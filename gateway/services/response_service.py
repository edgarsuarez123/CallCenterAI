"""
Response Service
Combined service for response templates, routing, and caching.

This module provides:
- Response templates for common intents (bilingual support)
- Intelligent routing between scripted and AI responses
- Response caching to optimize token usage

Key Features:
- Template-based variable substitution
- Automatic routing to scripted or AI responses
- Redis-backed persistent caching with tiered TTL strategies
- Bilingual support (English/Spanish)
- Graceful fallback when Redis unavailable
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError

from services.structured_logging import get_logger, LogCategory, logger
from models.enums import LanguageCode
from services.configuration import get_settings

# Import CallContext and IntentType locally to avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.call_orchestrator import CallContext
    from services.nlp_service import IntentType

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))


# ---------- Response Templates ----------
@dataclass
class ResponseTemplate:
    """Response template with metadata."""
    template: str
    ttl: int
    variables: List[str]
    description: str


class TemplateTier(Enum):
    """Template TTL tiers."""
    GREETING = 86400      # 24 hours
    QUESTION = 3600       # 1 hour
    SPECIFIC = 300        # 5 minutes


class ResponseTemplates:
    """
    Collection of response templates organized by intent and language.
    
    Provides template-based responses for common conversational patterns
    to reduce token usage and improve response consistency.
    """
    
    def __init__(self):
        self.templates = self._initialize_templates()
    
    def _initialize_templates(self):
        """Initialize all response templates."""
        # Import locally to avoid circular import
        from services.nlp_service import IntentType
        
        return {
            IntentType.GREETING: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="Hello! Thank you for calling {clinic_name}. How can I help you today?",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Initial greeting when call is answered"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="¡Hola! Gracias por llamar a {clinic_name}. ¿Cómo puedo ayudarte hoy?",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Saludo inicial cuando se contesta la llamada"
                )
            },
            
            IntentType.APPOINTMENT_BOOKING: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I'd be happy to help you book an appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment booking question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Estaré encantado de ayudarte a reservar una cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para reservar cita"
                )
            },
            
            IntentType.APPOINTMENT_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you with information about your appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment inquiry question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte con información sobre tu cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para consulta de cita"
                )
            },
            
            IntentType.APPOINTMENT_CANCELLATION: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you cancel your appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment cancellation question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte a cancelar tu cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para cancelar cita"
                )
            },
            
            IntentType.APPOINTMENT_RESCHEDULING: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you reschedule your appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment rescheduling question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte a reprogramar tu cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para reprogramar cita"
                )
            },
            
            IntentType.PROVIDER_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you find information about our providers. Which doctor would you like to see?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Provider selection question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte a encontrar información sobre nuestros proveedores. ¿Qué doctor te gustaría ver?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta de selección de proveedor"
                )
            },
            
            IntentType.CLINIC_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you with information about our clinic. What would you like to know?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="General clinic information question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte con información sobre nuestra clínica. ¿Qué te gustaría saber?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta general sobre información de la clínica"
                )
            },
            
            IntentType.BILLING_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you with billing questions. What's your name or account number?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Billing inquiry question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte con preguntas de facturación. ¿Cuál es tu nombre o número de cuenta?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta de consulta de facturación"
                )
            },
            
            IntentType.EMERGENCY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I understand this is an emergency. Please call 911 immediately for life-threatening situations. For urgent medical needs, I can help you find the nearest emergency room.",
                    ttl=TemplateTier.SPECIFIC.value,
                    variables=[],
                    description="Emergency response"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Entiendo que esto es una emergencia. Por favor llama al 911 inmediatamente para situaciones que amenacen la vida. Para necesidades médicas urgentes, puedo ayudarte a encontrar la sala de emergencias más cercana.",
                    ttl=TemplateTier.SPECIFIC.value,
                    variables=[],
                    description="Respuesta de emergencia"
                )
            },
            
            IntentType.GENERAL_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I'm here to help with any questions you might have. What can I assist you with today?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="General inquiry response"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Estoy aquí para ayudar con cualquier pregunta que puedas tener. ¿Con qué puedo ayudarte hoy?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Respuesta de consulta general"
                )
            },
            
            IntentType.GOODBYE: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="Thank you for calling {clinic_name}! Have a great day!",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Goodbye message"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="¡Gracias por llamar a {clinic_name}! ¡Que tengas un gran día!",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Mensaje de despedida"
                )
            }
        }
    
    def get_template(
        self, 
        intent: "IntentType", 
        language: LanguageCode
    ) -> Optional[ResponseTemplate]:
        """Get template for given intent and language."""
        return self.templates.get(intent, {}).get(language)
    
    def has_template(self, intent: "IntentType", language: LanguageCode) -> bool:
        """Check if template exists for given intent and language."""
        return intent in self.templates and language in self.templates[intent]
    
    def get_required_variables(self, intent: "IntentType", language: LanguageCode) -> List[str]:
        """Get list of required variables for template."""
        template = self.get_template(intent, language)
        return template.variables if template else []
    
    async def substitute_variables(
        self, 
        intent: "IntentType", 
        language: LanguageCode, 
        variables: Dict[str, Any],
        clinic_id: Optional[str] = None,
        db: Optional[Any] = None
    ) -> Optional[str]:
        """
        Substitute variables in template and return final response.
        
        Args:
            intent: Intent type
            language: Language code
            variables: Variables to substitute
            clinic_id: Optional clinic ID to auto-load clinic variables
            db: Optional database session for loading clinic variables
            
        Returns:
            Formatted template string or None if template not found
        """
        template = self.get_template(intent, language)
        if not template:
            return None
        
        try:
            # Auto-load clinic variables if clinic_id provided
            if clinic_id and db:
                from services.clinic_template_variables import get_clinic_template_variables
                clinic_vars = await get_clinic_template_variables(clinic_id, db)
                # Merge clinic vars with provided vars (provided vars take precedence)
                merged_vars = {**clinic_vars, **variables}
            else:
                merged_vars = variables
            
            # Validate required variables
            missing_vars = set(template.variables) - set(merged_vars.keys())
            if missing_vars:
                raise ValueError(f"Missing required variables: {missing_vars}")
            
            # Substitute variables
            return template.template.format(**merged_vars)
            
        except KeyError as e:
            raise ValueError(f"Missing variable in template: {e}")
        except Exception as e:
            raise ValueError(f"Error substituting template variables: {e}")
    
    def get_all_intents(self):
        """Get list of all intents that have templates."""
        # Import locally to avoid circular import
        from services.nlp_service import IntentType
        return list(self.templates.keys())
    
    def get_supported_languages(self, intent: "IntentType") -> List[LanguageCode]:
        """Get list of supported languages for given intent."""
        return list(self.templates.get(intent, {}).keys())
    
    def get_template_statistics(self) -> Dict[str, Any]:
        """Get statistics about available templates."""
        total_templates = 0
        intents_with_templates = 0
        language_coverage = {}
        
        for intent, languages in self.templates.items():
            intents_with_templates += 1
            total_templates += len(languages)
            
            for language in languages:
                if language not in language_coverage:
                    language_coverage[language] = 0
                language_coverage[language] += 1
        
        return {
            "total_templates": total_templates,
            "intents_with_templates": intents_with_templates,
            "language_coverage": language_coverage,
            "average_templates_per_intent": total_templates / max(intents_with_templates, 1)
        }
    
    def validate_template_variables(
        self, 
        intent: "IntentType", 
        language: LanguageCode, 
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate variables against template requirements."""
        template = self.get_template(intent, language)
        if not template:
            return {
                "valid": False,
                "error": f"No template found for {intent.value}:{language.value}"
            }
        
        required_vars = set(template.variables)
        provided_vars = set(variables.keys())
        
        missing_vars = required_vars - provided_vars
        extra_vars = provided_vars - required_vars
        
        return {
            "valid": len(missing_vars) == 0,
            "missing_variables": list(missing_vars),
            "extra_variables": list(extra_vars),
            "required_variables": template.variables,
            "provided_variables": list(variables.keys())
        }


