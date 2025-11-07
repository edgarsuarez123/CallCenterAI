"""
Azure OpenAI service for conversational AI and intent classification.

This service provides:
- Intent classification from user input
- Response generation with context awareness
- Entity extraction from conversations
- Bilingual conversation support
- Streaming response capabilities
- Fallback response handling
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Union, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ExternalServiceUnavailableError,
    ValidationError,
    AzureCommunicationError
)
from services.bilingual_manager import get_bilingual_manager, LanguageCode
from services.response_cache import get_response_cache_service
from services.response_templates import get_response_templates


logger = get_logger("azure_openai_service")


from services.natural_language_processor import IntentType, EntityType, ExtractedEntities, IntentResult


@dataclass
class Entity:
    """Extracted entity from conversation."""
    type: EntityType
    value: str
    confidence: float
    start_position: int
    end_position: int
    context: Optional[str] = None


@dataclass
class ConversationMessage:
    """Message in a conversation."""
    role: str  # "system", "user", "assistant"
    content: str
    timestamp: datetime
    language: LanguageCode
    intent: Optional[IntentType] = None
    entities: List[Entity] = field(default_factory=list)


@dataclass
class ResponseResult:
    """Result of response generation."""
    response_text: str
    intent: Optional[IntentType]
    entities: List[Entity]
    processing_time_ms: int
    timestamp: datetime
    language: LanguageCode
    streaming: bool = False
    fallback_used: bool = False
    source: str = "ai_generated"  # "cache", "template", or "ai_generated"


class AzureOpenAIService:
    """
    Service for Azure OpenAI integration.
    
    Provides intent classification, response generation, and entity extraction
    for conversational AI in healthcare call center.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        self.bilingual_manager = get_bilingual_manager()
        
        # OpenAI configuration
        self.endpoint = self.settings.azure.openai.endpoint
        self.api_key = self.settings.azure.openai.api_key.get_secret_value()
        self.api_version = self.settings.azure.openai.api_version
        self.deployment_name = self.settings.azure.openai.deployment_name
        
        # Conversation settings
        self.max_tokens = self.settings.azure.openai.max_tokens
        self.temperature = self.settings.azure.openai.temperature
        self.system_prompt_en = self.settings.azure.openai.system_prompt_en
        self.system_prompt_es = self.settings.azure.openai.system_prompt_es
        
        # Feature flags
        self.enable_intent_classification = self.settings.azure.openai.enable_intent_classification
        self.enable_response_generation = self.settings.azure.openai.enable_response_generation
        self.enable_streaming_responses = self.settings.azure.openai.enable_streaming_responses
        self.enable_context_awareness = self.settings.azure.openai.enable_context_awareness
        self.enable_entity_extraction = self.settings.azure.openai.enable_entity_extraction
        self.enable_fallback_responses = self.settings.azure.openai.enable_fallback_responses
        
        # Thresholds and limits
        self.intent_confidence_threshold = self.settings.azure.openai.intent_confidence_threshold
        self.max_intent_retries = self.settings.azure.openai.max_intent_retries
        self.response_timeout_seconds = self.settings.azure.openai.response_timeout_seconds
        self.context_window_size = self.settings.azure.openai.context_window_size
        
        # Fallback responses
        self.fallback_response_en = self.settings.azure.openai.fallback_response_en
        self.fallback_response_es = self.settings.azure.openai.fallback_response_es
        
        # Initialize OpenAI client
        self._initialize_openai_client()
        
        # Initialize cache services
        self.response_cache = get_response_cache_service()
        self.response_templates = get_response_templates()
        self.enable_response_caching = True  # Configuration flag for caching
        
        # Conversation storage
        self.conversations: Dict[str, List[ConversationMessage]] = {}
        
        # Performance tracking
        self.intent_stats: Dict[str, Dict[str, Any]] = {}
        self.response_stats: Dict[str, Dict[str, Any]] = {}
        
        # Initialize locks for thread safety
        self._conversations_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
        
        # Intent classification prompts
        self.intent_prompts = {
            LanguageCode.ENGLISH: """
            Analyze the following user input and classify the intent. Respond with a JSON object containing:
            - "intent": one of the following: appointment_booking, appointment_cancellation, appointment_rescheduling, 
              appointment_inquiry, provider_inquiry, clinic_inquiry, billing_inquiry, emergency, general_inquiry, greeting, goodbye, unknown
            - "confidence": a number between 0 and 1
            - "entities": a list of extracted entities with type, value, and confidence
            
            User input: "{user_input}"
            """,
            LanguageCode.SPANISH: """
            Analiza la siguiente entrada del usuario y clasifica la intención. Responde con un objeto JSON que contenga:
            - "intent": uno de los siguientes: appointment_booking, appointment_cancellation, appointment_rescheduling,
              appointment_inquiry, provider_inquiry, clinic_inquiry, billing_inquiry, emergency, general_inquiry, greeting, goodbye, unknown
            - "confidence": un número entre 0 y 1
            - "entities": una lista de entidades extraídas con tipo, valor y confianza
            
            Entrada del usuario: "{user_input}"
            """
        }
        
        self.logger.info(
            "Azure OpenAI service initialized",
            LogCategory.AZURE_OPENAI,
            extra_data={
                "endpoint": self.endpoint,
                "deployment_name": self.deployment_name,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "enable_intent_classification": self.enable_intent_classification,
                "enable_response_generation": self.enable_response_generation
            }
        )
    
    def _initialize_openai_client(self):
        """Initialize the OpenAI client."""
        try:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=f"{self.endpoint}/openai/deployments/{self.deployment_name}"
            )
            
            self.logger.info(
                "OpenAI client initialized successfully",
                LogCategory.AZURE_OPENAI,
                extra_data={
                    "base_url": f"{self.endpoint}/openai/deployments/{self.deployment_name}",
                    "api_version": self.api_version
                }
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to initialize OpenAI client: {e}",
                LogCategory.AZURE_OPENAI,
                exception=e
            )
            raise ExternalServiceUnavailableError("Azure OpenAI", str(e))
    
    @log_performance("openai_classify_intent")
    async def classify_intent(self, user_input: str, call_id: str, 
                            language: LanguageCode = LanguageCode.ENGLISH) -> IntentResult:
        """
        Classify the intent of user input.
        
        Args:
            user_input: Text input from user
            call_id: ID of the call
            language: Language of the input
            
        Returns:
            Intent classification result
        """
        try:
            # Validate inputs
            if not user_input or not user_input.strip():
                raise ValidationError("user_input", user_input, "User input cannot be empty")
            
            if not self.enable_intent_classification:
                # Return default intent if classification is disabled
                return IntentResult(
                    intent=IntentType.UNKNOWN,
                    confidence=0.0,
                    entities=[],
                    raw_response="Intent classification disabled",
                    processing_time_ms=0,
                    timestamp=datetime.now(timezone.utc),
                    language=language,
                    fallback_used=True
                )
            
            start_time = time.time()
            
            # Get appropriate prompt
            prompt_template = self.intent_prompts.get(language, self.intent_prompts[LanguageCode.ENGLISH])
            prompt = prompt_template.format(user_input=user_input)
            
            # Make API call with retries
            for attempt in range(self.max_intent_retries):
                try:
                    # Issue 96: Handle rate limiting with retries and backoff
                    response = await self.client.chat.completions.create(
                        model=self.deployment_name,
                        messages=[
                            {"role": "system", "content": "You are an expert intent classifier for healthcare call centers."},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=200,
                        temperature=0.1,  # Low temperature for consistent classification
                        timeout=self.response_timeout_seconds
                    )
                    
                    # Parse response (with null checks)
                    if not response.choices or len(response.choices) == 0:
                        raise ValueError("Empty response from OpenAI")
                    
                    response_text = response.choices[0].message.content
                    if not response_text:
                        raise ValueError("Empty response content from OpenAI")
                    
                    intent_data = json.loads(response_text)
                    
                    # Extract intent
                    intent_str = intent_data.get("intent", "unknown")
                    try:
                        intent = IntentType(intent_str)
                    except ValueError:
                        intent = IntentType.UNKNOWN
                    
                    # Extract confidence
                    confidence = float(intent_data.get("confidence", 0.0))
                    
                    # Extract entities
                    entities = intent_data.get("entities", [])
                    
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    
                    # Create result
                    result = IntentResult(
                        intent=intent,
                        confidence=confidence,
                        entities=entities,
                        raw_response=response_text,
                        processing_time_ms=processing_time_ms,
                        timestamp=datetime.now(timezone.utc),
                        language=language
                    )
                    
                    # Update statistics
                    await self._update_intent_stats(call_id, result)
                    
                    # Store in conversation history
                    await self._add_to_conversation(call_id, "user", user_input, language, intent, entities)
                    
                    self.logger.info(
                        f"Intent classified for call {call_id}",
                        LogCategory.AZURE_OPENAI,
                        extra_data={
                            "call_id": call_id,
                            "intent": intent.value,
                            "confidence": confidence,
                            "entities_count": len(entities),
                            "processing_time_ms": processing_time_ms,
                            "language": language.value
                        }
                    )
                    
                    return result
                    
                except json.JSONDecodeError as e:
                    self.logger.warning(
                        f"Failed to parse intent classification response (attempt {attempt + 1}): {e}",
                        LogCategory.AZURE_OPENAI
                    )
                    if attempt == self.max_intent_retries - 1:
                        # Return fallback result
                        return self._create_fallback_intent_result(user_input, call_id, language, start_time)
                except Exception as e:
                    error_str = str(e).lower()
                    # Issue 96: Check for rate limit errors
                    if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
                        if attempt < self.max_intent_retries - 1:
                            # Issue 96: Exponential backoff for rate limit errors
                            wait_time = 1.0 * (2 ** attempt)
                            self.logger.warning(
                                f"Rate limit exceeded for intent classification (attempt {attempt + 1}), retrying in {wait_time}s",
                                LogCategory.AZURE_OPENAI
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            # Issue 96: Max retries reached, return fallback
                            self.logger.error(
                                f"Rate limit exceeded after {self.max_intent_retries} retries for intent classification",
                                LogCategory.AZURE_OPENAI
                            )
                            return self._create_fallback_intent_result(user_input, call_id, language, start_time)
                    else:
                        # Non-rate-limit error
                        self.logger.warning(
                            f"Intent classification attempt {attempt + 1} failed: {e}",
                            LogCategory.AZURE_OPENAI
                        )
                        if attempt == self.max_intent_retries - 1:
                            # Return fallback result
                            return self._create_fallback_intent_result(user_input, call_id, language, start_time)
            
        except Exception as e:
            self.logger.error(
                f"Failed to classify intent for call {call_id}: {e}",
                LogCategory.AZURE_OPENAI,
                exception=e
            )
            raise
    
    def _create_fallback_intent_result(self, user_input: str, call_id: str, 
                                     language: LanguageCode, start_time: float) -> IntentResult:
        """Create a fallback intent result when classification fails."""
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Simple keyword-based fallback classification
        user_input_lower = user_input.lower()
        
        if any(word in user_input_lower for word in ["book", "schedule", "appointment", "cita", "agendar"]):
            intent = IntentType.APPOINTMENT_BOOKING
        elif any(word in user_input_lower for word in ["cancel", "cancelar"]):
            intent = IntentType.APPOINTMENT_CANCELLATION
        elif any(word in user_input_lower for word in ["reschedule", "reagendar", "change", "cambiar"]):
            intent = IntentType.APPOINTMENT_RESCHEDULING
        elif any(word in user_input_lower for word in ["hello", "hi", "hola", "buenos"]):
            intent = IntentType.GREETING
        elif any(word in user_input_lower for word in ["bye", "goodbye", "adios", "hasta"]):
            intent = IntentType.GOODBYE
        elif any(word in user_input_lower for word in ["emergency", "emergencia", "urgent", "urgente"]):
            intent = IntentType.EMERGENCY
        else:
            intent = IntentType.GENERAL_INQUIRY
        
        return IntentResult(
            intent=intent,
            confidence=0.3,  # Low confidence for fallback
            entities=[],
            raw_response="Fallback classification",
            processing_time_ms=processing_time_ms,
            timestamp=datetime.now(timezone.utc),
            language=language,
            fallback_used=True
        )
    
    @log_performance("openai_generate_response")
    async def generate_response(self, user_input: str, call_id: str,
                              language: LanguageCode = LanguageCode.ENGLISH,
                              intent: Optional[IntentType] = None,
                              entities: Optional[List[Dict[str, Any]]] = None) -> ResponseResult:
        """
        Generate a response to user input with caching support.
        
        Args:
            user_input: Text input from user
            call_id: ID of the call
            language: Language for response
            intent: Classified intent (optional)
            entities: Extracted entities (optional)
            
        Returns:
            Generated response result
        """
        try:
            # Validate inputs
            if not user_input or not user_input.strip():
                raise ValidationError("user_input", user_input, "User input cannot be empty")
            
            if not self.enable_response_generation:
                # Return fallback response if generation is disabled
                return self._create_fallback_response(call_id, language)
            
            start_time = time.time()
            
            # Check cache first if caching is enabled and intent is available
            if self.enable_response_caching and intent:
                cached_response = await self._get_cached_response(intent, language, entities, call_id)
                if cached_response:
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    
                    # Create result from cache
                    result = ResponseResult(
                        response_text=cached_response,
                        intent=intent,
                        entities=entities or [],
                        processing_time_ms=processing_time_ms,
                        timestamp=datetime.now(timezone.utc),
                        language=language,
                        source="cache"
                    )
                    
                    # Update statistics
                    await self._update_response_stats(call_id, result)
                    
                    # Store in conversation history
                    await self._add_to_conversation(call_id, "assistant", cached_response, language, intent, entities or [])
                    
                    self.logger.info(
                        f"Cached response used for call {call_id}",
                        LogCategory.AZURE_OPENAI,
                        extra_data={
                            "call_id": call_id,
                            "response_length": len(cached_response),
                            "processing_time_ms": processing_time_ms,
                            "language": language.value,
                            "intent": intent.value,
                            "source": "cache"
                        }
                    )
                    
                    return result
            
            # Generate new response using Azure OpenAI
            response_text = await self._generate_ai_response(user_input, call_id, language, intent, entities)
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            # Extract entities from response if enabled
            response_entities = []
            if self.enable_entity_extraction:
                response_entities = await self._extract_entities_from_text(response_text, language)
            
            # Create result
            result = ResponseResult(
                response_text=response_text,
                intent=intent,
                entities=response_entities,
                processing_time_ms=processing_time_ms,
                timestamp=datetime.now(timezone.utc),
                language=language,
                source="ai_generated"
            )
            
            # Cache the response if caching is enabled and intent is available
            if self.enable_response_caching and intent:
                await self._cache_ai_response(intent, language, response_text, entities, call_id)
            
            # Update statistics (with await - it's async)
            await self._update_response_stats(call_id, result)
            
            # Store in conversation history
            await self._add_to_conversation(call_id, "assistant", response_text, language, intent, response_entities)
            
            self.logger.info(
                f"AI response generated for call {call_id}",
                LogCategory.AZURE_OPENAI,
                extra_data={
                    "call_id": call_id,
                    "response_length": len(response_text),
                    "processing_time_ms": processing_time_ms,
                    "language": language.value,
                    "intent": intent.value if intent else None,
                    "source": "ai_generated"
                }
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"Failed to generate response for call {call_id}: {e}",
                LogCategory.AZURE_OPENAI,
                exception=e
            )
            
            # Return fallback response
            return self._create_fallback_response(call_id, language)
    
    async def _get_cached_response(
        self, 
        intent: IntentType, 
        language: LanguageCode, 
        entities: Optional[List[Dict[str, Any]]], 
        call_id: str
    ) -> Optional[str]:
        """
        Get cached response for intent and language.
        
        Args:
            intent: Intent type
            language: Language code
            entities: Extracted entities
            call_id: Call ID for context
            
        Returns:
            Optional[str]: Cached response if found, None otherwise
        """
        try:
            # Check if template exists first
            if self.response_templates.has_template(intent, language):
                # Extract variables from entities
                variables = self._extract_variables_from_entities(entities)
                
                # Try to get template response
                template_response = self.response_templates.substitute_variables(intent, language, variables)
                if template_response:
                    # Cache the template response
                    await self.response_cache.cache_response(
                        intent=intent.value,
                        language=language.value,
                        response=template_response,
                        template=self.response_templates.get_template(intent, language).template,
                        variables=variables,
                        source="template"
                    )
                    return template_response
            
            # Try cache for AI-generated responses
            variables = self._extract_variables_from_entities(entities)
            cached_response = await self.response_cache.get_cached_response(
                intent=intent.value,
                language=language.value,
                variables=variables
            )
            
            return cached_response
            
        except Exception as e:
            self.logger.warning(
                f"Error getting cached response: {e}",
                LogCategory.AZURE_OPENAI,
                extra_data={"intent": intent.value, "language": language.value}
            )
            return None
    
    async def _cache_ai_response(
        self, 
        intent: IntentType, 
        language: LanguageCode, 
        response_text: str, 
        entities: Optional[List[Dict[str, Any]]], 
        call_id: str
    ) -> bool:
        """
        Cache AI-generated response.
        
        Args:
            intent: Intent type
            language: Language code
            response_text: Generated response text
            entities: Extracted entities
            call_id: Call ID for context
            
        Returns:
            bool: True if cached successfully, False otherwise
        """
        try:
            # Only cache certain types of responses
            cacheable_intents = {
                IntentType.GREETING,
                IntentType.GOODBYE,
                IntentType.APPOINTMENT_BOOKING,
                IntentType.APPOINTMENT_INQUIRY,
                IntentType.PROVIDER_INQUIRY,
                IntentType.CLINIC_INQUIRY,
                IntentType.BILLING_INQUIRY,
                IntentType.GENERAL_INQUIRY
            }
            
            if intent not in cacheable_intents:
                return False
            
            # Extract variables from entities
            variables = self._extract_variables_from_entities(entities)
            
            # Cache the response
            return await self.response_cache.cache_response(
                intent=intent.value,
                language=language.value,
                response=response_text,
                variables=variables,
                source="ai_generated"
            )
            
        except Exception as e:
            self.logger.warning(
                f"Error caching AI response: {e}",
                LogCategory.AZURE_OPENAI,
                extra_data={"intent": intent.value, "language": language.value}
            )
            return False
    
    async def _generate_ai_response(
        self, 
        user_input: str, 
        call_id: str, 
        language: LanguageCode, 
        intent: Optional[IntentType], 
        entities: Optional[List[Dict[str, Any]]]
    ) -> str:
        """
        Generate response using Azure OpenAI.
        
        Args:
            user_input: User input text
            call_id: Call ID
            language: Language code
            intent: Intent type
            entities: Extracted entities
            
        Returns:
            str: Generated response text
        """
        # Get system prompt for language
        system_prompt = self.system_prompt_en if language == LanguageCode.ENGLISH else self.system_prompt_es
        
        # Build conversation context
        messages = [{"role": "system", "content": system_prompt}]
        
        if self.enable_context_awareness:
            async with self._conversations_lock:
                if call_id in self.conversations:
                    # Add recent conversation history (with bounds check)
                    conversation = self.conversations[call_id]
                    if conversation:
                        start_idx = max(0, len(conversation) - self.context_window_size)
                        recent_messages = conversation[start_idx:]
                    else:
                        recent_messages = []
                else:
                    recent_messages = []
            
            for msg in recent_messages:
                messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Add current user input
        messages.append({"role": "user", "content": user_input})
        
        # Issue 96: Handle rate limiting with retries and backoff
        max_retries = 3
        retry_delay = 1.0  # Start with 1 second delay
        
        for attempt in range(max_retries):
            try:
                # Generate response
                response = await self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=self.response_timeout_seconds
                )
                break  # Success, exit retry loop
            except Exception as api_error:
                error_str = str(api_error).lower()
                # Issue 96: Check for rate limit errors
                if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
                    if attempt < max_retries - 1:
                        # Issue 96: Exponential backoff for rate limit errors
                        wait_time = retry_delay * (2 ** attempt)
                        self.logger.warning(
                            f"Rate limit exceeded for call {call_id}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})",
                            LogCategory.AZURE_OPENAI
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # Issue 96: Max retries reached, return fallback
                        self.logger.error(
                            f"Rate limit exceeded after {max_retries} retries for call {call_id}",
                            LogCategory.AZURE_OPENAI
                        )
                        raise
                else:
                    # Non-rate-limit error, re-raise immediately
                    raise
        
        # Validate response (with null checks)
        if not response.choices or len(response.choices) == 0:
            raise ValueError("Empty response from OpenAI")
        
        response_content = response.choices[0].message.content
        if not response_content:
            raise ValueError("Empty response content from OpenAI")
        
        return response_content
    
    def _extract_variables_from_entities(self, entities: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Extract template variables from entities.
        
        Args:
            entities: List of extracted entities
            
        Returns:
            Dict[str, Any]: Variables for template substitution
        """
        variables = {}
        
        if not entities:
            return variables
        
        for entity in entities:
            entity_type = entity.get("type", "").lower()
            entity_value = entity.get("value", "")
            
            # Map entity types to template variables
            if entity_type in ["clinic_name", "clinic"]:
                variables["clinic_name"] = entity_value
            elif entity_type in ["patient_name", "name"]:
                variables["patient_name"] = entity_value
            elif entity_type in ["appointment_date", "date"]:
                variables["date"] = entity_value
            elif entity_type in ["appointment_time", "time"]:
                variables["time"] = entity_value
            elif entity_type in ["provider_name", "doctor"]:
                variables["provider_name"] = entity_value
        
        return variables
    
    async def generate_streaming_response(self, user_input: str, call_id: str,
                                        language: LanguageCode = LanguageCode.ENGLISH,
                                        intent: Optional[IntentType] = None) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response to user input.
        
        Args:
            user_input: Text input from user
            call_id: ID of the call
            language: Language for response
            intent: Classified intent (optional)
            
        Yields:
            Response text chunks
        """
        try:
            if not self.enable_streaming_responses:
                # Fall back to regular response generation
                result = await self.generate_response(user_input, call_id, language, intent)
                yield result.response_text
                return
            
            # Get system prompt for language
            system_prompt = self.system_prompt_en if language == LanguageCode.ENGLISH else self.system_prompt_es
            
            # Build conversation context
            messages = [{"role": "system", "content": system_prompt}]
            
            if self.enable_context_awareness:
                async with self._conversations_lock:
                    if call_id in self.conversations:
                        # Add recent conversation history (with bounds check)
                        conversation = self.conversations[call_id]
                        if conversation:
                            start_idx = max(0, len(conversation) - self.context_window_size)
                            recent_messages = conversation[start_idx:]
                        else:
                            recent_messages = []
                    else:
                        recent_messages = []
                
                for msg in recent_messages:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            # Add current user input
            messages.append({"role": "user", "content": user_input})
            
            # Issue 96: Handle rate limiting with retries and backoff for streaming
            max_retries = 3
            retry_delay = 1.0
            
            for attempt in range(max_retries):
                try:
                    # Generate streaming response
                    stream = await self.client.chat.completions.create(
                        model=self.deployment_name,
                        messages=messages,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        stream=True,
                        timeout=self.response_timeout_seconds
                    )
                    break  # Success, exit retry loop
                except Exception as api_error:
                    error_str = str(api_error).lower()
                    # Issue 96: Check for rate limit errors
                    if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            self.logger.warning(
                                f"Rate limit exceeded for streaming response (attempt {attempt + 1}), retrying in {wait_time}s",
                                LogCategory.AZURE_OPENAI
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            self.logger.error(
                                f"Rate limit exceeded after {max_retries} retries for streaming response",
                                LogCategory.AZURE_OPENAI
                            )
                            raise
                    else:
                        raise
            
            full_response = ""
            async for chunk in stream:
                # Validate chunk (with null checks)
                if not chunk.choices or len(chunk.choices) == 0:
                    continue
                
                if chunk.choices[0].delta and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
            
            # Store complete response in conversation history
            await self._add_to_conversation(call_id, "assistant", full_response, language, intent, [])
            
            self.logger.info(
                f"Streaming response generated for call {call_id}",
                LogCategory.AZURE_OPENAI,
                extra_data={
                    "call_id": call_id,
                    "response_length": len(full_response),
                    "language": language.value
                }
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to generate streaming response for call {call_id}: {e}",
                LogCategory.AZURE_OPENAI,
                exception=e
            )
            
            # Yield fallback response
            fallback_response = self.fallback_response_en if language == LanguageCode.ENGLISH else self.fallback_response_es
            yield fallback_response
    
    def _create_fallback_response(self, call_id: str, language: LanguageCode) -> ResponseResult:
        """Create a fallback response when generation fails."""
        fallback_text = self.fallback_response_en if language == LanguageCode.ENGLISH else self.fallback_response_es
        
        return ResponseResult(
            response_text=fallback_text,
            intent=None,
            entities=[],
            processing_time_ms=0,
            timestamp=datetime.now(timezone.utc),
            language=language,
            fallback_used=True
        )
    
    async def _extract_entities_from_text(self, text: str, language: LanguageCode) -> List[Entity]:
        """
        Extract entities from text using OpenAI.
        
        Args:
            text: Text to extract entities from
            language: Language of the text
            
        Returns:
            List of extracted entities
        """
        try:
            if not self.enable_entity_extraction:
                return []
            
            # Create entity extraction prompt
            prompt = f"""
            Extract entities from the following text. Respond with a JSON array of entities, each containing:
            - "type": one of: date, time, phone_number, email, name, appointment_type, provider_name, clinic_name, symptoms, medication, insurance
            - "value": the extracted value
            - "confidence": confidence score (0-1)
            - "start_position": character position where entity starts
            - "end_position": character position where entity ends
            
            Text: "{text}"
            """
            
            # Issue 96: Handle rate limiting with retries and backoff for entity extraction
            max_retries = 3
            retry_delay = 1.0
            
            for attempt in range(max_retries):
                try:
                    response = await self.client.chat.completions.create(
                        model=self.deployment_name,
                        messages=[
                            {"role": "system", "content": "You are an expert entity extractor for healthcare conversations."},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=500,
                        temperature=0.1,
                        timeout=10
                    )
                    break  # Success, exit retry loop
                except Exception as api_error:
                    error_str = str(api_error).lower()
                    # Issue 96: Check for rate limit errors
                    if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            self.logger.warning(
                                f"Rate limit exceeded for entity extraction (attempt {attempt + 1}), retrying in {wait_time}s",
                                LogCategory.AZURE_OPENAI
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            self.logger.error(
                                f"Rate limit exceeded after {max_retries} retries for entity extraction",
                                LogCategory.AZURE_OPENAI
                            )
                            return []  # Return empty entities on rate limit failure
                    else:
                        # Non-rate-limit error, return empty entities
                        self.logger.warning(f"Entity extraction failed: {api_error}")
                        return []
            
            # Validate response (with null checks)
            if not response.choices or len(response.choices) == 0:
                self.logger.warning("Empty response from OpenAI for entity extraction")
                return []
            
            response_text = response.choices[0].message.content
            if not response_text:
                self.logger.warning("Empty response content from OpenAI for entity extraction")
                return []
            
            try:
                entities_data = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.logger.warning(f"Failed to parse entity extraction response: {e}")
                return []
            
            if not isinstance(entities_data, list):
                self.logger.warning("Entity extraction response is not a list")
                return []
            
            entities = []
            for entity_data in entities_data:
                try:
                    entity = Entity(
                        type=EntityType(entity_data["type"]),
                        value=entity_data["value"],
                        confidence=float(entity_data["confidence"]),
                        start_position=int(entity_data["start_position"]),
                        end_position=int(entity_data["end_position"])
                    )
                    entities.append(entity)
                except (ValueError, KeyError) as e:
                    self.logger.warning(f"Failed to parse entity: {e}")
                    continue
            
            return entities
            
        except Exception as e:
            self.logger.error(f"Failed to extract entities: {e}")
            return []
    
    async def _add_to_conversation(self, call_id: str, role: str, content: str,
                                 language: LanguageCode, intent: Optional[IntentType] = None,
                                 entities: Optional[List[Dict[str, Any]]] = None):
        """Add a message to the conversation history."""
        try:
            async with self._conversations_lock:
                if call_id not in self.conversations:
                    self.conversations[call_id] = []
                
                # Convert entities to Entity objects
                entity_objects = []
                if entities:
                    for entity_data in entities:
                        try:
                            entity = Entity(
                                type=EntityType(entity_data.get("type", "unknown")),
                                value=entity_data.get("value", ""),
                                confidence=float(entity_data.get("confidence", 0.0)),
                                start_position=int(entity_data.get("start_position", 0)),
                                end_position=int(entity_data.get("end_position", 0))
                            )
                            entity_objects.append(entity)
                        except (ValueError, KeyError):
                            continue
                
                message = ConversationMessage(
                    role=role,
                    content=content,
                    timestamp=datetime.now(timezone.utc),
                    language=language,
                    intent=intent,
                    entities=entity_objects
                )
                
                self.conversations[call_id].append(message)
                
                # Issue 49, 97: Properly truncate conversation history when it exceeds the limit
                # Keep the most recent messages and system message
                max_messages = 50  # Maximum conversation history size
                if len(self.conversations[call_id]) > max_messages:
                    # Keep the most recent messages, preserving important context
                    # Remove oldest messages but keep at least the last max_messages
                    self.conversations[call_id] = self.conversations[call_id][-max_messages:]
                    self.logger.debug(f"Truncated conversation history for call {call_id} to {max_messages} messages")
                
        except Exception as e:
            self.logger.error(f"Failed to add message to conversation: {e}")
    
    async def _update_intent_stats(self, call_id: str, result: IntentResult):
        """Update intent classification statistics."""
        if not call_id:
            return
        
        async with self._stats_lock:
            if call_id not in self.intent_stats:
                self.intent_stats[call_id] = {
                    "start_time": datetime.now(timezone.utc),
                    "total_classifications": 0,
                    "successful_classifications": 0,
                    "high_confidence_classifications": 0,
                    "fallback_classifications": 0,
                    "intent_counts": {},
                    "total_processing_time": 0
                }
            
            stats = self.intent_stats[call_id]
            stats["total_classifications"] += 1
            stats["total_processing_time"] += result.processing_time_ms
            
            if not result.fallback_used:
                stats["successful_classifications"] += 1
                
                if result.confidence >= self.intent_confidence_threshold:
                    stats["high_confidence_classifications"] += 1
            else:
                stats["fallback_classifications"] += 1
            
            intent_name = result.intent.value
            if intent_name not in stats["intent_counts"]:
                stats["intent_counts"][intent_name] = 0
            stats["intent_counts"][intent_name] += 1
    
    async def _update_response_stats(self, call_id: str, result: ResponseResult):
        """Update response generation statistics."""
        if not call_id:
            return
        
        async with self._stats_lock:
            if call_id not in self.response_stats:
                self.response_stats[call_id] = {
                    "start_time": datetime.now(timezone.utc),
                    "total_responses": 0,
                    "successful_responses": 0,
                    "fallback_responses": 0,
                    "total_processing_time": 0,
                    "total_response_length": 0
                }
            
            stats = self.response_stats[call_id]
            stats["total_responses"] += 1
            stats["total_processing_time"] += result.processing_time_ms
            stats["total_response_length"] += len(result.response_text) if result.response_text else 0
            
            if not result.fallback_used:
                stats["successful_responses"] += 1
            else:
                stats["fallback_responses"] += 1
    
    async def get_conversation_history(self, call_id: str, limit: int = 10) -> List[ConversationMessage]:
        """
        Get conversation history for a call.
        
        Args:
            call_id: ID of the call
            limit: Maximum number of messages to return
            
        Returns:
            List of conversation messages
        """
        if not call_id:
            return []
        
        async with self._conversations_lock:
            if call_id not in self.conversations:
                return []
            
            messages = self.conversations[call_id]
            if limit > 0 and len(messages) > limit:
                return messages[-limit:]
            return messages
    
    def get_intent_statistics(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get intent classification statistics for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Intent statistics or None
        """
        if call_id not in self.intent_stats:
            return None
        
        stats = self.intent_stats[call_id].copy()
        stats["duration_seconds"] = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds()
        
        # Division by zero check
        if stats["total_classifications"] > 0:
            stats["success_rate"] = stats["successful_classifications"] / stats["total_classifications"]
            stats["high_confidence_rate"] = stats["high_confidence_classifications"] / stats["total_classifications"]
            stats["fallback_rate"] = stats["fallback_classifications"] / stats["total_classifications"]
            stats["average_processing_time"] = stats["total_processing_time"] / stats["total_classifications"]
        else:
            stats["success_rate"] = 0.0
            stats["high_confidence_rate"] = 0.0
            stats["fallback_rate"] = 0.0
            stats["average_processing_time"] = 0.0
        
        return stats
    
    def get_response_statistics(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get response generation statistics for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Response statistics or None
        """
        if call_id not in self.response_stats:
            return None
        
        stats = self.response_stats[call_id].copy()
        stats["duration_seconds"] = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds()
        
        # Division by zero check
        if stats["total_responses"] > 0:
            stats["success_rate"] = stats["successful_responses"] / stats["total_responses"]
            stats["fallback_rate"] = stats["fallback_responses"] / stats["total_responses"]
            stats["average_processing_time"] = stats["total_processing_time"] / stats["total_responses"]
            stats["average_response_length"] = stats["total_response_length"] / stats["total_responses"]
        else:
            stats["success_rate"] = 0.0
            stats["fallback_rate"] = 0.0
            stats["average_processing_time"] = 0.0
            stats["average_response_length"] = 0.0
        
        return stats
    
    async def get_active_conversations_count(self) -> int:
        """Get count of active conversations."""
        async with self._conversations_lock:
            return len(self.conversations)
    
    async def cleanup_expired_conversations(self):
        """Remove old conversations from memory."""
        current_time = datetime.now(timezone.utc)
        expired_calls = []
        
        # Create a copy of conversations to iterate over safely
        async with self._conversations_lock:
            conversations_copy = dict(self.conversations)
        
        for call_id, messages in conversations_copy.items():
            if not messages:
                expired_calls.append(call_id)
                continue
            
            last_message_time = messages[-1].timestamp
            # Remove after 5 minutes of inactivity (user requirement)
            time_since_last_message = (current_time - last_message_time).total_seconds()
            
            if time_since_last_message > 300:  # 5 minutes = 300 seconds
                expired_calls.append(call_id)
        
        # Remove expired conversations with lock
        async with self._conversations_lock:
            for call_id in expired_calls:
                if call_id in self.conversations:
                    del self.conversations[call_id]
                if call_id in self.intent_stats:
                    del self.intent_stats[call_id]
                if call_id in self.response_stats:
                    del self.response_stats[call_id]
                
                self.logger.info(f"Cleaned up expired OpenAI conversation: {call_id}")
    
    async def end_conversation(self, call_id: str):
        """Explicitly end and clean up a conversation when call finishes."""
        if not call_id:
            return
        
        async with self._conversations_lock:
            if call_id in self.conversations:
                del self.conversations[call_id]
            if call_id in self.intent_stats:
                del self.intent_stats[call_id]
            if call_id in self.response_stats:
                del self.response_stats[call_id]
            self.logger.info(f"Conversation {call_id} ended and cleaned up")


# Global service instance
_azure_openai_service: Optional[AzureOpenAIService] = None


def get_azure_openai_service() -> AzureOpenAIService:
    """Get the global Azure OpenAI Service instance."""
    global _azure_openai_service
    if _azure_openai_service is None:
        _azure_openai_service = AzureOpenAIService()
    return _azure_openai_service
