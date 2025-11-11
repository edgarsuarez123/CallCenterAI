"""
NLP Service for conversational AI and intent classification.

This service provides:
- Intent classification from user input using Azure OpenAI
- Response generation with context awareness
- Bilingual conversation support
- Fallback response handling

This is the single entry point for all NLP operations, replacing the previous
hybrid NLP service and local NLP engine.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum

import openai
from openai import AsyncOpenAI

from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ExternalServiceUnavailableError,
    ValidationError,
    AzureCommunicationError
)
from models.enums import LanguageCode
# Import call_orchestrator inside __init__ to avoid circular import
from services.response_service import get_response_cache_service, get_response_templates, get_response_router


logger = get_logger("nlp_service")


# ---------- Intent and Entity Types (Single Source of Truth) ----------
class IntentType(Enum):
    """Intent types for user input classification."""
    APPOINTMENT_BOOKING = "appointment_booking"
    APPOINTMENT_CANCELLATION = "appointment_cancellation"
    APPOINTMENT_RESCHEDULING = "appointment_rescheduling"
    APPOINTMENT_INQUIRY = "appointment_inquiry"
    INSURANCE_INQUIRY = "insurance_inquiry"
    PROVIDER_INQUIRY = "provider_inquiry"
    CLINIC_INQUIRY = "clinic_inquiry"
    BILLING_INQUIRY = "billing_inquiry"
    GENERAL_INQUIRY = "general_inquiry"
    EMERGENCY = "emergency"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    CONFIRMATION = "confirmation"
    NEGATION = "negation"
    UNCLEAR = "unclear"
    UNKNOWN = "unknown"


# Note: EntityType enum removed - entities are extracted as dicts during intent classification

@dataclass
class ExtractedEntities:
    """Extracted entities from user input."""
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    insurance_provider: Optional[str] = None
    provider_name: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class IntentResult:
    """Result of intent analysis."""
    intent: IntentType
    confidence: float
    entities: Union[ExtractedEntities, List[Dict[str, Any]]]  # Can be ExtractedEntities or list of dicts
    original_text: str = ""
    processed_text: str = ""
    raw_response: Optional[str] = None
    processing_time_ms: int = 0
    timestamp: Optional[datetime] = None
    language: Optional[LanguageCode] = None
    fallback_used: bool = False
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if self.original_text is None:
            self.original_text = ""
        if self.processed_text is None:
            self.processed_text = self.original_text


# Note: Entity dataclass removed - entities are extracted as dicts during intent classification
# Note: ConversationMessage dataclass removed - conversation history storage removed


@dataclass
class ResponseResult:
    """Result of response generation."""
    response_text: str
    intent: Optional[IntentType]
    entities: Union[ExtractedEntities, List[Dict[str, Any]]]  # Can be ExtractedEntities or list of dicts
    processing_time_ms: int
    timestamp: datetime
    language: LanguageCode
    fallback_used: bool = False
    source: str = "ai_generated"  # "cache", "template", or "ai_generated"


class NLPService:
    """
    NLP Service - Single entry point for all NLP operations.
    
    Provides intent classification and response generation
    for conversational AI in healthcare call center using Azure OpenAI.
    
    This service replaces the previous hybrid NLP service and local NLP engine,
    providing a unified interface for all NLP operations.
    
    Note: Entities are extracted during intent classification (as dicts),
    not separately from responses. Conversation history is managed by call_orchestrator.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        # Note: call_orchestrator is not needed during initialization to avoid circular import
        # It can be imported lazily if needed in the future
        
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
        self.enable_context_awareness = self.settings.azure.openai.enable_context_awareness
        # Note: enable_entity_extraction removed - entities already extracted during intent classification
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
        
        # Note: Conversation storage, statistics tracking removed - not used externally
        
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
    
    async def _get_system_prompt(self, language: LanguageCode, clinic_id: Optional[str] = None) -> str:
        """
        Get system prompt for language, with clinic-specific override if available.
        
        Args:
            language: Language code
            clinic_id: Optional clinic ID for clinic-specific prompt
            
        Returns:
            str: System prompt text
        """
        # Try to get clinic-specific prompt if clinic_id provided
        if clinic_id:
            try:
                from services.database import get_async_db_session
                from services.clinic_management import ClinicManagementService
                
                async with get_async_db_session() as db:
                    service = ClinicManagementService(db)
                    prompt_key = f'ai_system_prompt_{"en" if language == LanguageCode.ENGLISH else "es"}'
                    clinic_prompt = await service.get_clinic_config(clinic_id, prompt_key)
                    
                    if clinic_prompt:
                        # Get clinic name for template substitution
                        clinic = await service.get_clinic(clinic_id)
                        if clinic:
                            clinic_prompt = clinic_prompt.format(clinic_name=clinic.clinic_name)
                        return clinic_prompt
            except Exception as e:
                self.logger.warning(f"Failed to load clinic-specific prompt for {clinic_id}: {e}")
        
        # Fall back to default prompt
        default_prompt = self.system_prompt_en if language == LanguageCode.ENGLISH else self.system_prompt_es
        return default_prompt
    
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
                    
                    # Note: Statistics tracking and conversation history removed - not used externally
                    
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
                    # Issue 3.4: Check for rate limit errors with improved backoff and jitter
                    if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
                        if attempt < self.max_intent_retries - 1:
                            # Issue 3.4: Exponential backoff with jitter for rate limit errors
                            import random
                            base_wait = 1.0 * (2 ** attempt)
                            jitter = random.uniform(0, base_wait * 0.1)  # 10% jitter
                            wait_time = base_wait + jitter
                            self.logger.warning(
                                f"Rate limit exceeded for intent classification (attempt {attempt + 1}), retrying in {wait_time:.2f}s",
                                LogCategory.AZURE_OPENAI,
                                extra_data={"attempt": attempt + 1, "wait_time": wait_time}
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
                              entities: Optional[List[Dict[str, Any]]] = None,
                              clinic_id: Optional[str] = None) -> ResponseResult:
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
                    
                    # Note: Statistics tracking and conversation history removed - not used externally
                    
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
            response_text = await self._generate_ai_response(user_input, call_id, language, intent, entities, clinic_id)
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            # Note: Entity extraction from response removed - entities already extracted during intent classification
            # Note: Statistics tracking and conversation history removed - not used externally
            
            # Create result
            result = ResponseResult(
                response_text=response_text,
                intent=intent,
                entities=entities or [],  # Use entities from intent classification
                processing_time_ms=processing_time_ms,
                timestamp=datetime.now(timezone.utc),
                language=language,
                source="ai_generated"
            )
            
            # Cache the response if caching is enabled and intent is available
            if self.enable_response_caching and intent:
                await self._cache_ai_response(intent, language, response_text, entities, call_id)
            
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
        Get cached response for intent and language using ResponseRouter.
        
        Args:
            intent: Intent type
            language: Language code
            entities: Extracted entities
            call_id: Call ID for context
            
        Returns:
            Optional[str]: Cached response if found, None otherwise
        """
        try:
            # Use ResponseRouter for centralized routing logic
            response_router = get_response_router()
            
            # Extract variables from entities for template substitution
            variables = self._extract_variables_from_entities(entities)
            
            # Try ResponseRouter (handles templates and cache)
            # Note: We don't have CallContext here, so we pass language and entities directly
            router_result = await response_router.get_response(
                user_input="",  # Not needed for template checking
                intent=intent,
                call_context=None,  # No CallContext available
                clinic_config=None,
                entities=entities,
                language=language,
                clinic_id=None,  # Will be loaded from template variables if needed
                call_id=call_id
            )
            
            # If ResponseRouter found a template response, cache it and return
            if router_result.is_scripted and router_result.text:
                # Cache the template response
                await self.response_cache.cache_response(
                    intent=intent.value,
                    language=language.value,
                    response=router_result.text,
                    template=self.response_templates.get_template(intent, language).template if self.response_templates.has_template(intent, language) else None,
                    variables=variables,
                    source="template"
                )
                return router_result.text
            
            # If no template, try cache for AI-generated responses
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
                extra_data={"intent": intent.value, "language": language.value},
                exception=e
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
        entities: Optional[List[Dict[str, Any]]],
        clinic_id: Optional[str] = None
    ) -> str:
        """
        Generate response using Azure OpenAI.
        
        Args:
            user_input: User input text
            call_id: Call ID
            language: Language code
            intent: Intent type
            entities: Extracted entities
            clinic_id: Optional clinic ID for clinic-specific prompts
            
        Returns:
            str: Generated response text
        """
        # Get system prompt for language (clinic-specific if available)
        system_prompt = await self._get_system_prompt(language, clinic_id)
        
        # Build conversation context
        messages = [{"role": "system", "content": system_prompt}]
        
        # Note: Context awareness removed - conversation history storage removed
        # If context awareness is needed, use call_orchestrator's conversation_history instead
        
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
                # Issue 3.4: Check for rate limit errors with improved backoff and jitter
                if 'rate limit' in error_str or '429' in error_str or 'too many requests' in error_str:
                    if attempt < max_retries - 1:
                        # Issue 3.4: Exponential backoff with jitter for rate limit errors
                        import random
                        base_wait = retry_delay * (2 ** attempt)
                        jitter = random.uniform(0, base_wait * 0.1)  # 10% jitter
                        wait_time = base_wait + jitter
                        self.logger.warning(
                            f"Rate limit exceeded for call {call_id}, retrying in {wait_time:.2f}s (attempt {attempt + 1}/{max_retries})",
                            LogCategory.AZURE_OPENAI,
                            extra_data={"call_id": call_id, "attempt": attempt + 1, "wait_time": wait_time}
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
    
    async def cleanup_expired_conversations(self):
        """Remove old conversations from memory (no-op - conversation storage removed)."""
        # Note: Conversation storage removed - this is kept for backward compatibility
        pass
    
    async def end_conversation(self, call_id: str):
        """Explicitly end and clean up a conversation when call finishes (no-op - conversation storage removed)."""
        # Note: Conversation storage removed - this is kept for backward compatibility
        pass


# Global service instance
_nlp_service: Optional[NLPService] = None


def get_nlp_service() -> NLPService:
    """Get the global NLP service instance."""
    global _nlp_service
    if _nlp_service is None:
        _nlp_service = NLPService()
    return _nlp_service


# Backward compatibility alias
def get_azure_openai_service() -> NLPService:
    """Backward compatibility alias for get_nlp_service()."""
    return get_nlp_service()


# ---------- Simple Helper Methods for Common Checks ----------
def is_confirmation(text: str) -> bool:
    """Check if text is a confirmation (yes, correct, etc.)."""
    if not text:
        return False
    text_lower = text.lower().strip()
    confirmation_words = ["yes", "yeah", "yep", "yup", "correct", "right", "that's right", "exactly", "sure", "ok", "okay", "si", "sí", "correcto"]
    return any(word in text_lower for word in confirmation_words)


def is_negation(text: str) -> bool:
    """Check if text is a negation (no, not, etc.)."""
    if not text:
        return False
    text_lower = text.lower().strip()
    negation_words = ["no", "nope", "not", "don't", "doesn't", "won't", "can't", "never", "nunca", "no"]
    return any(word in text_lower for word in negation_words)


def is_goodbye(text: str) -> bool:
    """Check if text is a goodbye."""
    if not text:
        return False
    text_lower = text.lower().strip()
    goodbye_words = ["bye", "goodbye", "see you", "later", "farewell", "adios", "hasta luego", "hasta la vista"]
    return any(word in text_lower for word in goodbye_words)