# ---------- Response Router ----------
@dataclass
class RouterResponseResult:
    """Result of response routing decision."""
    text: str
    is_scripted: bool
    template_key: Optional[str] = None
    tokens_used: int = 0


class ResponseRouter:
    """Automatically routes to scripted or AI responses based on intent type."""
    
    # Keywords that require dynamic data lookup
    DYNAMIC_DATA_KEYWORDS = [
        "available", "slots", "appointment times", "next available",
        "provider schedule", "doctor available", "when can i see",
        "availability", "free time", "open slots"
    ]
    
    def __init__(self):
        """Initialize the response router."""
        self.logger = get_logger("response_router")
    
    async def get_response(
        self,
        user_input: str,
        intent: "IntentType",
        call_context: Optional["CallContext"] = None,
        clinic_config: Optional[Dict[str, Any]] = None,
        entities: Optional[List[Dict[str, Any]]] = None,
        language: Optional[LanguageCode] = None,
        clinic_id: Optional[str] = None,
        call_id: Optional[str] = None
    ) -> RouterResponseResult:
        """
        Automatically determine response type and generate response.
        
        Uses intent-based template checking (more accurate than keyword matching).
        Priority: Template -> Cache -> Dynamic Data -> AI Generation
        """
        # Validate inputs
        if not user_input or not user_input.strip():
            self.logger.warning("Empty user_input in get_response", LogCategory.NLP)
            return RouterResponseResult(
                text="I'm sorry, I didn't catch that. Could you please repeat?",
                is_scripted=True,
                tokens_used=0
            )
        
        if not intent:
            self.logger.warning("No intent provided in get_response", LogCategory.NLP)
            # Fallback to AI generation
            response_text = await self._generate_ai_response(user_input, call_context)
            return RouterResponseResult(
                text=response_text,
                is_scripted=False,
                tokens_used=200
            )
        
        try:
            # Get response templates instance
            response_templates = get_response_templates()
            # Use language from call_context if available, otherwise use provided language, default to English
            if call_context and call_context.language:
                language = call_context.language
            elif language:
                language = language
            else:
                language = LanguageCode.ENGLISH
            
            # Get clinic_id from call_context if available, otherwise use provided clinic_id
            if call_context and hasattr(call_context, 'clinic_id'):
                clinic_id = call_context.clinic_id
            elif not clinic_id:
                clinic_id = None
            
            # Priority 1: Check if template exists for this intent (intent-based, not keyword-based)
            if response_templates.has_template(intent, language):
                # Extract variables from entities or clinic_config
                variables = {}
                if entities:
                    # Extract variables from entities
                    for entity in entities:
                        if isinstance(entity, dict):
                            entity_type = entity.get('type', '')
                            entity_value = entity.get('value', '')
                            if entity_type and entity_value:
                                variables[entity_type.lower()] = entity_value
                
                # Merge with clinic_config if provided
                if clinic_config:
                    variables.update(clinic_config)
                
                # Try to get template response
                template_response = await response_templates.substitute_variables(
                    intent, language, variables,
                    clinic_id=clinic_id
                )
                
                if template_response:
                    self.logger.info(
                        f"Using template response for intent: {intent.value}",
                        LogCategory.NLP,
                        extra_data={
                            "intent": intent.value,
                            "language": language.value,
                            "tokens_used": 0
                        }
                    )
                    return RouterResponseResult(
                        text=template_response,
                        is_scripted=True,
                        template_key=intent.value,
                        tokens_used=0
                    )
            
            # Priority 2: Check if requires dynamic data (Google Calendar, etc.)
            # Note: Dynamic data requires full CallContext
            if call_context and self._requires_dynamic_data(user_input):
                response_text = await self._generate_dynamic_response(
                    user_input, call_context, clinic_config or {}
                )
                self.logger.info(
                    "Using dynamic data response",
                    LogCategory.NLP,
                    extra_data={"tokens_used": "~50"}
                )
                return RouterResponseResult(
                    text=response_text,
                    is_scripted=False,
                    tokens_used=50  # Estimated for calendar queries
                )
            
            # Priority 3: Default to AI for complex questions
            # Note: AI generation requires full CallContext
            if call_context:
                response_text = await self._generate_ai_response(user_input, call_context)
                self.logger.info(
                    "Using AI-generated response",
                    LogCategory.NLP,
                    extra_data={"tokens_used": "~200"}
                )
                return RouterResponseResult(
                    text=response_text,
                    is_scripted=False,
                    tokens_used=200  # Estimated for complex AI responses
                )
            else:
                # Fallback if no CallContext provided
                self.logger.warning("No CallContext provided, cannot generate AI response", LogCategory.NLP)
                return RouterResponseResult(
                    text="I'm sorry, I'm having trouble processing that request. Could you please try again?",
                    is_scripted=False,
                    tokens_used=0
                )
            
        except Exception as e:
            self.logger.error(f"Error in response routing: {e}", LogCategory.NLP, exception=e)
            # Fallback to generic scripted response
            return RouterResponseResult(
                text="I'm sorry, I didn't understand that. Could you please repeat?",
                is_scripted=True,
                template_key="greeting",
                tokens_used=0
            )
    
    def _requires_dynamic_data(self, user_input: str) -> bool:
        """Check if question requires dynamic data lookup."""
        user_lower = user_input.lower()
        return any(keyword in user_lower for keyword in self.DYNAMIC_DATA_KEYWORDS)
    
    async def _generate_dynamic_response(
        self, user_input: str, context: "CallContext", config: Dict[str, Any]
    ) -> str:
        """Generate response with dynamic data (calendar, etc.)."""
        try:
            from services.google_calendar_service import get_google_calendar_service
            calendar_service = get_google_calendar_service()
            
            start_date = datetime.now()
            end_date = start_date + timedelta(days=7)
            
            provider_id = context.metadata.get('provider_id') if context.metadata else None
            if not provider_id:
                self.logger.warning("provider_id not found in context metadata", LogCategory.NLP)
                return "I can help you check availability. Please provide a provider name."
            
            try:
                from services.database import get_async_db_session
                from sqlalchemy import select
                async with get_async_db_session() as db:
                    from models.models import Provider
                    provider_result = await db.execute(select(Provider).where(Provider.provider_id == provider_id))
                    provider = provider_result.scalar_one_or_none()
                    if not provider:
                        self.logger.warning(f"Provider {provider_id} not found in database", LogCategory.NLP)
                        return "I can help you check availability. Please provide a valid provider name."
            except Exception as db_error:
                self.logger.error(f"Failed to validate provider: {db_error}")
            
            if not start_date or not end_date:
                self.logger.warning("Invalid dates for availability check", LogCategory.NLP)
                return "I can help you check availability. Please provide a date range."
            
            if end_date < start_date:
                self.logger.warning("end_date is before start_date", LogCategory.NLP)
                return "I can help you check availability. Please provide a valid date range."
            
            try:
                await calendar_service.get_available_slots(
                    provider_id=provider_id,
                    start_date=start_date,
                    end_date=end_date
                )
            except Exception as calendar_error:
                if 'authentication' in str(calendar_error).lower() or 'auth' in str(calendar_error).lower():
                    self.logger.error(f"Calendar authentication error: {calendar_error}", LogCategory.NLP)
                    return "I'm sorry, I'm having trouble accessing the calendar. Please contact our staff for availability."
                elif 'network' in str(calendar_error).lower() or 'connection' in str(calendar_error).lower():
                    self.logger.error(f"Calendar network error: {calendar_error}", LogCategory.NLP)
                    return "I'm sorry, I'm having trouble connecting to the calendar. Please try again later."
                else:
                    self.logger.error(f"Calendar service error: {calendar_error}", LogCategory.NLP)
                    return "I'm sorry, I'm having trouble checking availability. Please contact our staff."
            
            from services.nlp_service import get_nlp_service
            nlp_service = get_nlp_service()
            
            entities = []
            if context.entities:
                entities = context.entities
            elif context.metadata and 'entities' in context.metadata:
                entities = context.metadata['entities']
            
            response_result = await nlp_service.generate_response(
                user_input=user_input,
                call_id=context.call_id,
                language=context.language,
                intent=context.current_intent,
                entities=entities if entities else None,
                clinic_id=context.clinic_id if hasattr(context, 'clinic_id') else None
            )
            
            if not response_result or not response_result.response_text:
                self.logger.warning("Empty response from OpenAI service", LogCategory.NLP)
                return "I can help you check availability. Please hold while I look that up."
            
            return response_result.response_text
            
        except Exception as e:
            self.logger.error(f"Error generating dynamic response: {e}")
            return "I can help you check availability. Please hold while I look that up."
    
    async def _generate_ai_response(
        self, user_input: str, context: "CallContext"
    ) -> str:
        """Generate AI response for complex questions."""
        try:
            from services.nlp_service import get_nlp_service
            nlp_service = get_nlp_service()
            
            entities = []
            if context.entities:
                entities = context.entities
            elif context.metadata and 'entities' in context.metadata:
                entities = context.metadata['entities']
            
            response_result = await nlp_service.generate_response(
                user_input=user_input,
                call_id=context.call_id,
                language=context.language,
                intent=context.current_intent,
                entities=entities if entities else None,
                clinic_id=context.clinic_id if hasattr(context, 'clinic_id') else None
            )
            
            if not response_result or not response_result.response_text:
                self.logger.warning("Empty response from OpenAI service", LogCategory.NLP)
                return "I'm sorry, I'm having trouble processing that request. Could you please try again?"
            
            return response_result.response_text
        except Exception as e:
            self.logger.error(f"Error generating AI response: {e}")
            return "I'm sorry, I'm having trouble processing that request. Could you please try again?"


