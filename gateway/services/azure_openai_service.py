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
from datetime import datetime, timedelta
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


logger = get_logger("azure_openai_service")


class IntentType(Enum):
    """Types of user intents."""
    APPOINTMENT_BOOKING = "appointment_booking"
    APPOINTMENT_CANCELLATION = "appointment_cancellation"
    APPOINTMENT_RESCHEDULING = "appointment_rescheduling"
    APPOINTMENT_INQUIRY = "appointment_inquiry"
    PROVIDER_INQUIRY = "provider_inquiry"
    CLINIC_INQUIRY = "clinic_inquiry"
    BILLING_INQUIRY = "billing_inquiry"
    EMERGENCY = "emergency"
    GENERAL_INQUIRY = "general_inquiry"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    UNKNOWN = "unknown"


class EntityType(Enum):
    """Types of entities that can be extracted."""
    DATE = "date"
    TIME = "time"
    PHONE_NUMBER = "phone_number"
    EMAIL = "email"
    NAME = "name"
    APPOINTMENT_TYPE = "appointment_type"
    PROVIDER_NAME = "provider_name"
    CLINIC_NAME = "clinic_name"
    SYMPTOMS = "symptoms"
    MEDICATION = "medication"
    INSURANCE = "insurance"


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: IntentType
    confidence: float
    entities: List[Dict[str, Any]]
    raw_response: str
    processing_time_ms: int
    timestamp: datetime
    language: LanguageCode
    fallback_used: bool = False


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
        
        # Conversation storage
        self.conversations: Dict[str, List[ConversationMessage]] = {}
        
        # Performance tracking
        self.intent_stats: Dict[str, Dict[str, Any]] = {}
        self.response_stats: Dict[str, Dict[str, Any]] = {}
        
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
                base_url=f"{self.endpoint}/openai/deployments/{self.deployment_name}",
                api_version=self.api_version
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
                    timestamp=datetime.utcnow(),
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
                    
                    # Parse response
                    response_text = response.choices[0].message.content
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
                        timestamp=datetime.utcnow(),
                        language=language
                    )
                    
                    # Update statistics
                    self._update_intent_stats(call_id, result)
                    
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
            timestamp=datetime.utcnow(),
            language=language,
            fallback_used=True
        )
    
    @log_performance("openai_generate_response")
    async def generate_response(self, user_input: str, call_id: str,
                              language: LanguageCode = LanguageCode.ENGLISH,
                              intent: Optional[IntentType] = None,
                              entities: Optional[List[Dict[str, Any]]] = None) -> ResponseResult:
        """
        Generate a response to user input.
        
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
            
            # Get system prompt for language
            system_prompt = self.system_prompt_en if language == LanguageCode.ENGLISH else self.system_prompt_es
            
            # Build conversation context
            messages = [{"role": "system", "content": system_prompt}]
            
            if self.enable_context_awareness and call_id in self.conversations:
                # Add recent conversation history
                recent_messages = self.conversations[call_id][-self.context_window_size:]
                for msg in recent_messages:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            # Add current user input
            messages.append({"role": "user", "content": user_input})
            
            # Generate response
            response = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=self.response_timeout_seconds
            )
            
            response_text = response.choices[0].message.content
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
                timestamp=datetime.utcnow(),
                language=language
            )
            
            # Update statistics
            self._update_response_stats(call_id, result)
            
            # Store in conversation history
            await self._add_to_conversation(call_id, "assistant", response_text, language, intent, response_entities)
            
            self.logger.info(
                f"Response generated for call {call_id}",
                LogCategory.AZURE_OPENAI,
                extra_data={
                    "call_id": call_id,
                    "response_length": len(response_text),
                    "processing_time_ms": processing_time_ms,
                    "language": language.value,
                    "intent": intent.value if intent else None
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
            
            if self.enable_context_awareness and call_id in self.conversations:
                # Add recent conversation history
                recent_messages = self.conversations[call_id][-self.context_window_size:]
                for msg in recent_messages:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            # Add current user input
            messages.append({"role": "user", "content": user_input})
            
            # Generate streaming response
            stream = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,
                timeout=self.response_timeout_seconds
            )
            
            full_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
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
            timestamp=datetime.utcnow(),
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
            
            response_text = response.choices[0].message.content
            entities_data = json.loads(response_text)
            
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
                timestamp=datetime.utcnow(),
                language=language,
                intent=intent,
                entities=entity_objects
            )
            
            self.conversations[call_id].append(message)
            
            # Limit conversation history size
            if len(self.conversations[call_id]) > 100:
                self.conversations[call_id] = self.conversations[call_id][-50:]
                
        except Exception as e:
            self.logger.error(f"Failed to add message to conversation: {e}")
    
    def _update_intent_stats(self, call_id: str, result: IntentResult):
        """Update intent classification statistics."""
        if call_id not in self.intent_stats:
            self.intent_stats[call_id] = {
                "start_time": datetime.utcnow(),
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
    
    def _update_response_stats(self, call_id: str, result: ResponseResult):
        """Update response generation statistics."""
        if call_id not in self.response_stats:
            self.response_stats[call_id] = {
                "start_time": datetime.utcnow(),
                "total_responses": 0,
                "successful_responses": 0,
                "fallback_responses": 0,
                "total_processing_time": 0,
                "total_response_length": 0
            }
        
        stats = self.response_stats[call_id]
        stats["total_responses"] += 1
        stats["total_processing_time"] += result.processing_time_ms
        stats["total_response_length"] += len(result.response_text)
        
        if not result.fallback_used:
            stats["successful_responses"] += 1
        else:
            stats["fallback_responses"] += 1
    
    def get_conversation_history(self, call_id: str, limit: int = 10) -> List[ConversationMessage]:
        """
        Get conversation history for a call.
        
        Args:
            call_id: ID of the call
            limit: Maximum number of messages to return
            
        Returns:
            List of conversation messages
        """
        if call_id not in self.conversations:
            return []
        
        messages = self.conversations[call_id]
        return messages[-limit:] if limit > 0 else messages
    
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
        stats["duration_seconds"] = (datetime.utcnow() - stats["start_time"]).total_seconds()
        
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
        stats["duration_seconds"] = (datetime.utcnow() - stats["start_time"]).total_seconds()
        
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
    
    def get_active_conversations_count(self) -> int:
        """Get count of active conversations."""
        return len(self.conversations)
    
    async def cleanup_expired_conversations(self):
        """Clean up expired conversations."""
        try:
            current_time = datetime.utcnow()
            expired_calls = []
            
            for call_id, messages in self.conversations.items():
                if messages:
                    last_message_time = messages[-1].timestamp
                    if (current_time - last_message_time).total_seconds() > 3600:  # 1 hour
                        expired_calls.append(call_id)
            
            for call_id in expired_calls:
                del self.conversations[call_id]
                if call_id in self.intent_stats:
                    del self.intent_stats[call_id]
                if call_id in self.response_stats:
                    del self.response_stats[call_id]
                
                self.logger.info(f"Cleaned up expired OpenAI conversation: {call_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired OpenAI conversations: {e}")


# Global service instance
_azure_openai_service: Optional[AzureOpenAIService] = None


def get_azure_openai_service() -> AzureOpenAIService:
    """Get the global Azure OpenAI Service instance."""
    global _azure_openai_service
    if _azure_openai_service is None:
        _azure_openai_service = AzureOpenAIService()
    return _azure_openai_service
