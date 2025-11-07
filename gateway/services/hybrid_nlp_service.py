"""
Hybrid NLP service that combines existing NaturalLanguageProcessor with Azure OpenAI.

This service provides:
- Fallback between Azure OpenAI and local NLP processing
- Confidence-based routing between services
- Performance optimization through caching
- Bilingual support with language detection
- Entity extraction from both services
- Intent classification with hybrid approach
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum

from services.natural_language_processor import (
    NaturalLanguageProcessor, 
    IntentResult as LocalIntentResult,
    IntentType as LocalIntentType,
    ExtractedEntities
)
from services.azure_openai_service import (
    AzureOpenAIService,
    IntentResult as AzureIntentResult,
    IntentType as AzureIntentType,
    Entity as AzureEntity,
    EntityType
)
from services.bilingual_manager import get_bilingual_manager, LanguageCode
from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ValidationError,
    ExternalServiceUnavailableError,
    ServiceUnavailableError
)


logger = get_logger("hybrid_nlp_service")


class ProcessingStrategy(Enum):
    """Strategy for processing user input."""
    AZURE_FIRST = "azure_first"      # Try Azure OpenAI first, fallback to local
    LOCAL_FIRST = "local_first"      # Try local NLP first, fallback to Azure
    HYBRID = "hybrid"                # Use both and combine results
    AZURE_ONLY = "azure_only"        # Use only Azure OpenAI
    LOCAL_ONLY = "local_only"        # Use only local NLP


@dataclass
class HybridIntentResult:
    """Result from hybrid NLP processing."""
    intent: Union[LocalIntentType, AzureIntentType]
    confidence: float
    entities: List[Dict[str, Any]]
    processing_strategy: ProcessingStrategy
    azure_result: Optional[AzureIntentResult] = None
    local_result: Optional[LocalIntentResult] = None
    processing_time_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    language: LanguageCode = LanguageCode.ENGLISH
    fallback_used: bool = False


@dataclass
class ProcessingStats:
    """Statistics for hybrid processing."""
    total_requests: int = 0
    azure_requests: int = 0
    local_requests: int = 0
    hybrid_requests: int = 0
    fallback_requests: int = 0
    azure_success_rate: float = 0.0
    local_success_rate: float = 0.0
    average_processing_time: float = 0.0
    total_processing_time: float = 0.0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HybridNLPService:
    """
    Hybrid NLP service that combines local and Azure OpenAI processing.
    
    Provides intelligent routing between services based on:
    - Service availability
    - Performance requirements
    - Confidence thresholds
    - Language support
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        self.bilingual_manager = get_bilingual_manager()
        
        # Initialize services
        self.local_nlp = NaturalLanguageProcessor()
        self.azure_openai = AzureOpenAIService()
        
        # Processing configuration
        self.default_strategy = ProcessingStrategy.AZURE_FIRST
        self.confidence_threshold = 0.7
        self.azure_timeout_seconds = 10
        self.local_timeout_seconds = 2
        
        # Performance tracking
        self.processing_stats = ProcessingStats()
        self.call_stats: Dict[str, ProcessingStats] = {}
        
        # Caching for performance
        self.intent_cache: Dict[str, HybridIntentResult] = {}
        
        # Thread safety
        self._cache_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
        
        # Tiered TTL strategy for different intent types
        self.cache_ttl_mapping = {
            "greeting": 86400,      # 24 hours
            "goodbye": 86400,       # 24 hours
            "appointment_booking": 3600,    # 1 hour
            "appointment_inquiry": 3600,    # 1 hour
            "provider_inquiry": 3600,       # 1 hour
            "clinic_inquiry": 3600,         # 1 hour
            "billing_inquiry": 3600,        # 1 hour
            "general_inquiry": 3600,        # 1 hour
            "specific": 300,                # 5 minutes
            "default": 300                  # 5 minutes
        }
        self.default_ttl = 300  # 5 minutes
        
        # Service health tracking
        self.azure_health = True
        self.local_health = True
        self.last_health_check = datetime.now(timezone.utc)
        self.health_check_interval = 60  # seconds
        
        self.logger.info(
            "Hybrid NLP service initialized",
            LogCategory.NLP,
            extra_data={
                "default_strategy": self.default_strategy.value,
                "confidence_threshold": self.confidence_threshold,
                "cache_ttl_mapping": self.cache_ttl_mapping,
                "default_ttl": self.default_ttl
            }
        )
    
    def _get_ttl_for_intent(self, intent: str) -> int:
        """
        Get TTL for given intent type.
        
        Args:
            intent: Intent type string
            
        Returns:
            int: TTL in seconds
        """
        return self.cache_ttl_mapping.get(intent, self.default_ttl)
    
    @log_performance("hybrid_process_input")
    async def process_input(self, user_input: str, call_id: str,
                          language: LanguageCode = LanguageCode.ENGLISH,
                          strategy: Optional[ProcessingStrategy] = None,
                          context: Optional[Dict[str, Any]] = None) -> HybridIntentResult:
        """
        Process user input using hybrid NLP approach.
        
        Args:
            user_input: Text input from user
            call_id: ID of the call
            language: Language of the input
            strategy: Processing strategy to use
            context: Additional context for processing
            
        Returns:
            Hybrid intent result
        """
        try:
            # Validate inputs
            if not user_input or not user_input.strip():
                raise ValidationError("user_input", user_input, "User input cannot be empty")
            
            if not call_id:
                raise ValidationError("call_id", call_id, "Call ID cannot be empty")
            
            # Check cache first (with lock)
            cache_key = f"{call_id}:{hash(user_input)}:{language.value}"
            async with self._cache_lock:
                if cache_key in self.intent_cache:
                    cached_result = self.intent_cache[cache_key]
                    if cached_result:
                        # Use tiered TTL based on intent
                        intent_ttl = self._get_ttl_for_intent(cached_result.intent.value if cached_result.intent else "default")
                        if (datetime.now(timezone.utc) - cached_result.timestamp).total_seconds() < intent_ttl:
                            self.logger.debug(f"Using cached intent result for call {call_id}")
                            return cached_result
                        else:
                            # Remove expired cache entry
                            del self.intent_cache[cache_key]
            
            # Determine processing strategy
            if strategy is None:
                strategy = await self._determine_strategy(call_id, language)
            
            # Check service health
            await self._check_service_health()
            
            # Issue 40: Handle service unavailability with fallback
            azure_available = await self._check_azure_availability()
            local_available = await self._check_local_availability()
            
            if not azure_available and not local_available:
                # Issue 40: Both services unavailable - return default intent
                self.logger.warning(f"Both Azure and local NLP services unavailable for call {call_id}, using fallback")
                return self._create_fallback_result(user_input, call_id, language)
            
            start_time = time.time()
            
            # Process based on strategy
            if strategy == ProcessingStrategy.AZURE_FIRST:
                result = await self._process_azure_first(user_input, call_id, language, context)
            elif strategy == ProcessingStrategy.LOCAL_FIRST:
                result = await self._process_local_first(user_input, call_id, language, context)
            elif strategy == ProcessingStrategy.HYBRID:
                result = await self._process_hybrid(user_input, call_id, language, context)
            elif strategy == ProcessingStrategy.AZURE_ONLY:
                result = await self._process_azure_only(user_input, call_id, language, context)
            elif strategy == ProcessingStrategy.LOCAL_ONLY:
                result = await self._process_local_only(user_input, call_id, language, context)
            else:
                raise ValidationError("strategy", strategy, f"Unknown processing strategy: {strategy}")
            
            # Update processing time
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            result.language = language
            
            # Update statistics
            await self._update_processing_stats(call_id, result)
            
            # Cache result (with lock)
            async with self._cache_lock:
                self.intent_cache[cache_key] = result
            
            # Clean up old cache entries
            await self._cleanup_cache()
            
            self.logger.info(
                f"Hybrid NLP processing completed for call {call_id}",
                LogCategory.NLP,
                extra_data={
                    "call_id": call_id,
                    "strategy": strategy.value,
                    "intent": result.intent.value if hasattr(result.intent, 'value') else str(result.intent),
                    "confidence": result.confidence,
                    "processing_time_ms": result.processing_time_ms,
                    "fallback_used": result.fallback_used,
                    "language": language.value
                }
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"Failed to process input for call {call_id}: {e}",
                LogCategory.NLP,
                exception=e
            )
            raise
    
    async def _determine_strategy(self, call_id: str, language: LanguageCode) -> ProcessingStrategy:
        """
        Determine the best processing strategy based on context.
        
        Args:
            call_id: ID of the call
            language: Language of the input
            
        Returns:
            Processing strategy to use
        """
        try:
            # Check service health
            if not self.azure_health and not self.local_health:
                # Both services down, raise error instead of infinite loop
                raise ServiceUnavailableError("All NLP services are down")
            elif not self.azure_health:
                return ProcessingStrategy.LOCAL_ONLY
            elif not self.local_health:
                return ProcessingStrategy.AZURE_ONLY
            
            # Check language support
            if language == LanguageCode.SPANISH:
                # Azure OpenAI has better Spanish support
                return ProcessingStrategy.AZURE_FIRST
            
            # Check call history for performance
            if call_id in self.call_stats:
                stats = self.call_stats[call_id]
                if stats.azure_success_rate > 0.8 and stats.local_success_rate < 0.6:
                    return ProcessingStrategy.AZURE_FIRST
                elif stats.local_success_rate > 0.8 and stats.azure_success_rate < 0.6:
                    return ProcessingStrategy.LOCAL_FIRST
                elif stats.fallback_requests > stats.total_requests * 0.3:
                    # High fallback rate, use hybrid approach
                    return ProcessingStrategy.HYBRID
            
            # Default strategy
            return self.default_strategy
            
        except Exception as e:
            self.logger.error(f"Failed to determine strategy: {e}")
            return ProcessingStrategy.LOCAL_ONLY
    
    async def _process_azure_first(self, user_input: str, call_id: str,
                                 language: LanguageCode, context: Optional[Dict[str, Any]]) -> HybridIntentResult:
        """Process with Azure OpenAI first, fallback to local NLP."""
        try:
            # Try Azure OpenAI first
            if self.azure_health:
                try:
                    azure_result = await asyncio.wait_for(
                        self.azure_openai.classify_intent(user_input, call_id, language),
                        timeout=self.azure_timeout_seconds
                    )
                    
                    # Convert Azure result to hybrid result
                    result = HybridIntentResult(
                        intent=azure_result.intent,
                        confidence=azure_result.confidence,
                        entities=azure_result.entities,
                        processing_strategy=ProcessingStrategy.AZURE_FIRST,
                        azure_result=azure_result,
                        language=language
                    )
                    
                    if azure_result.confidence >= self.confidence_threshold:
                        return result
                    else:
                        # Low confidence, try local NLP as backup
                        self.logger.debug(f"Azure confidence {azure_result.confidence} below threshold, trying local NLP")
                        
                except asyncio.TimeoutError:
                    self.logger.warning(f"Azure OpenAI timeout for call {call_id}")
                except Exception as e:
                    self.logger.warning(f"Azure OpenAI failed for call {call_id}: {e}")
            
            # Fallback to local NLP
            local_result = await asyncio.wait_for(
                asyncio.to_thread(self.local_nlp.process_input, user_input, context),
                timeout=self.local_timeout_seconds
            )
            
            # Convert local result to hybrid result
            result = HybridIntentResult(
                intent=local_result.intent,
                confidence=local_result.confidence,
                entities=self._convert_local_entities(local_result.entities),
                processing_strategy=ProcessingStrategy.AZURE_FIRST,
                local_result=local_result,
                language=language,
                fallback_used=True
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Azure-first processing failed for call {call_id}: {e}")
            # Return fallback result
            return self._create_fallback_result(user_input, call_id, language)
    
    async def _process_local_first(self, user_input: str, call_id: str,
                                 language: LanguageCode, context: Optional[Dict[str, Any]]) -> HybridIntentResult:
        """Process with local NLP first, fallback to Azure OpenAI."""
        try:
            # Try local NLP first
            if self.local_health:
                try:
                    local_result = await asyncio.wait_for(
                        asyncio.to_thread(self.local_nlp.process_input, user_input, context),
                        timeout=self.local_timeout_seconds
                    )
                    
                    # Convert local result to hybrid result
                    result = HybridIntentResult(
                        intent=local_result.intent,
                        confidence=local_result.confidence,
                        entities=self._convert_local_entities(local_result.entities),
                        processing_strategy=ProcessingStrategy.LOCAL_FIRST,
                        local_result=local_result,
                        language=language
                    )
                    
                    if local_result.confidence >= self.confidence_threshold:
                        return result
                    else:
                        # Low confidence, try Azure OpenAI as backup
                        self.logger.debug(f"Local confidence {local_result.confidence} below threshold, trying Azure OpenAI")
                        
                except asyncio.TimeoutError:
                    self.logger.warning(f"Local NLP timeout for call {call_id}")
                except Exception as e:
                    self.logger.warning(f"Local NLP failed for call {call_id}: {e}")
            
            # Fallback to Azure OpenAI
            if self.azure_health:
                azure_result = await asyncio.wait_for(
                    self.azure_openai.classify_intent(user_input, call_id, language),
                    timeout=self.azure_timeout_seconds
                )
                
                # Convert Azure result to hybrid result
                result = HybridIntentResult(
                    intent=azure_result.intent,
                    confidence=azure_result.confidence,
                    entities=azure_result.entities,
                    processing_strategy=ProcessingStrategy.LOCAL_FIRST,
                    azure_result=azure_result,
                    language=language,
                    fallback_used=True
                )
                
                return result
            
            # Both services failed, return fallback
            return self._create_fallback_result(user_input, call_id, language)
            
        except Exception as e:
            self.logger.error(f"Local-first processing failed for call {call_id}: {e}")
            return self._create_fallback_result(user_input, call_id, language)
    
    async def _process_hybrid(self, user_input: str, call_id: str,
                            language: LanguageCode, context: Optional[Dict[str, Any]]) -> HybridIntentResult:
        """Process with both services and combine results."""
        try:
            results = []
            
            # Issue 95: Check service availability before and during processing
            # Re-check availability right before processing
            azure_available = await self._check_azure_availability()
            local_available = await self._check_local_availability()
            
            if not azure_available and not local_available:
                # Both services unavailable - return fallback
                self.logger.warning(f"Both services unavailable for hybrid processing, using fallback")
                return self._create_fallback_result(user_input, call_id, language)
            
            # Process with both services in parallel
            tasks = []
            
            if azure_available:  # Issue 95: Use current availability status
                tasks.append(
                    asyncio.wait_for(
                        self.azure_openai.classify_intent(user_input, call_id, language),
                        timeout=self.azure_timeout_seconds
                    )
                )
            
            if local_available:  # Issue 95: Use current availability status
                tasks.append(
                    asyncio.wait_for(
                        asyncio.to_thread(self.local_nlp.process_input, user_input, context),
                        timeout=self.local_timeout_seconds
                    )
                )
            
            if not tasks:
                return self._create_fallback_result(user_input, call_id, language)
            
            # Wait for all tasks to complete
            completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
            
            azure_result = None
            local_result = None
            
            # Issue 94: Handle timeouts specifically
            for i, task_result in enumerate(completed_tasks):
                if isinstance(task_result, Exception):
                    # Issue 94: Check if it's a timeout
                    if isinstance(task_result, asyncio.TimeoutError):
                        self.logger.warning(f"Task {i} timed out: {task_result}")
                        # Issue 94: Continue with other results, don't fail completely
                        continue
                    else:
                        self.logger.warning(f"Task {i} failed: {task_result}")
                        continue
                
                # Issue 95: Use current availability status for result assignment
                if i == 0 and azure_available:
                    azure_result = task_result
                elif (i == 1 and local_available) or (i == 0 and not azure_available and local_available):
                    local_result = task_result
            
            # Issue 164: Properly handle partial results and ensure the best result is used
            # Combine results - handle case where one service fails but the other succeeds
            if azure_result and local_result:
                # Both succeeded - combine them
                return self._combine_results(azure_result, local_result, user_input, call_id, language)
            elif azure_result:
                # Only Azure succeeded
                return HybridIntentResult(
                    intent=azure_result.intent,
                    confidence=azure_result.confidence,
                    entities=azure_result.entities,
                    processing_strategy=ProcessingStrategy.HYBRID,
                    azure_result=azure_result,
                    language=language
                )
            elif local_result:
                # Only local succeeded
                return HybridIntentResult(
                    intent=local_result.intent,
                    confidence=local_result.confidence,
                    entities=self._convert_local_entities(local_result.entities),
                    processing_strategy=ProcessingStrategy.HYBRID,
                    local_result=local_result,
                    language=language
                )
            else:
                # Both failed - return fallback
                return self._create_fallback_result(user_input, call_id, language)
            
        except Exception as e:
            self.logger.error(f"Hybrid processing failed for call {call_id}: {e}")
            return self._create_fallback_result(user_input, call_id, language)
    
    async def _process_azure_only(self, user_input: str, call_id: str,
                                language: LanguageCode, context: Optional[Dict[str, Any]]) -> HybridIntentResult:
        """Process with Azure OpenAI only."""
        try:
            if not self.azure_health:
                return self._create_fallback_result(user_input, call_id, language)
            
            azure_result = await asyncio.wait_for(
                self.azure_openai.classify_intent(user_input, call_id, language),
                timeout=self.azure_timeout_seconds
            )
            
            return HybridIntentResult(
                intent=azure_result.intent,
                confidence=azure_result.confidence,
                entities=azure_result.entities,
                processing_strategy=ProcessingStrategy.AZURE_ONLY,
                azure_result=azure_result,
                language=language
            )
            
        except Exception as e:
            self.logger.error(f"Azure-only processing failed for call {call_id}: {e}")
            return self._create_fallback_result(user_input, call_id, language)
    
    async def _process_local_only(self, user_input: str, call_id: str,
                                language: LanguageCode, context: Optional[Dict[str, Any]]) -> HybridIntentResult:
        """Process with local NLP only."""
        try:
            if not self.local_health:
                return self._create_fallback_result(user_input, call_id, language)
            
            local_result = await asyncio.wait_for(
                asyncio.to_thread(self.local_nlp.process_input, user_input, context),
                timeout=self.local_timeout_seconds
            )
            
            return HybridIntentResult(
                intent=local_result.intent,
                confidence=local_result.confidence,
                entities=self._convert_local_entities(local_result.entities),
                processing_strategy=ProcessingStrategy.LOCAL_ONLY,
                local_result=local_result,
                language=language
            )
            
        except Exception as e:
            self.logger.error(f"Local-only processing failed for call {call_id}: {e}")
            return self._create_fallback_result(user_input, call_id, language)
    
    def _combine_results(self, azure_result: Optional[AzureIntentResult],
                        local_result: Optional[LocalIntentResult],
                        user_input: str, call_id: str, language: LanguageCode) -> HybridIntentResult:
        """Combine results from both services."""
        try:
            if azure_result and local_result:
                # Both results available, choose the one with higher confidence
                if azure_result.confidence >= local_result.confidence:
                    primary_result = azure_result
                    secondary_result = local_result
                else:
                    primary_result = local_result
                    secondary_result = azure_result
                
                # Combine entities (with null checks)
                combined_entities = []
                if azure_result and azure_result.entities:
                    try:
                        combined_entities = azure_result.entities.copy() if hasattr(azure_result.entities, 'copy') else list(azure_result.entities)
                    except (AttributeError, TypeError):
                        combined_entities = list(azure_result.entities) if azure_result.entities else []
                
                if local_result and local_result.entities:
                    combined_entities.extend(self._convert_local_entities(local_result.entities))
                
                return HybridIntentResult(
                    intent=primary_result.intent,
                    confidence=max(azure_result.confidence if azure_result else 0,
                                 local_result.confidence if local_result else 0),
                    entities=combined_entities,
                    processing_strategy=ProcessingStrategy.HYBRID,
                    azure_result=azure_result,
                    local_result=local_result,
                    language=language
                )
            
            elif azure_result:
                return HybridIntentResult(
                    intent=azure_result.intent,
                    confidence=azure_result.confidence,
                    entities=azure_result.entities,
                    processing_strategy=ProcessingStrategy.HYBRID,
                    azure_result=azure_result,
                    language=language
                )
            
            elif local_result:
                return HybridIntentResult(
                    intent=local_result.intent,
                    confidence=local_result.confidence,
                    entities=self._convert_local_entities(local_result.entities),
                    processing_strategy=ProcessingStrategy.HYBRID,
                    local_result=local_result,
                    language=language
                )
            
            else:
                return self._create_fallback_result(user_input, call_id, language)
                
        except Exception as e:
            self.logger.error(f"Failed to combine results: {e}")
            return self._create_fallback_result(user_input, call_id, language)
    
    def _convert_local_entities(self, local_entities: ExtractedEntities) -> List[Dict[str, Any]]:
        """Convert local entities to Azure format."""
        entities = []
        
        if local_entities.appointment_date:
            entities.append({
                "type": "date",
                "value": local_entities.appointment_date,
                "confidence": 0.8
            })
        
        if local_entities.appointment_time:
            entities.append({
                "type": "time",
                "value": local_entities.appointment_time,
                "confidence": 0.8
            })
        
        if local_entities.phone_numbers:
            for phone in local_entities.phone_numbers:
                entities.append({
                    "type": "phone_number",
                    "value": phone,
                    "confidence": 0.9
                })
        
        if local_entities.emails:
            for email in local_entities.emails:
                entities.append({
                    "type": "email",
                    "value": email,
                    "confidence": 0.9
                })
        
        if local_entities.names:
            for name in local_entities.names:
                entities.append({
                    "type": "name",
                    "value": name,
                    "confidence": 0.7
                })
        
        return entities
    
    def _create_fallback_result(self, user_input: str, call_id: str, language: LanguageCode) -> HybridIntentResult:
        """Create a fallback result when all processing fails."""
        # Import single source of truth for intent types
        from models.enums import IntentType
        
        # Simple keyword-based fallback
        user_input_lower = user_input.lower()
        
        if any(word in user_input_lower for word in ["book", "schedule", "appointment", "cita", "agendar"]):
            intent = IntentType.APPOINTMENT_BOOKING
        elif any(word in user_input_lower for word in ["cancel", "cancelar"]):
            intent = IntentType.APPOINTMENT_CANCELLATION
        elif any(word in user_input_lower for word in ["reschedule appointment", "reagendar cita", "change appointment", "cambiar cita"]):
            intent = IntentType.APPOINTMENT_RESCHEDULING
        elif any(word in user_input_lower for word in ["hello", "hi", "hola", "buenas tardes", "buenas noches", "buenos dias"]):
            intent = IntentType.GREETING
        elif any(word in user_input_lower for word in ["bye", "goodbye", "adios", "hasta luego", "chao"]):
            intent = IntentType.GOODBYE
        else:
            intent = IntentType.GENERAL_INQUIRY
        
        # Issue 62: Extract entities from user input in fallback result
        entities = []
        try:
            # Simple entity extraction for fallback
            # Extract names (simple pattern matching)
            import re
            name_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
            names = re.findall(name_pattern, user_input)
            for name in names[:3]:  # Limit to 3 names
                entities.append({
                    "type": "name",
                    "value": name,
                    "confidence": 0.5
                })
            
            # Extract dates (simple pattern matching)
            date_pattern = r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b'
            dates = re.findall(date_pattern, user_input)
            for date in dates[:2]:  # Limit to 2 dates
                entities.append({
                    "type": "date",
                    "value": date,
                    "confidence": 0.5
                })
            
            # Extract times (simple pattern matching)
            time_pattern = r'\b(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)\b'
            times = re.findall(time_pattern, user_input)
            for time in times[:2]:  # Limit to 2 times
                entities.append({
                    "type": "time",
                    "value": time,
                    "confidence": 0.5
                })
        except Exception as entity_error:
            self.logger.warning(f"Failed to extract entities in fallback: {entity_error}")
        
        return HybridIntentResult(
            intent=intent,
            confidence=0.3,  # Low confidence for fallback
            entities=entities,  # Issue 62: Include extracted entities
            processing_strategy=ProcessingStrategy.LOCAL_ONLY,
            language=language,
            fallback_used=True
        )
    
    async def _check_service_health(self):
        """Check the health of both services."""
        try:
            current_time = datetime.now(timezone.utc)
            if (current_time - self.last_health_check).total_seconds() < self.health_check_interval:
                return  # Skip health check if too recent
            
            # Use unique health check call_id with timestamp
            health_check_id = f"health_check_{int(datetime.now(timezone.utc).timestamp())}"
            
            # Check Azure OpenAI health
            try:
                test_result = await asyncio.wait_for(
                    self.azure_openai.classify_intent("test", health_check_id, LanguageCode.ENGLISH),
                    timeout=10  # Increased from 5 to 10 seconds
                )
                self.azure_health = True
            except Exception as e:
                self.azure_health = False
                self.logger.warning(f"Azure OpenAI health check failed: {e}")
            finally:
                # Clean up health check conversation immediately (with error handling)
                try:
                    if hasattr(self.azure_openai, 'conversations') and health_check_id in self.azure_openai.conversations:
                        del self.azure_openai.conversations[health_check_id]
                except Exception as cleanup_error:
                    self.logger.warning(f"Failed to cleanup health check conversation: {cleanup_error}")
            
            # Check local NLP health
            try:
                test_result = await asyncio.wait_for(
                    asyncio.to_thread(self.local_nlp.process_input, "test"),
                    timeout=2
                )
                self.local_health = True
            except Exception as e:
                self.local_health = False
                self.logger.warning(f"Local NLP health check failed: {e}")
            
            self.last_health_check = current_time
        except Exception as e:
            # Issue 183: Handle health check failures and update service status accordingly
            self.logger.error(f"Health check failed: {e}")
            # Issue 183: Mark services as unavailable if health check fails completely
            self.azure_health = False
            self.local_health = False
            # Issue 183: Log the failure for monitoring
            self.logger.warning(f"Both services marked as unavailable due to health check failure: {e}")
    
    async def _check_azure_availability(self) -> bool:
        """Check if Azure OpenAI service is available."""
        try:
            return self.azure_health
        except Exception:
            return False
    
    async def _check_local_availability(self) -> bool:
        """Check if local NLP service is available."""
        try:
            return self.local_health
        except Exception:
            return False
    
    async def _update_processing_stats(self, call_id: str, result: HybridIntentResult):
        """Update processing statistics."""
        # Validate inputs
        if not call_id:
            return
        
        # Access with lock
        async with self._stats_lock:
            if call_id not in self.call_stats:
                self.call_stats[call_id] = ProcessingStats()
            
            stats = self.call_stats[call_id]
            if not stats:
                return
            
            stats.total_requests += 1
            stats.total_processing_time += result.processing_time_ms
            
            if result.processing_strategy == ProcessingStrategy.AZURE_FIRST:
                stats.azure_requests += 1
            elif result.processing_strategy == ProcessingStrategy.LOCAL_FIRST:
                stats.local_requests += 1
            elif result.processing_strategy == ProcessingStrategy.HYBRID:
                stats.hybrid_requests += 1
            
            if result.fallback_used:
                stats.fallback_requests += 1
            
            # Update success rates (with division by zero checks)
            if stats.azure_requests > 0:
                stats.azure_success_rate = (stats.azure_requests - stats.fallback_requests) / stats.azure_requests
            else:
                stats.azure_success_rate = 0.0
            
            if stats.local_requests > 0:
                stats.local_success_rate = (stats.local_requests - stats.fallback_requests) / stats.local_requests
            else:
                stats.local_success_rate = 0.0
            
            # Update average processing time (with division by zero check)
            if stats.total_requests > 0:
                stats.average_processing_time = stats.total_processing_time / stats.total_requests
            else:
                stats.average_processing_time = 0.0
    
    async def _cleanup_cache(self):
        """Clean up expired cache entries."""
        try:
            current_time = datetime.now(timezone.utc)
            expired_keys = []
            
            # Get expired keys with lock
            async with self._cache_lock:
                for key, result in list(self.intent_cache.items()):  # Create copy to avoid modification during iteration
                    if result:
                        # Use tiered TTL based on intent
                        intent_ttl = self._get_ttl_for_intent(result.intent.value if result.intent else "default")
                        if (current_time - result.timestamp).total_seconds() > intent_ttl:
                            expired_keys.append(key)
            
            # Remove expired keys with lock
            if expired_keys:
                async with self._cache_lock:
                    for key in expired_keys:
                        if key in self.intent_cache:
                            del self.intent_cache[key]
            
            if expired_keys:
                self.logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup cache: {e}")
    
    async def get_processing_statistics(self, call_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get processing statistics.
        
        Args:
            call_id: Optional call ID for call-specific stats
            
        Returns:
            Processing statistics
        """
        # Access with lock
        async with self._stats_lock:
            call_stats_copy = dict(self.call_stats)
        
        if call_id and call_id in call_stats_copy:
            stats = call_stats_copy[call_id]
            if not stats:
                return {"error": "Statistics not found"}
            return {
                "call_id": call_id,
                "total_requests": stats.total_requests,
                "azure_requests": stats.azure_requests,
                "local_requests": stats.local_requests,
                "hybrid_requests": stats.hybrid_requests,
                "fallback_requests": stats.fallback_requests,
                "azure_success_rate": stats.azure_success_rate,
                "local_success_rate": stats.local_success_rate,
                "average_processing_time": stats.average_processing_time,
                "total_processing_time": stats.total_processing_time
            }
        else:
            return {
                "global_stats": {
                    "total_requests": self.processing_stats.total_requests,
                    "azure_requests": self.processing_stats.azure_requests,
                    "local_requests": self.processing_stats.local_requests,
                    "hybrid_requests": self.processing_stats.hybrid_requests,
                    "fallback_requests": self.processing_stats.fallback_requests,
                    "azure_success_rate": self.processing_stats.azure_success_rate,
                    "local_success_rate": self.processing_stats.local_success_rate,
                    "average_processing_time": self.processing_stats.average_processing_time
                },
                "service_health": {
                    "azure_health": self.azure_health,
                    "local_health": self.local_health,
                    "last_health_check": self.last_health_check.isoformat()
                },
                "cache_stats": {
                    "cache_size": len(self.intent_cache),  # Access without lock for read-only
                    "cache_ttl_mapping": self.cache_ttl_mapping,
                    "default_ttl": self.default_ttl
                }
            }
    
    async def cleanup_expired_data(self):
        """Clean up expired data and statistics."""
        try:
            # Clean up old call statistics
            current_time = datetime.now(timezone.utc)
            expired_calls = []
            
            # Get expired calls with lock (create copy to avoid modification during iteration)
            async with self._stats_lock:
                call_stats_copy = dict(self.call_stats)
            
            for call_id, stats in call_stats_copy.items():
                if not stats:
                    expired_calls.append(call_id)
                    continue
                
                # Fix: Compare with stats.start_time (now exists in ProcessingStats)
                if hasattr(stats, 'start_time') and stats.start_time:
                    time_since_start = (current_time - stats.start_time).total_seconds()
                    # Remove stats for calls older than 1 hour or with no requests
                    if stats.total_requests == 0 or time_since_start > 3600:
                        expired_calls.append(call_id)
                else:
                    # No start_time, remove if no requests
                    if stats.total_requests == 0:
                        expired_calls.append(call_id)
            
            # Remove expired calls with lock
            if expired_calls:
                async with self._stats_lock:
                    for call_id in expired_calls:
                        if call_id in self.call_stats:
                            del self.call_stats[call_id]
            
            # Clean up cache
            await self._cleanup_cache()
            
            if expired_calls:
                self.logger.info(f"Cleaned up {len(expired_calls)} expired call statistics")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired data: {e}")


# Global service instance
_hybrid_nlp_service: Optional[HybridNLPService] = None


def get_hybrid_nlp_service() -> HybridNLPService:
    """Get the global Hybrid NLP Service instance."""
    global _hybrid_nlp_service
    if _hybrid_nlp_service is None:
        _hybrid_nlp_service = HybridNLPService()
    return _hybrid_nlp_service