# ---------- Response Cache ----------
class CacheTier(Enum):
    """Cache TTL tiers for different response types."""
    GREETING = 86400      # 24 hours
    QUESTION = 3600       # 1 hour
    SPECIFIC = 300        # 5 minutes
    AI_GENERATED = 300    # 5 minutes


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    response: str
    template: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    created_at: datetime = None
    ttl: int = 300
    source: str = "template"  # "template" or "ai_generated"
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(AST)


@dataclass
class CacheStatistics:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    errors: int = 0
    total_requests: int = 0
    cache_size: int = 0
    last_reset: datetime = None
    
    def __post_init__(self):
        if self.last_reset is None:
            self.last_reset = datetime.now(AST)
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests
    
    @property
    def miss_rate(self) -> float:
        """Calculate cache miss rate."""
        return 1.0 - self.hit_rate


class ResponseCacheService:
    """
    Service for caching AI responses with Redis backend.
    
    Provides intelligent caching of both template-based responses and
    AI-generated responses to optimize token usage and improve performance.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        self.redis_client: Optional[redis.Redis] = None
        self._connection_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._stats = CacheStatistics()
        self._local_cache: Dict[str, CacheEntry] = {}
        self._is_connected = False
        
        # Cache configuration
        self.redis_config = self.settings.redis_cache
        self.key_prefix = self.redis_config.key_prefix
        self.default_ttl = self.redis_config.default_ttl
        
        # TTL mapping for different response types
        self.cache_ttl_mapping = {
            "greeting": CacheTier.GREETING.value,
            "goodbye": CacheTier.GREETING.value,
            "name_request": CacheTier.QUESTION.value,
            "provider_selection": CacheTier.QUESTION.value,
            "date_selection": CacheTier.QUESTION.value,
            "time_selection": CacheTier.QUESTION.value,
            "confirmation": CacheTier.QUESTION.value,
            "ai_generated": CacheTier.AI_GENERATED.value,
            "specific": CacheTier.SPECIFIC.value
        }
        
        self.logger.info(
            "Response cache service initialized",
            LogCategory.CACHE,
            extra_data={
                "redis_host": self.redis_config.host,
                "redis_port": self.redis_config.port,
                "key_prefix": self.key_prefix,
                "default_ttl": self.default_ttl
            }
        )
    
    async def initialize(self) -> bool:
        """Initialize Redis connection."""
        try:
            async with self._connection_lock:
                if self.redis_client is None:
                    connection_kwargs = {
                        "host": self.redis_config.host,
                        "port": self.redis_config.port,
                        "db": self.redis_config.db,
                        "max_connections": self.redis_config.max_connections,
                        "socket_timeout": self.redis_config.socket_timeout,
                        "socket_connect_timeout": self.redis_config.socket_connect_timeout,
                        "retry_on_timeout": self.redis_config.retry_on_timeout,
                        "health_check_interval": self.redis_config.health_check_interval,
                        "decode_responses": True
                    }
                    
                    if self.redis_config.password:
                        connection_kwargs["password"] = self.redis_config.password.get_secret_value()
                    
                    self.redis_client = redis.Redis(**connection_kwargs)
                    await self.redis_client.ping()
                    self._is_connected = True
                    
                    self.logger.info(
                        "Redis connection established",
                        LogCategory.CACHE,
                        extra_data={
                            "host": self.redis_config.host,
                            "port": self.redis_config.port,
                            "db": self.redis_config.db
                        }
                    )
                    
                    return True
                    
        except (RedisError, ConnectionError, TimeoutError) as e:
            self.logger.warning(
                f"Redis connection failed, using local cache fallback: {e}",
                LogCategory.CACHE,
                extra_data={"error": str(e)}
            )
            self._is_connected = False
            return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error initializing Redis: {e}",
                LogCategory.CACHE,
                extra_data={"error": str(e)}
            )
            self._is_connected = False
            return False
    
    async def get_cached_response(
        self, 
        intent: str, 
        language: str, 
        variables: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Get cached response for given intent and language."""
        try:
            async with self._stats_lock:
                self._stats.total_requests += 1
            
            cache_key = self._generate_cache_key(intent, language, variables)
            
            if not self._is_connected:
                await self.initialize()
            
            if self._is_connected and self.redis_client:
                try:
                    cached_data = await self.redis_client.get(cache_key)
                    if cached_data:
                        try:
                            entry_data = json.loads(cached_data)
                            entry = CacheEntry(**entry_data)
                        except (json.JSONDecodeError, TypeError, KeyError) as e:
                            self.logger.warning(f"Failed to parse cached data: {e}", LogCategory.CACHE)
                            cached_data = None
                        
                        if cached_data and entry:
                            if self._is_entry_valid(entry):
                                async with self._stats_lock:
                                    self._stats.hits += 1
                                self.logger.debug(
                                    f"Cache hit for {intent}:{language}",
                                    LogCategory.CACHE,
                                    extra_data={"cache_key": cache_key}
                                )
                                return entry.response
                            else:
                                await self.redis_client.delete(cache_key)
                        else:
                            await self.redis_client.delete(cache_key)
                            
                except (RedisError, ConnectionError, TimeoutError) as e:
                    self.logger.warning(
                        f"Redis error during get, falling back to local cache: {e}",
                        LogCategory.CACHE
                    )
                    self._is_connected = False
            
            # Fallback to local cache
            async with self._cache_lock:
                if cache_key in self._local_cache:
                    entry = self._local_cache[cache_key]
                    if entry and self._is_entry_valid(entry):
                        async with self._stats_lock:
                            self._stats.hits += 1
                        self.logger.debug(
                            f"Local cache hit for {intent}:{language}",
                            LogCategory.CACHE
                        )
                        return entry.response
                    else:
                        del self._local_cache[cache_key]
            
            async with self._stats_lock:
                self._stats.misses += 1
            return None
            
        except Exception as e:
            async with self._stats_lock:
                self._stats.errors += 1
            self.logger.error(
                f"Error getting cached response: {e}",
                LogCategory.CACHE,
                extra_data={"intent": intent, "language": language, "error": str(e)}
            )
            return None
    
    async def cache_response(
        self,
        intent: str,
        language: str,
        response: str,
        template: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
        source: str = "template"
    ) -> bool:
        """Cache a response for given intent and language."""
        try:
            if ttl is None:
                ttl = self.cache_ttl_mapping.get(intent, self.default_ttl)
            
            entry = CacheEntry(
                response=response,
                template=template,
                variables=variables,
                ttl=ttl,
                source=source
            )
            
            cache_key = self._generate_cache_key(intent, language, variables)
            
            if self._is_connected and self.redis_client:
                try:
                    entry_data = json.dumps(asdict(entry), default=str)
                    await self.redis_client.setex(cache_key, ttl, entry_data)
                    
                    self.logger.debug(
                        f"Cached response in Redis for {intent}:{language}",
                        LogCategory.CACHE,
                        extra_data={
                            "cache_key": cache_key,
                            "ttl": ttl,
                            "source": source
                        }
                    )
                    return True
                    
                except (RedisError, ConnectionError, TimeoutError) as e:
                    self.logger.warning(
                        f"Redis error during cache, using local cache: {e}",
                        LogCategory.CACHE
                    )
                    self._is_connected = False
            
            # Fallback to local cache
            async with self._cache_lock:
                self._local_cache[cache_key] = entry
            
            async with self._cache_lock:
                if cache_key not in self._local_cache:
                    self.logger.error(f"Failed to write to local cache for {intent}:{language}")
                    return False
            
            await self._cleanup_local_cache()
            
            self.logger.debug(
                f"Cached response locally for {intent}:{language}",
                LogCategory.CACHE,
                extra_data={"ttl": ttl, "source": source}
            )
            return True
            
        except Exception as e:
            async with self._stats_lock:
                self._stats.errors += 1
            self.logger.error(
                f"Error caching response: {e}",
                LogCategory.CACHE,
                extra_data={"intent": intent, "language": language, "error": str(e)}
            )
            return False
    
    def _generate_cache_key(
        self, 
        intent: str, 
        language: str, 
        variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate cache key for intent, language, and variables."""
        base_key = f"{intent}:{language}"
        
        if variables:
            sorted_vars = sorted(variables.items())
            var_hash = hashlib.sha256(json.dumps(sorted_vars, sort_keys=True).encode()).hexdigest()[:16]
            base_key = f"{base_key}:{var_hash}"
        
        return f"{self.key_prefix}response:{base_key}"
    
    def _is_entry_valid(self, entry: CacheEntry) -> bool:
        """Check if cache entry is still valid."""
        if entry.created_at is None:
            return False
        
        elapsed = (datetime.now(AST) - entry.created_at).total_seconds()
        return elapsed < entry.ttl
    
    async def _cleanup_local_cache(self):
        """Clean up expired entries from local cache."""
        if hasattr(self, '_cleanup_in_progress') and self._cleanup_in_progress:
            return
        
        try:
            self._cleanup_in_progress = True
            
            current_time = datetime.now(AST)
            expired_keys = []
            
            async with self._cache_lock:
                for key, entry in list(self._local_cache.items()):
                    if entry and not self._is_entry_valid(entry):
                        expired_keys.append(key)
            
            if expired_keys:
                async with self._cache_lock:
                    for key in expired_keys:
                        if key in self._local_cache:
                            entry = self._local_cache[key]
                            if entry and not self._is_entry_valid(entry):
                                del self._local_cache[key]
                                async with self._stats_lock:
                                    self._stats.evictions += 1
            
            if expired_keys:
                self.logger.debug(
                    f"Cleaned up {len(expired_keys)} expired local cache entries",
                    LogCategory.CACHE
                )
        except Exception as e:
            self.logger.error(
                f"Error cleaning up local cache: {e}",
                LogCategory.CACHE
            )
        finally:
            self._cleanup_in_progress = False
    
    async def get_cache_statistics(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        try:
            redis_info = {}
            if self._is_connected and self.redis_client:
                try:
                    info = await self.redis_client.info("memory")
                    if info:
                        redis_info = {
                            "redis_used_memory": info.get("used_memory_human", "unknown"),
                            "redis_connected_clients": info.get("connected_clients", 0),
                            "redis_evicted_keys": info.get("evicted_keys", 0)
                        }
                except Exception as e:
                    self.logger.warning(f"Could not get Redis info: {e}")
            
            async with self._cache_lock:
                cache_size = len(self._local_cache)
            
            if self._is_connected and self.redis_client:
                try:
                    pattern = f"{self.key_prefix}response:*"
                    keys = await self.redis_client.keys(pattern)
                    if keys:
                        cache_size = len(keys)
                except Exception:
                    pass
            
            async with self._stats_lock:
                self._stats.cache_size = cache_size
            
            return {
                "statistics": asdict(self._stats),
                "connection_status": {
                    "redis_connected": self._is_connected,
                    "local_cache_size": cache_size
                },
                "redis_info": redis_info,
                "ttl_mapping": self.cache_ttl_mapping
            }
            
        except Exception as e:
            self.logger.error(
                f"Error getting cache statistics: {e}",
                LogCategory.CACHE
            )
            return {"error": str(e)}
    
    async def clear_cache(self, pattern: Optional[str] = None) -> bool:
        """Clear cache entries."""
        try:
            if pattern is None:
                pattern = f"{self.key_prefix}response:*"
            
            cleared_count = 0
            
            if self._is_connected and self.redis_client:
                try:
                    keys = await self.redis_client.keys(pattern)
                    if keys and len(keys) > 0:
                        cleared_count += await self.redis_client.delete(*keys)
                except Exception as e:
                    self.logger.warning(f"Error clearing Redis cache: {e}")
            
            async with self._cache_lock:
                if pattern == f"{self.key_prefix}response:*" or pattern is None:
                    cleared_count += len(self._local_cache)
                    self._local_cache.clear()
                else:
                    keys_to_remove = [k for k in self._local_cache.keys() if pattern.replace("*", "") in k]
                    for key in keys_to_remove:
                        if key in self._local_cache:
                            del self._local_cache[key]
                    cleared_count += len(keys_to_remove)
            
            self.logger.info(
                f"Cleared {cleared_count} cache entries",
                LogCategory.CACHE,
                extra_data={"pattern": pattern, "cleared_count": cleared_count}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Error clearing cache: {e}",
                LogCategory.CACHE
            )
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on cache service."""
        try:
            health_status = {
                "status": "healthy",
                "redis_connected": False,
                "local_cache_available": True,
                "timestamp": datetime.now(AST).isoformat()
            }
            
            if self.redis_client:
                try:
                    await self.redis_client.ping()
                    health_status["redis_connected"] = True
                except Exception as e:
                    health_status["redis_connected"] = False
                    health_status["redis_error"] = str(e)
            
            try:
                async with self._cache_lock:
                    test_key = f"{self.key_prefix}health_check"
                    test_entry = CacheEntry(response="test", ttl=1)
                    self._local_cache[test_key] = test_entry
                    if test_key in self._local_cache:
                        del self._local_cache[test_key]
            except Exception as e:
                health_status["local_cache_available"] = False
                health_status["local_cache_error"] = str(e)
                health_status["status"] = "unhealthy"
            
            if not health_status["redis_connected"] and not health_status["local_cache_available"]:
                health_status["status"] = "unhealthy"
            
            return health_status
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(AST).isoformat()
            }
    
    async def close(self):
        """Close Redis connection."""
        try:
            if self.redis_client:
                await self.redis_client.close()
                self._is_connected = False
                self.logger.info("Redis connection closed", LogCategory.CACHE)
        except Exception as e:
            self.logger.error(f"Error closing Redis connection: {e}", LogCategory.CACHE)


# ---------- Global Instances and Factory Functions ----------
_response_templates: Optional[ResponseTemplates] = None
_response_router: Optional[ResponseRouter] = None
_response_cache_service: Optional[ResponseCacheService] = None


def get_response_templates() -> ResponseTemplates:
    """Get global response templates instance."""
    global _response_templates
    if _response_templates is None:
        _response_templates = ResponseTemplates()
    return _response_templates


def get_response_router() -> ResponseRouter:
    """Get global response router instance."""
    global _response_router
    if _response_router is None:
        _response_router = ResponseRouter()
    return _response_router


def get_response_cache_service() -> ResponseCacheService:
    """Get global response cache service instance."""
    global _response_cache_service
    if _response_cache_service is None:
        _response_cache_service = ResponseCacheService()
    return _response_cache_service

