"""
Call orchestrator for coordinating STT, OpenAI, and TTS pipeline.

This service provides:
- Real-time call flow coordination
- Audio streaming management
- Intent processing pipeline
- Response generation and synthesis
- Bilingual conversation management
- Call state management
- Performance monitoring
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum

from services.azure_speech_stt import get_speech_to_text_service, SpeechToTextService
from services.azure_speech_tts import get_text_to_speech_service, TextToSpeechService
from services.azure_openai_service import get_azure_openai_service, AzureOpenAIService, IntentType
from services.hybrid_nlp_service import get_hybrid_nlp_service, HybridNLPService
from services.bilingual_manager import get_bilingual_manager, LanguageCode
from services.audio_stream_handler import get_audio_stream_handler, AudioStreamHandler
from services.response_templates import get_response_templates
from services.azure_communication_service import get_azure_communication_service
from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ValidationError,
    ExternalServiceUnavailableError,
    CallOrchestrationError
)


logger = get_logger("call_orchestrator")


class CallState(Enum):
    """States of a call in the orchestrator."""
    INITIALIZING = "initializing"
    CONNECTED = "connected"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    WAITING = "waiting"
    TRANSFERRING = "transferring"
    ENDING = "ending"
    ENDED = "ended"
    ERROR = "error"


class CallType(Enum):
    """Types of calls."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    REMINDER = "reminder"
    FOLLOW_UP = "follow_up"


@dataclass
class CallContext:
    """Context for a call session."""
    call_id: str
    caller_phone: Optional[str] = None
    clinic_id: Optional[str] = None
    call_type: Optional[CallType] = None
    state: CallState = CallState.INITIALIZING
    language: LanguageCode = LanguageCode.ENGLISH
    start_time: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    audio_stream_handler: Optional[AudioStreamHandler] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    current_intent: Optional[IntentType] = None
    entities: List[Dict[str, Any]] = field(default_factory=list)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    call_metadata: Dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    max_errors: int = 5


@dataclass
class CallMetrics:
    """Metrics for call performance."""
    call_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_duration_seconds: float = 0.0
    stt_processing_time: float = 0.0
    nlp_processing_time: float = 0.0
    tts_processing_time: float = 0.0
    total_interactions: int = 0
    successful_interactions: int = 0
    language_switches: int = 0
    errors: int = 0
    average_response_time: float = 0.0


