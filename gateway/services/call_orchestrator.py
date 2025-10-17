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
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum

from services.azure_speech_stt import get_speech_to_text_service, SpeechToTextService
from services.azure_speech_tts import get_text_to_speech_service, TextToSpeechService
from services.azure_openai_service import get_azure_openai_service, AzureOpenAIService, IntentType
from services.hybrid_nlp_service import get_hybrid_nlp_service, HybridNLPService
from services.bilingual_manager import get_bilingual_manager, LanguageCode
from services.audio_stream_handler import get_audio_stream_handler, AudioStreamHandler
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
    call_type: CallType
    state: CallState
    language: LanguageCode
    start_time: datetime
    last_activity: datetime
    audio_stream_handler: Optional[AudioStreamHandler] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
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
        
        # Active calls
        self.active_calls: Dict[str, CallContext] = {}
        self.call_metrics: Dict[str, CallMetrics] = {}
        
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
    async def start_call(self, call_id: str, call_type: CallType,
                        language: LanguageCode = LanguageCode.ENGLISH,
                        audio_stream_handler: Optional[AudioStreamHandler] = None,
                        call_metadata: Optional[Dict[str, Any]] = None) -> CallContext:
        """
        Start a new call session.
        
        Args:
            call_id: Unique identifier for the call
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
            
            if call_id in self.active_calls:
                raise CallOrchestrationError("call_already_active", f"Call {call_id} is already active")
            
            if len(self.active_calls) >= self.max_concurrent_calls:
                raise CallOrchestrationError("max_calls_exceeded", "Maximum concurrent calls exceeded")
            
            # Create call context
            call_context = CallContext(
                call_id=call_id,
                call_type=call_type,
                state=CallState.INITIALIZING,
                language=language,
                start_time=datetime.now(timezone.utc),
                last_activity=datetime.now(timezone.utc),
                audio_stream_handler=audio_stream_handler,
                call_metadata=call_metadata or {}
            )
            
            # Create call metrics
            call_metrics = CallMetrics(
                call_id=call_id,
                start_time=datetime.now(timezone.utc)
            )
            
            # Store call context and metrics
            self.active_calls[call_id] = call_context
            self.call_metrics[call_id] = call_metrics
            
            # Initialize audio stream handler
            if audio_stream_handler:
                await self._initialize_audio_stream(call_context)
            
            # Set up call timeout
            asyncio.create_task(self._monitor_call_timeout(call_id))
            
            # Update state
            call_context.state = CallState.CONNECTED
            call_context.last_activity = datetime.now(timezone.utc)
            
            # Update statistics
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
    
    async def _initialize_audio_stream(self, call_context: CallContext):
        """Initialize audio stream for the call."""
        try:
            if not call_context.audio_stream_handler:
                return
            
            # Register STT callback
            def stt_callback(call_id: str, text: str, detected_language: str):
                asyncio.create_task(self._handle_speech_input(call_id, text, detected_language))
            
            call_context.audio_stream_handler.register_stt_callback(stt_callback)
            
            # Register TTS callback
            def tts_callback(call_id: str, text: str) -> bytes:
                return self.tts_service.synthesize_speech(text, call_context.language.value, call_id).audio_data
            
            call_context.audio_stream_handler.register_tts_callback(tts_callback)
            
            self.logger.debug(f"Audio stream initialized for call {call_context.call_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize audio stream for call {call_context.call_id}: {e}")
    
    async def _handle_speech_input(self, call_id: str, text: str, detected_language: str):
        """Handle speech input from STT service."""
        try:
            if call_id not in self.active_calls:
                self.logger.warning(f"Received speech input for inactive call: {call_id}")
                return
            
            call_context = self.active_calls[call_id]
            
            # Update call state
            call_context.state = CallState.PROCESSING
            call_context.last_activity = datetime.now(timezone.utc)
            
            # Detect language
            detected_lang = LanguageCode.ENGLISH if detected_language.startswith("en") else LanguageCode.SPANISH
            
            # Check for language switch
            if detected_lang != call_context.language:
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
                "timestamp": datetime.now(timezone.utc),
                "intent": intent_result.intent.value if hasattr(intent_result.intent, 'value') else str(intent_result.intent),
                "confidence": intent_result.confidence,
                "language": language.value
            })
            
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
        """Generate and synthesize response."""
        try:
            start_time = time.time()
            
            # Generate response using OpenAI
            response_result = await self.openai_service.generate_response(
                user_input=call_context.conversation_history[-1]["content"],
                call_id=call_context.call_id,
                language=call_context.language,
                intent=call_context.current_intent,
                entities=call_context.entities
            )
            
            # Add response to conversation history
            call_context.conversation_history.append({
                "role": "assistant",
                "content": response_result.response_text,
                "timestamp": datetime.now(timezone.utc),
                "language": call_context.language.value
            })
            
            # Update call state
            call_context.state = CallState.SPEAKING
            call_context.last_activity = datetime.now(timezone.utc)
            
            # Synthesize and play response
            await self._synthesize_response(call_context, response_result.response_text)
            
            # Update metrics
            call_metrics = self.call_metrics[call_context.call_id]
            call_metrics.tts_processing_time += time.time() - start_time
            call_metrics.successful_interactions += 1
            
            # Update state to listening
            call_context.state = CallState.LISTENING
            
            # Trigger callbacks
            await self._trigger_callbacks("response_generated", call_context, response_result)
            
        except Exception as e:
            self.logger.error(f"Failed to generate response for call {call_context.call_id}: {e}")
            await self._handle_call_error(call_context.call_id, e)
    
    async def _synthesize_response(self, call_context: CallContext, response_text: str):
        """Synthesize and play response using TTS."""
        try:
            if not call_context.audio_stream_handler:
                self.logger.warning(f"No audio stream handler for call {call_context.call_id}")
                return
            
            # Synthesize speech
            synthesis_result = await self.tts_service.synthesize_speech(
                text=response_text,
                language=call_context.language.value,
                call_id=call_context.call_id
            )
            
            if synthesis_result.success:
                # Send audio to stream
                await call_context.audio_stream_handler.send_audio_from_tts(response_text)
                self.logger.debug(f"Response synthesized and sent for call {call_context.call_id}")
            else:
                self.logger.error(f"TTS synthesis failed for call {call_context.call_id}: {synthesis_result.error_message}")
                
        except Exception as e:
            self.logger.error(f"Failed to synthesize response for call {call_context.call_id}: {e}")
            raise
    
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
            call_context.last_activity = datetime.now(timezone.utc)
            
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
                time_since_activity = (datetime.now(timezone.utc) - call_context.last_activity).total_seconds()
                if time_since_activity > self.silence_timeout_seconds:
                    self.logger.warning(f"Call {call_id} timed out due to inactivity")
                    await self.end_call(call_id, "timeout")
                    break
                
                # Check for maximum call duration
                call_duration = (datetime.now(timezone.utc) - call_context.start_time).total_seconds()
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
            call_metrics = self.call_metrics[call_id]
            
            # Update call state
            call_context.state = CallState.ENDING
            
            # Stop audio stream
            if call_context.audio_stream_handler:
                await call_context.audio_stream_handler.stop_streaming()
            
            # Update metrics
            call_metrics.end_time = datetime.now(timezone.utc)
            call_metrics.total_duration_seconds = (call_metrics.end_time - call_metrics.start_time).total_seconds()
            
            if call_metrics.total_interactions > 0:
                call_metrics.average_response_time = (
                    call_metrics.stt_processing_time + 
                    call_metrics.nlp_processing_time + 
                    call_metrics.tts_processing_time
                ) / call_metrics.total_interactions
            
            # Update statistics
            self.orchestration_stats["active_calls"] -= 1
            self.orchestration_stats["completed_calls"] += 1
            
            if call_metrics.errors > 0:
                self.orchestration_stats["failed_calls"] += 1
            
            # Update average call duration
            total_duration = sum(m.total_duration_seconds for m in self.call_metrics.values() if m.end_time)
            completed_calls = sum(1 for m in self.call_metrics.values() if m.end_time)
            if completed_calls > 0:
                self.orchestration_stats["average_call_duration"] = total_duration / completed_calls
            
            # Trigger callbacks
            await self._trigger_callbacks("call_ended", call_context, {"reason": reason})
            
            # Clean up
            del self.active_calls[call_id]
            
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
            current_time = datetime.now(timezone.utc)
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