class CallOrchestrator:
    """
    Orchestrates the complete call flow pipeline.
    
    Coordinates STT, NLP/OpenAI, and TTS services to provide
    seamless conversational AI experience.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        
        # Service dependencies
        self.stt_service = get_speech_to_text_service()
        self.tts_service = get_text_to_speech_service()
        self.openai_service = get_azure_openai_service()
        self.hybrid_nlp = get_hybrid_nlp_service()
        self.bilingual_manager = get_bilingual_manager()
        self.response_templates = get_response_templates()
        self.audio_stream_handler = get_audio_stream_handler()
        
        # Active calls
        self.active_calls: Dict[str, CallContext] = {}
        self.call_metrics: Dict[str, CallMetrics] = {}
        
        # Initialize locks for thread safety
        self._stats_lock = asyncio.Lock()
        self._calls_lock = asyncio.Lock()
        
        # Configuration
        self.max_concurrent_calls = 100
        self.call_timeout_minutes = 30
        self.silence_timeout_seconds = 10
        self.max_conversation_turns = 50
        
        # Performance tracking
        self.orchestration_stats: Dict[str, Any] = {
            "total_calls": 0,
            "active_calls": 0,
            "completed_calls": 0,
            "failed_calls": 0,
            "average_call_duration": 0.0,
            "average_response_time": 0.0
        }
        
        # Event callbacks
        self.callbacks: Dict[str, List[Callable]] = {
            "call_started": [],
            "call_ended": [],
            "intent_detected": [],
            "response_generated": [],
            "language_switched": [],
            "error_occurred": []
        }
        
        self.logger.info(
            "Call orchestrator initialized",
            LogCategory.CALL_ORCHESTRATION,
            extra_data={
                "max_concurrent_calls": self.max_concurrent_calls,
                "call_timeout_minutes": self.call_timeout_minutes,
                "silence_timeout_seconds": self.silence_timeout_seconds
            }
        )
    
    @log_performance("orchestrator_start_call")
    async def start_call(self, call_id: str, caller_phone: str, clinic_id: str, 
                        call_type: str = 'inbound',
                        language: LanguageCode = LanguageCode.ENGLISH,
                        audio_stream_handler: Optional[AudioStreamHandler] = None,
                        call_metadata: Optional[Dict[str, Any]] = None) -> CallContext:
        """
        Start a new call session.
        
        Args:
            call_id: Unique identifier for the call
            caller_phone: Phone number of the caller
            clinic_id: ID of the clinic handling the call
            call_type: Type of call (inbound/outbound/reminder)
            language: Initial language for the call
            audio_stream_handler: Audio stream handler for the call
            call_metadata: Additional metadata for the call
            
        Returns:
            Call context for the new call
        """
        try:
            # Validate inputs
            if not call_id:
                raise ValidationError("call_id", call_id, "Call ID cannot be empty")
            
            # Check if call already exists (with lock)
            async with self._calls_lock:
                if call_id in self.active_calls:
                    self.logger.warning(f"Call {call_id} already exists")
                    return self.active_calls[call_id]
                
                if len(self.active_calls) >= self.max_concurrent_calls:
                    raise CallOrchestrationError("max_calls_exceeded", "Maximum concurrent calls exceeded")
            
            # Create call context
            # Capture timestamp once
            current_time = datetime.now(AST)
            
            call_context = CallContext(
                call_id=call_id,
                caller_phone=caller_phone,
                clinic_id=clinic_id,
                call_type=call_type,
                state=CallState.INITIALIZING,
                language=language,
                start_time=current_time,
                last_activity=current_time,
                audio_stream_handler=audio_stream_handler
            )
            
            # Create call metrics
            call_metrics = CallMetrics(
                call_id=call_id,
                start_time=current_time
            )
            
            # Store call context and metrics (with lock)
            async with self._calls_lock:
                self.active_calls[call_id] = call_context
                self.call_metrics[call_id] = call_metrics
            
            # Initialize audio stream handler
            if audio_stream_handler:
                await self._initialize_audio_stream(call_context)
            
            # Set up call timeout
            timeout_task = asyncio.create_task(self._monitor_call_timeout(call_id))
            call_context.metadata['timeout_task'] = timeout_task
            
            # Update state
            call_context.state = CallState.CONNECTED
            call_context.last_activity = datetime.now(AST)
            
            # Update statistics (with lock)
            async with self._stats_lock:
                self.orchestration_stats["total_calls"] += 1
                self.orchestration_stats["active_calls"] += 1
            
            # Trigger callbacks
            await self._trigger_callbacks("call_started", call_context)
            
            self.logger.info(
                f"Call started: {call_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    "call_id": call_id,
                    "call_type": call_type.value,
                    "language": language.value,
                    "active_calls": len(self.active_calls)
                }
            )
            
            return call_context
            
        except Exception as e:
            self.logger.error(
                f"Failed to start call {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
            raise
    
    async def play_greeting(self, call_id: str):
        """Play greeting message to the caller."""
        try:
            call_context = self.active_calls.get(call_id)
            if not call_context:
                self.logger.error(f"Call {call_id} not found for greeting")
                return
            
            # Generate greeting message
            greeting_text = "Hello! Thank you for calling. How can I help you today?"
            
            # Synthesize and play greeting
            await self._synthesize_response(call_context, greeting_text)
            
            self.logger.info(
                f"Greeting played for call {call_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={"call_id": call_id}
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to play greeting for call {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
    
    async def _handle_emergency(self, call_context: CallContext):
        """Handle emergency calls - transfer to human immediately"""
        try:
            # Get emergency transfer number from system config
            emergency_number = await self._get_config_value(
                call_context.clinic_id, 
                'emergency_transfer_number',
                fallback='911'
            )
            
            # Log emergency transfer
            await self._log_audit(
                clinic_id=call_context.clinic_id,
                action='emergency_transfer',
                entity_type='call',
                entity_id=call_context.call_id,
                metadata={'emergency_number': emergency_number}
            )
            
            # Play emergency message
            message = "This is an emergency. Transferring you immediately to our emergency line."
            await self._synthesize_response(call_context, message)
            
            # Transfer call
            await self._transfer_call(call_context.call_id, emergency_number)
            
            logger.info(f"Emergency call {call_context.call_id} transferred to {emergency_number}")
            
        except Exception as e:
            logger.error(f"Error handling emergency call {call_context.call_id}: {e}")
    
    async def _transfer_to_department(self, call_context: CallContext, department: str):
        """Transfer call to human agent in specific department"""
        try:
            # Get department transfer number
            dept_key = f"{department}_department_number"
            transfer_number = await self._get_config_value(
                call_context.clinic_id,
                dept_key,
                fallback='+1234567890'  # Default clinic number
            )
            
            # Play transfer message
            message = f"Transferring you to our {department} department."
            await self._synthesize_response(call_context, message)
            
            # Transfer call
            await self._transfer_call(call_context.call_id, transfer_number)
            
            logger.info(f"Call {call_context.call_id} transferred to {department} department")
            
        except Exception as e:
            logger.error(f"Error transferring call to {department}: {e}")
    
    async def _handle_provider_inquiry(self, call_context: CallContext, entities: Dict[str, Any]):
        """Handle provider information requests"""
        try:
            # Use Azure OpenAI to answer provider questions
            provider_info = await self._get_provider_info(call_context.clinic_id, entities)
            
            if provider_info:
                response = f"Here's the information you requested: {provider_info}"
            else:
                response = "I don't have that information available. Let me transfer you to our staff."
                await self._transfer_to_department(call_context, 'general')
                return
            
            await self._synthesize_response(call_context, response)
            
        except Exception as e:
            logger.error(f"Error handling provider inquiry: {e}")
    
    async def _handle_general_inquiry(self, call_context: CallContext, intent_result):
        """Handle general FAQ using Azure OpenAI"""
        try:
            # Use Azure OpenAI for general questions
            response = await self.openai_service.generate_response(
                call_context.conversation_history,
                intent_result.entities
            )
            
            await self._synthesize_response(call_context, response)
            
        except Exception as e:
            logger.error(f"Error handling general inquiry: {e}")
    
    async def _transfer_call(self, call_id: str, transfer_number: str):
        """Transfer call to another number (stub - logs only, doesn't crash)"""
        try:
            logger.info(f"Transfer requested for call {call_id} to {transfer_number}")
            logger.warning(f"Call transfer not yet implemented - call will continue with AI")
            
            # Update call state to show transfer was attempted
            if call_id in self.active_calls:
                self.active_calls[call_id].state = CallState.LISTENING
                
            # For now, just continue the call with AI instead of crashing
            # TODO: Implement actual ACS transfer API call
            
        except Exception as e:
            logger.error(f"Error in transfer stub for call {call_id}: {e}")
            # Don't raise - just log and continue
    
    async def _get_config_value(self, clinic_id: str, key: str, fallback: str = None):
        """Get configuration value from system_config table"""
        try:
            from services.database import get_db_session
            from models.models import SystemConfig
            
            # Query system_config table
            with get_db_session() as db:
                config = db.query(SystemConfig).filter(
                    SystemConfig.config_key == key,
                    SystemConfig.is_deleted == 'no'
                ).first()
                
                if config:
                    return config.config_value
                else:
                    logger.warning(f"Config key '{key}' not found for clinic {clinic_id}, using fallback: {fallback}")
                    return fallback or "911"
                    
        except Exception as e:
            logger.error(f"Error getting config value {key}: {e}")
            return fallback or "911"
    
    async def _log_audit(self, clinic_id: str, action: str, entity_type: str, entity_id: str, metadata: Dict = None):
        """Log audit event"""
        try:
            # This would insert into audit_logs table
            logger.info(f"Audit log: {action} on {entity_type} {entity_id} for clinic {clinic_id}")
        except Exception as e:
            logger.error(f"Error logging audit event: {e}")
    
    async def _get_provider_info(self, clinic_id: str, entities: Dict[str, Any]):
        """Get provider information based on entities"""
        try:
            # This would query providers table
            # For now, return placeholder
            return "Provider information not available"
        except Exception as e:
            logger.error(f"Error getting provider info: {e}")
            return None

    async def _monitor_call_timeout(self, call_id: str):
        """Monitor call timeout and cleanup if exceeded."""
        try:
            timeout_seconds = self.call_timeout_minutes * 60
            
            # Wait for timeout period
            await asyncio.sleep(timeout_seconds)
            
            # Check if call still exists and hasn't been active
            call_context = self.active_calls.get(call_id)
            if not call_context:
                return
            
            # Check if call has been inactive for too long
            time_since_activity = datetime.now(AST) - call_context.last_activity
            if time_since_activity.total_seconds() > timeout_seconds:
                self.logger.warning(
                    f"Call {call_id} timed out after {timeout_seconds} seconds",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_id, "timeout_seconds": timeout_seconds}
                )
                
                # End the call
                await self.end_call(call_id, "timeout")
            
        except asyncio.CancelledError:
            # Call was ended normally, cancel timeout monitoring
            pass
        except Exception as e:
            self.logger.error(
                f"Error monitoring timeout for call {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
    
    async def _trigger_callbacks(self, event_type: str, call_context: CallContext):
        """Trigger registered callbacks for the given event."""
        try:
            callbacks = self.callbacks.get(event_type, [])
            if not callbacks:
                return
            
            # Execute all callbacks
            for callback in callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(call_context)
                    else:
                        callback(call_context)
                except Exception as e:
                    self.logger.error(
                        f"Error in callback for {event_type}: {e}",
                        LogCategory.CALL_ORCHESTRATION,
                        exception=e
                    )
                    
        except Exception as e:
            self.logger.error(
                f"Error triggering callbacks for {event_type}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
    
    async def _handle_call_error(self, call_id: str, error: Exception):
        """Handle errors during call processing."""
        try:
            call_context = self.active_calls.get(call_id)
            if not call_context:
                return
            
            # Increment error count
            call_context.error_count += 1
            
            # Check if we've exceeded max errors
            if call_context.error_count >= call_context.max_errors:
                self.logger.error(
                    f"Call {call_id} exceeded max errors ({call_context.max_errors}), ending call",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_id, "error_count": call_context.error_count}
                )
                
                # End the call
                await self.end_call(call_id, "error_limit_exceeded")
                return
            
            # Log the error
            self.logger.error(
                f"Error in call {call_id}: {error}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={"call_id": call_id, "error_count": call_context.error_count},
                exception=error
            )
            
            # Try to play error message
            try:
                error_message = "I'm sorry, I'm having trouble processing your request. Please try again."
                await self._synthesize_response(call_context, error_message)
            except Exception as synthesis_error:
                self.logger.error(
                    f"Failed to synthesize error message for call {call_id}: {synthesis_error}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=synthesis_error
                )
                
        except Exception as e:
            self.logger.error(
                f"Error handling call error for {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
    
    async def _play_text_source_fallback(self, call_context: CallContext, text: str):
        """Fallback method to play text using ACS Play API when TTS fails."""
        try:
            # Use ACS Play API as fallback
            acs_service = get_azure_communication_service()
            call_state = acs_service.active_calls.get(call_context.call_id)
            
            if call_state and call_state.acs_call_id:
                # Use Play API to play text
                await acs_service.play_audio_to_call(
                    call_id=call_context.call_id,
                    text=text,
                    language=call_context.language.value
                )
                
                self.logger.info(
                    f"Fallback text played via ACS Play API for call {call_context.call_id}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_context.call_id}
                )
            else:
                self.logger.error(
                    f"No ACS call state found for fallback playback: {call_context.call_id}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_context.call_id}
                )
                
        except Exception as e:
            self.logger.error(
                f"Failed to play fallback text for call {call_context.call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )

    async def _initialize_audio_stream(self, call_context: CallContext):
        """Initialize audio stream for the call."""
        try:
            if not call_context.audio_stream_handler:
                return
            
            # Register STT callback
            def stt_callback(call_id: str, text: str, detected_language: str):
                asyncio.create_task(self._handle_speech_input(call_id, text, detected_language))
            
            call_context.audio_stream_handler.register_stt_callback(call_context.call_id, stt_callback)
            
            # Register TTS callback
            def tts_callback(call_id: str, text: str) -> bytes:
                # Use create_task to handle async synthesis without blocking
                asyncio.create_task(self._handle_tts_synthesis(call_id, text, call_context.language.value))
                return b''  # Return empty bytes immediately, audio sent via WebSocket
            
            call_context.audio_stream_handler.register_tts_callback(tts_callback)
            
            self.logger.debug(f"Audio stream initialized for call {call_context.call_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize audio stream for call {call_context.call_id}: {e}")
    
    async def _handle_tts_synthesis(self, call_id: str, text: str, language: str):
        """Handle TTS synthesis asynchronously."""
        try:
            synthesis_result = await self.tts_service.synthesize_speech(text, language, call_id)
            if synthesis_result.success and call_id in self.active_calls:
                call_context = self.active_calls[call_id]
                if call_context.audio_stream_handler:
                    await call_context.audio_stream_handler.send_tts_audio(call_id, synthesis_result.audio_data)
        except Exception as e:
            self.logger.error(f"TTS synthesis failed in callback: {e}")
    
    async def _handle_speech_input(self, call_id: str, text: str, detected_language: str):
        """Handle speech input from STT service."""
        try:
            async with self._calls_lock:
                if call_id not in self.active_calls:
                    self.logger.warning(f"Received speech input for inactive call: {call_id}")
                    return
                call_context = self.active_calls[call_id]
                current_language = call_context.language

            # Continue processing outside lock
            call_context.state = CallState.PROCESSING
            call_context.last_activity = datetime.now(AST)
            
            # Detect language
            detected_lang = LanguageCode.ENGLISH if detected_language.startswith("en") else LanguageCode.SPANISH
            
            # Only switch if language actually changed
            if detected_lang != current_language:
                async with self._calls_lock:
                    # Double-check language hasn't changed (avoid race)
                    if call_context.language == current_language:
                        await self._handle_language_switch(call_context, detected_lang)
            
            # Process the input
            await self._process_user_input(call_context, text, detected_lang)
            
        except Exception as e:
            self.logger.error(f"Failed to handle speech input for call {call_id}: {e}")
            await self._handle_call_error(call_id, e)
    
    async def _process_user_input(self, call_context: CallContext, text: str, language: LanguageCode):
        """Process user input through the NLP pipeline."""
        try:
            start_time = time.time()
            
            # Classify intent using hybrid NLP
            intent_result = await self.hybrid_nlp.process_input(
                user_input=text,
                call_id=call_context.call_id,
                language=language
            )
            
            # Update call context
            call_context.current_intent = intent_result.intent
            call_context.entities = intent_result.entities
            call_context.language = language
            
            # Add to conversation history
            call_context.conversation_history.append({
                "role": "user",
                "content": text,
                "timestamp": datetime.now(AST),
                "intent": intent_result.intent.value if hasattr(intent_result.intent, 'value') else str(intent_result.intent),
                "confidence": intent_result.confidence,
                "language": language.value
            })

            # Trim history to last 20 messages (10 exchanges)
            if len(call_context.conversation_history) > 20:
                call_context.conversation_history = call_context.conversation_history[-20:]
            
            # Update metrics
            call_metrics = self.call_metrics[call_context.call_id]
            call_metrics.nlp_processing_time += time.time() - start_time
            call_metrics.total_interactions += 1
            
            # Generate response
            await self._generate_response(call_context, intent_result)
            
            # Trigger callbacks
            await self._trigger_callbacks("intent_detected", call_context, intent_result)
            
        except Exception as e:
            self.logger.error(f"Failed to process user input for call {call_context.call_id}: {e}")
            await self._handle_call_error(call_context.call_id, e)
    
    async def _generate_response(self, call_context: CallContext, intent_result):
        """Generate and synthesize response based on intent."""
        try:
            start_time = time.time()
            
            # Route based on intent
            intent = intent_result.intent
            
            if intent in [IntentType.APPOINTMENT_BOOKING, IntentType.APPOINTMENT_CANCELLATION, 
                        IntentType.APPOINTMENT_RESCHEDULING]:
                # Use CallFlowService for appointment handling
                from services.call_flow_service import CallFlowService
                from services.database import get_async_db_session
                
                async with get_async_db_session() as db:
                    flow_service = CallFlowService(db)
                    response_text = await flow_service.process_user_input(
                        call_context.call_id, 
                        call_context.conversation_history[-1]['content']
                    )
                
            elif intent == IntentType.INSURANCE_INQUIRY:
                # Transfer to human agent
                await self._transfer_to_department(call_context, 'insurance')
                return
                
            elif intent == IntentType.PROVIDER_INQUIRY:
                # Handle provider information requests
                await self._handle_provider_inquiry(call_context, intent_result.entities)
                return
                
            elif intent == IntentType.EMERGENCY:
                # Immediate transfer to emergency line
                await self._handle_emergency(call_context)
                return
                
            else:
                # General inquiry - use Azure OpenAI for FAQ
                await self._handle_general_inquiry(call_context, intent_result)
                return
            
            # Add response to conversation history
            call_context.conversation_history.append({
                "role": "assistant",
                "content": response_text,
                "timestamp": datetime.now(AST),
                "language": call_context.language.value
            })
            
            # Update call state
            call_context.state = CallState.SPEAKING
            call_context.last_activity = datetime.now(AST)
            
            # Synthesize and play response
            await self._synthesize_response(call_context, response_text)
            
            # Update metrics
            call_metrics = self.call_metrics[call_context.call_id]
            call_metrics.tts_processing_time += time.time() - start_time
            call_metrics.successful_interactions += 1
            
            # Update state to listening
            call_context.state = CallState.LISTENING
            
            # Trigger callbacks
            await self._trigger_callbacks("response_generated", call_context, response_text)
            
        except Exception as e:
            self.logger.error(f"Failed to generate response for call {call_context.call_id}: {e}")
            await self._handle_call_error(call_context.call_id, e)
    
    async def _synthesize_response(self, call_context: CallContext, response_text: str):
        """Synthesize and play response using TTS with retry logic."""
        MAX_RETRIES = 3
        
        try:
            # Synthesize speech
            synthesis_result = await self.tts_service.synthesize_speech(
                text=response_text,
                language=call_context.language.value,
                call_id=call_context.call_id
            )
            
            if not synthesis_result.success:
                self.logger.error(f"TTS synthesis failed for call {call_context.call_id}: {synthesis_result.error_message}")
                # Fallback to TextSource when TTS fails
                await self._play_text_source_fallback(call_context, response_text)
                return
            
            # Try multiple times with retry logic
            for attempt in range(MAX_RETRIES):
                try:
                    # Try WebSocket audio streaming first
                    if call_context.audio_stream_handler:
                        success = await call_context.audio_stream_handler.send_tts_audio(
                            call_context.call_id, 
                            synthesis_result.audio_data
                        )
                        if success:
                            self.logger.info(f"TTS sent via WebSocket (attempt {attempt + 1})")
                            return
                    
                    # Fallback: Use ACS Play API
                    acs_service = get_azure_communication_service()
                    call_state = acs_service.active_calls.get(call_context.call_id)
                    
                    if call_state and call_state.acs_call_id:
                        success = await acs_service.play_audio_to_call(
                            call_state.acs_call_id,
                            synthesis_result.audio_data
                        )
                        if success:
                            self.logger.info(f"TTS sent via ACS Play API (attempt {attempt + 1})")
                            return
                    
                    # Exponential backoff
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)
                    
                except Exception as e:
                    self.logger.error(f"TTS playback attempt {attempt + 1} failed: {e}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)
            
            # All retries exhausted
            self.logger.error(f"Failed to play TTS audio after {MAX_RETRIES} attempts")
            # Fallback to TextSource
            await self._play_text_source_fallback(call_context, response_text)
                
        except Exception as e:
            self.logger.error(f"Failed to synthesize response for call {call_context.call_id}: {e}", exc_info=True)
            # Fallback to TextSource when TTS fails
            await self._play_text_source_fallback(call_context, response_text)
    
    async def _play_text_source_fallback(self, call_context: CallContext, text: str):
        """Fallback to ACS TextSource when TTS synthesis fails."""
        try:
            acs_service = get_azure_communication_service()
            call_state = acs_service.active_calls.get(call_context.call_id)
            
            if call_state and call_state.acs_call_id:
                # Use ACS TextSource for immediate playback
                success = await acs_service.play_scripted_text(
                    call_state.acs_call_id, 
                    text, 
                    call_context.language.value
                )
                
                if success:
                    self.logger.info(f"Response played via TextSource fallback for call {call_context.call_id}")
                else:
                    self.logger.error(f"TextSource fallback failed for call {call_context.call_id}")
            else:
                self.logger.error(f"No ACS call connection for TextSource fallback: {call_context.call_id}")
                
        except Exception as e:
            self.logger.error(f"TextSource fallback failed for call {call_context.call_id}: {e}")
            await self._handle_call_error(call_context.call_id, e)
    
    async def _play_response(self, call_id: str, text: str, is_scripted: bool = False):
        """
        Play response - automatically uses TextSource or WebSocket based on is_scripted flag.
        
        Args:
            call_id: Call session ID
            text: Response text to play
            is_scripted: True for scripted responses (TextSource), False for AI responses (WebSocket)
        """
        try:
            async with self._calls_lock:
                call_context = self.active_calls.get(call_id)
                if not call_context:
                    self.logger.error(f"Call context not found for {call_id}")
                    return
            
            acs_service = get_azure_communication_service()
            call_state = acs_service.active_calls.get(call_id)
            
            if not call_state or not call_state.acs_call_id:
                self.logger.error(f"No ACS call connection for {call_id}")
                return
            
            if is_scripted:
                # Fast, reliable TextSource (no tokens, no TTS processing)
                self.logger.info(f"Playing scripted response via TextSource for call {call_id}")
                
                # Use ACS TextSource for immediate playback
                success = await acs_service.play_scripted_text(
                    call_state.acs_call_id, 
                    text, 
                    call_context.language.value
                )
                
                if success:
                    self.logger.debug(f"Scripted response played successfully for call {call_id}")
                else:
                    self.logger.error(f"Failed to play scripted response for call {call_id}")
                    
            else:
                # High-quality Azure Speech SDK (uses tokens, better quality)
                self.logger.info(f"Playing AI response via WebSocket for call {call_id}")
                
                # Synthesize speech using TTS service
                synthesis_result = await self.tts_service.synthesize_speech(
                    text=text,
                    language=call_context.language.value,
                    call_id=call_id
                )
                
                if not synthesis_result.success:
                    self.logger.error(f"TTS synthesis failed for call {call_id}: {synthesis_result.error_message}")
                    # Fallback to TextSource
                    await acs_service.play_scripted_text(
                        call_state.acs_call_id, 
                        text, 
                        call_context.language.value
                    )
                    return
                
                # Try WebSocket audio streaming first
                if call_context.audio_stream_handler:
                    success = await call_context.audio_stream_handler.send_tts_audio(
                        call_id, 
                        synthesis_result.audio_data
                    )
                    if success:
                        self.logger.debug(f"AI response sent via WebSocket for call {call_id}")
                        return
                
                # Fallback: Use ACS Play API
                success = await acs_service.play_audio_to_call(
                    call_state.acs_call_id,
                    synthesis_result.audio_data
                )
                
                if success:
                    self.logger.info(f"AI response played via ACS Play API for call {call_id}")
                else:
                    self.logger.error(f"Failed to play AI response for call {call_id}")
                    
        except Exception as e:
            self.logger.error(f"Failed to play response for call {call_id}: {e}", exc_info=True)
    
    async def _handle_language_switch(self, call_context: CallContext, new_language: LanguageCode):
        """Handle language switch during the call."""
        try:
            old_language = call_context.language
            call_context.language = new_language
            
            # Update bilingual manager
            self.bilingual_manager.set_language_preference(
                call_context.call_id,
                new_language,
                "user"
            )
            
            # Update metrics
            call_metrics = self.call_metrics[call_context.call_id]
            call_metrics.language_switches += 1
            
            # Trigger callbacks
            await self._trigger_callbacks("language_switched", call_context, {
                "old_language": old_language.value,
                "new_language": new_language.value
            })
            
            self.logger.info(
                f"Language switched for call {call_context.call_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    "call_id": call_context.call_id,
                    "old_language": old_language.value,
                    "new_language": new_language.value
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to handle language switch for call {call_context.call_id}: {e}")
    
    async def _handle_call_error(self, call_id: str, error: Exception):
        """Handle errors during call processing."""
        try:
            if call_id not in self.active_calls:
                return
            
            call_context = self.active_calls[call_id]
            call_context.error_count += 1
            
            # Update metrics
            call_metrics = self.call_metrics[call_id]
            call_metrics.errors += 1
            
            # Check if we should end the call due to too many errors
            if call_context.error_count >= call_context.max_errors:
                self.logger.error(f"Too many errors for call {call_id}, ending call")
                await self.end_call(call_id, "excessive_errors")
                return
            
            # Update call state
            call_context.state = CallState.ERROR
            
            # Trigger callbacks
            await self._trigger_callbacks("error_occurred", call_context, error)
            
            # Try to recover
            await self._recover_from_error(call_context)
            
        except Exception as e:
            self.logger.error(f"Failed to handle call error for call {call_id}: {e}")
    
    async def _recover_from_error(self, call_context: CallContext):
        """Attempt to recover from an error."""
        try:
            # Simple recovery: return to listening state
            call_context.state = CallState.LISTENING
            call_context.last_activity = datetime.now(AST)
            
            # Send a generic error message
            error_message = "I'm sorry, I didn't catch that. Could you please repeat?"
            if call_context.language == LanguageCode.SPANISH:
                error_message = "Lo siento, no entendí eso. ¿Podrías repetir por favor?"
            
            await self._synthesize_response(call_context, error_message)
            
        except Exception as e:
            self.logger.error(f"Failed to recover from error for call {call_context.call_id}: {e}")
    
    async def _monitor_call_timeout(self, call_id: str):
        """Monitor call for timeout."""
        try:
            max_iterations = 7200  # 2 hours at 5 second intervals
            iteration = 0
            
            while call_id in self.active_calls and iteration < max_iterations:
                iteration += 1
                call_context = self.active_calls[call_id]
                
                # Check for timeout
                time_since_activity = (datetime.now(AST) - call_context.last_activity).total_seconds()
                if time_since_activity > self.silence_timeout_seconds:
                    self.logger.warning(f"Call {call_id} timed out due to inactivity")
                    await self.end_call(call_id, "timeout")
                    break
                
                # Check for maximum call duration
                call_duration = (datetime.now(AST) - call_context.start_time).total_seconds()
                if call_duration > (self.call_timeout_minutes * 60):
                    self.logger.warning(f"Call {call_id} exceeded maximum duration")
                    await self.end_call(call_id, "max_duration")
                    break
                
                # Check for maximum conversation turns
                if len(call_context.conversation_history) >= self.max_conversation_turns:
                    self.logger.warning(f"Call {call_id} exceeded maximum conversation turns")
                    await self.end_call(call_id, "max_turns")
                    break
                
                await asyncio.sleep(5)  # Check every 5 seconds
            
            if iteration >= max_iterations:
                self.logger.warning(f"Call {call_id} monitoring reached max iterations")
                
        except Exception as e:
            self.logger.error(f"Call timeout monitoring failed for call {call_id}: {e}")
    
    @log_performance("orchestrator_end_call")
    async def end_call(self, call_id: str, reason: str = "normal"):
        """
        End a call session.
        
        Args:
            call_id: ID of the call to end
            reason: Reason for ending the call
        """
        try:
            if call_id not in self.active_calls:
                self.logger.warning(f"Attempted to end inactive call: {call_id}")
                return
            
            call_context = self.active_calls[call_id]
            call_metrics = self.call_metrics.get(call_id)

            if not call_metrics:
                self.logger.warning(f"No metrics found for call {call_id}, creating default")
                call_metrics = CallMetrics(
                    call_id=call_id,
                    start_time=call_context.start_time or datetime.now(AST)
                )
                self.call_metrics[call_id] = call_metrics
            
            # Cancel timeout monitoring task
            timeout_task = call_context.metadata.get('timeout_task')
            if timeout_task and not timeout_task.done():
                timeout_task.cancel()
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass
            
            # Update call state
            call_context.state = CallState.ENDING
            
            # Stop audio stream
            if call_context.audio_stream_handler:
                # Get connection ID from call context metadata
                connection_id = call_context.metadata.get('connection_id')
                if connection_id:
                    await call_context.audio_stream_handler.disconnect_audio_stream(connection_id)
            
            # Update metrics
            call_metrics.end_time = datetime.now(AST)
            call_metrics.total_duration_seconds = (call_metrics.end_time - call_metrics.start_time).total_seconds()
            
            if call_metrics.total_interactions > 0:
                call_metrics.average_response_time = (
                    call_metrics.stt_processing_time + 
                    call_metrics.nlp_processing_time + 
                    call_metrics.tts_processing_time
                ) / call_metrics.total_interactions
            
            # Update statistics
            async with self._stats_lock:
                self.orchestration_stats["active_calls"] -= 1
                self.orchestration_stats["completed_calls"] += 1
                
                if call_metrics.errors > 0:
                    self.orchestration_stats["failed_calls"] += 1
            
            # Update average call duration and clean up with locks
            async with self._calls_lock:
                # Calculate outside lock
                total_duration = sum(m.total_duration_seconds for m in self.call_metrics.values() if m.end_time)
                completed_calls = sum(1 for m in self.call_metrics.values() if m.end_time)
                avg_duration = total_duration / completed_calls if completed_calls > 0 else 0.0
                
                # Clean up
                del self.active_calls[call_id]
                if call_id in self.call_metrics:
                    del self.call_metrics[call_id]

            # Update stats separately
            async with self._stats_lock:
                self.orchestration_stats["average_call_duration"] = avg_duration
            
            # Trigger callbacks
            await self._trigger_callbacks("call_ended", call_context, {"reason": reason})
            
            # Clean up AI conversation history immediately when call finishes
            if hasattr(self, 'azure_openai_service'):
                await self.azure_openai_service.end_conversation(call_id)
            
            self.logger.info(
                f"Call ended: {call_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    "call_id": call_id,
                    "reason": reason,
                    "duration_seconds": call_metrics.total_duration_seconds,
                    "total_interactions": call_metrics.total_interactions,
                    "errors": call_metrics.errors,
                    "active_calls": len(self.active_calls)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to end call {call_id}: {e}")
    
    def register_callback(self, event: str, callback: Callable):
        """Register a callback for orchestration events."""
        if event in self.callbacks:
            self.callbacks[event].append(callback)
        else:
            self.callbacks[event] = [callback]
    
    def unregister_callback(self, event: str, callback: Callable):
        """Unregister a callback."""
        if event in self.callbacks and callback in self.callbacks[event]:
            self.callbacks[event].remove(callback)
    
    async def _trigger_callbacks(self, event: str, *args, **kwargs):
        """Trigger callbacks for an event."""
        if event in self.callbacks:
            for callback in self.callbacks[event]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(*args, **kwargs)
                    else:
                        callback(*args, **kwargs)
                except Exception as e:
                    self.logger.error(f"Callback error for event {event}: {e}")
    
    def get_call_context(self, call_id: str) -> Optional[CallContext]:
        """Get call context by ID."""
        return self.active_calls.get(call_id)
    
    def get_call_metrics(self, call_id: str) -> Optional[CallMetrics]:
        """Get call metrics by ID."""
        return self.call_metrics.get(call_id)
    
    def get_orchestration_statistics(self) -> Dict[str, Any]:
        """Get orchestration statistics."""
        return {
            "orchestration_stats": self.orchestration_stats.copy(),
            "active_calls": len(self.active_calls),
            "call_states": {
                call_id: context.state.value 
                for call_id, context in self.active_calls.items()
            },
            "service_health": {
                "stt_service": True,  # TODO: Add health checks
                "tts_service": True,
                "openai_service": True,
                "hybrid_nlp": True
            }
        }
    
    async def cleanup_expired_calls(self):
        """Clean up expired call data."""
        try:
            current_time = datetime.now(AST)
            expired_calls = []
            
            # Find expired calls (older than 1 hour)
            for call_id, metrics in self.call_metrics.items():
                if metrics.end_time and (current_time - metrics.end_time).total_seconds() > 3600:
                    expired_calls.append(call_id)
            
            # Remove expired calls
            for call_id in expired_calls:
                if call_id in self.call_metrics:
                    del self.call_metrics[call_id]
            
            if expired_calls:
                self.logger.info(f"Cleaned up {len(expired_calls)} expired calls")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired calls: {e}")


# Global service instance
_call_orchestrator: Optional[CallOrchestrator] = None


def get_call_orchestrator() -> CallOrchestrator:
    """Get the global Call Orchestrator instance."""
    global _call_orchestrator
    if _call_orchestrator is None:
        _call_orchestrator = CallOrchestrator()
    return _call_orchestrator
