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
from services.nlp_service import get_nlp_service, NLPService, IntentType, ExtractedEntities
from services.response_service import get_response_templates
# Use TYPE_CHECKING for forward references to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.audio_stream_handler import get_audio_stream_handler, AudioStreamHandler
    from services.azure_communication_service import get_azure_communication_service
from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ValidationError,
    ExternalServiceUnavailableError,
    CallOrchestrationError
)
from models.enums import LanguageCode
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


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
    audio_stream_handler: Optional["AudioStreamHandler"] = None
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
    total_interactions: int = 0
    errors: int = 0


class CallOrchestrator:
    """
    Orchestrates the complete call flow pipeline.
    
    Coordinates STT, NLP/OpenAI, and TTS services to provide
    seamless conversational AI experience.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        
        # Service dependencies (lazy imports to avoid circular dependencies)
        self.stt_service = get_speech_to_text_service()
        self.tts_service = get_text_to_speech_service()
        self.nlp_service = get_nlp_service()
        self.response_templates = get_response_templates()
        # Import here to avoid circular import with audio_stream_handler
        from services.audio_stream_handler import get_audio_stream_handler
        self.audio_stream_handler = get_audio_stream_handler()
        
        # Language preference tracking (moved from bilingual_manager)
        self.language_preferences: Dict[str, LanguageCode] = {}
        
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
            "average_call_duration": 0.0
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
                        call_type: Union[str, CallType] = 'inbound',
                        language: LanguageCode = LanguageCode.ENGLISH,
                        audio_stream_handler: Optional["AudioStreamHandler"] = None,
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
            
            if not clinic_id:
                raise ValidationError("clinic_id", clinic_id, "Clinic ID cannot be empty")
            
            # Issue 117: Verify clinic exists in database before starting call
            try:
                from services.database import get_async_db_session
                from sqlalchemy import select
                async with get_async_db_session() as db:
                    from models.models import Clinic
                    clinic_result = await db.execute(select(Clinic).where(Clinic.clinic_id == clinic_id))
                    clinic = clinic_result.scalar_one_or_none()
                    if not clinic:
                        raise ValidationError("clinic_id", clinic_id, f"Clinic {clinic_id} does not exist")
            except ValidationError:
                raise
            except Exception as clinic_error:
                self.logger.warning(f"Failed to verify clinic {clinic_id} exists: {clinic_error}")
                # Continue - clinic verification failure shouldn't stop the call
            
            # Convert call_type string to CallType enum if needed
            if isinstance(call_type, str):
                try:
                    call_type = CallType(call_type)
                except ValueError:
                    # Default to INBOUND if invalid string
                    call_type = CallType.INBOUND
                    self.logger.warning(
                        f"Invalid call_type '{call_type}', defaulting to INBOUND",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={"call_id": call_id, "invalid_call_type": str(call_type)}
                    )
            
            # Enforce admission control before STT/TTS initialization
            # This will queue the call if capacity is full
            from services.admission_controller import get_admission_controller
            admission_controller = get_admission_controller()
            admission_result = await admission_controller.check_admission(call_id, clinic_id, timeout_seconds=None)
            
            # Track if admission was granted (for cleanup on error)
            admission_granted = False
            
            if not admission_result.admitted:
                if admission_result.reason == "queue_timeout":
                    self.logger.warning(
                        f"Call {call_id} timed out in queue for clinic {clinic_id}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={
                            'call_id': call_id,
                            'clinic_id': clinic_id,
                            'current_calls': admission_result.current_calls,
                            'max_calls': admission_result.max_calls,
                            'queue_position': admission_result.queue_position,
                            'wait_time_seconds': admission_result.wait_time_seconds
                        }
                    )
                    raise CallOrchestrationError(
                        "queue_timeout",
                        f"Call {call_id} timed out in queue for clinic {clinic_id}"
                    )
                elif admission_result.reason == "cancelled":
                    self.logger.info(
                        f"Call {call_id} was cancelled while in queue for clinic {clinic_id}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={
                            'call_id': call_id,
                            'clinic_id': clinic_id
                        }
                    )
                    raise CallOrchestrationError(
                        "call_cancelled",
                        f"Call {call_id} was cancelled"
                    )
                else:
                    self.logger.warning(
                        f"Admission rejected for call {call_id} - clinic {clinic_id}: {admission_result.reason}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={
                            'call_id': call_id,
                            'clinic_id': clinic_id,
                            'current_calls': admission_result.current_calls,
                            'max_calls': admission_result.max_calls,
                            'reason': admission_result.reason
                        }
                    )
                    raise CallOrchestrationError(
                        "admission_rejected",
                        f"Clinic {clinic_id} admission rejected: {admission_result.reason}"
                    )
            else:
                # Admission was granted - semaphore is now held
                admission_granted = True
            
            # Log if call was admitted from queue
            if admission_result.reason == "admitted_from_queue":
                self.logger.info(
                    f"Call {call_id} admitted from queue for clinic {clinic_id} (position {admission_result.queue_position})",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={
                        'call_id': call_id,
                        'clinic_id': clinic_id,
                        'queue_position': admission_result.queue_position
                    }
                )
            
            # Issue 109: Check for duplicate call_connection_id in addition to call_id
            # Issue 120: Handle concurrent start attempts with proper locking
            # Issue 2.4: Check limit and reserve slot atomically within the same lock
            async with self._calls_lock:
                # Issue 109: Check if call_id already exists
                if call_id in self.active_calls:
                    # Remove from queue if queued and release admission
                    await admission_controller.remove_from_queue(call_id)
                    await admission_controller.release_admission(clinic_id, call_id=call_id)
                    self.logger.warning(
                        f"Call {call_id} already exists",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={"call_id": call_id}
                    )
                    return self.active_calls[call_id]
                
                # Issue 109: Check if acs_call_id (call_connection_id) is already associated with another call
                acs_call_id = None
                if call_metadata and 'acs_call_id' in call_metadata:
                    acs_call_id = call_metadata.get('acs_call_id')
                    # Check if any existing call has the same acs_call_id
                    for existing_call_id, existing_context in self.active_calls.items():
                        existing_metadata = existing_context.metadata or {}
                        # Check both metadata and call_metadata for acs_call_id (for compatibility)
                        existing_acs_id = existing_metadata.get('acs_call_id') or existing_context.call_metadata.get('acs_call_id')
                        if existing_acs_id == acs_call_id:
                            # Remove from queue if queued and release admission
                            await admission_controller.remove_from_queue(call_id)
                            await admission_controller.release_admission(clinic_id, call_id=call_id)
                            self.logger.warning(
                                f"ACS call ID {acs_call_id} already associated with call {existing_call_id}",
                                LogCategory.CALL_ORCHESTRATION,
                                extra_data={"call_id": call_id, "acs_call_id": acs_call_id, "existing_call_id": existing_call_id}
                            )
                            return existing_context
                
                # Issue 2.4: Handle maximum concurrent calls race condition
                # Check limit atomically within the same lock
                if len(self.active_calls) >= self.max_concurrent_calls:
                    # Remove from queue if queued and release admission
                    await admission_controller.remove_from_queue(call_id)
                    await admission_controller.release_admission(clinic_id, call_id=call_id)
                    raise CallOrchestrationError("max_calls_exceeded", "Maximum concurrent calls exceeded")
            
            # Create call context (outside lock to avoid holding lock during creation)
            # Capture timestamp once
            current_time = datetime.now(AST)
            
            # Issue 112: Store ACS call ID in CallContext metadata
            call_metadata_dict = call_metadata or {}
            if acs_call_id:
                call_metadata_dict['acs_call_id'] = acs_call_id
            
            call_context = CallContext(
                call_id=call_id,
                caller_phone=caller_phone,
                clinic_id=clinic_id,
                call_type=call_type,
                state=CallState.INITIALIZING,
                language=language,
                start_time=current_time,
                last_activity=current_time,
                audio_stream_handler=audio_stream_handler,
                metadata=call_metadata_dict  # Issue 112: Store metadata including acs_call_id
            )
            
            # Create call metrics
            call_metrics = CallMetrics(
                call_id=call_id,
                start_time=current_time
            )
            
            # Initialize CallFlowService (creates CallFlowContext and database Call record)
            from services.call_flow_service import CallFlowService
            from services.database import get_async_db_session
            from models.call_flow_models import CallFlowContext
            call_flow_context = None
            try:
                async with get_async_db_session() as db:
                    call_flow_service = CallFlowService(db)
                    flow_response = await call_flow_service.initialize_call(
                        call_sid=call_id,
                        caller_phone=caller_phone,
                        clinic_id=clinic_id
                    )
                    # Get the created CallFlowContext
                    from services.call_flow_service import get_call
                    call_flow_context = await get_call(call_id)
                    self.logger.info(
                        f"CallFlowService initialized for call {call_id}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={"call_id": call_id, "clinic_id": clinic_id}
                    )
            except Exception as flow_error:
                self.logger.error(
                    f"Failed to initialize CallFlowService for call {call_id}: {flow_error}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=flow_error,
                    extra_data={"call_id": call_id}
                )
                # Create minimal CallFlowContext to allow call to proceed
                from models.call_flow_models import CallFlowState
                call_flow_context = CallFlowContext(
                    call_sid=call_id,
                    current_state=CallFlowState.GET_INTENT,
                    clinic_id=clinic_id
                )
                from services.call_flow_service import store_call
                await store_call(call_id, call_flow_context)
            
            # Store reference to CallFlowContext in CallContext.metadata for easy access
            if call_flow_context:
                call_metadata_dict['call_flow_context'] = call_flow_context
                call_metadata_dict['call_flow_state'] = call_flow_context.current_state.value if hasattr(call_flow_context.current_state, 'value') else str(call_flow_context.current_state)
            
            # Register call in ACS service (store ACS metadata)
            if acs_call_id:
                call_metadata_dict['acs_call_id'] = acs_call_id
                call_metadata_dict['acs_status'] = "incoming"
                call_metadata_dict['websocket_connected'] = False
                call_metadata_dict['audio_stream_active'] = False
            
            # Issue 2.4: Store call context and metrics atomically after creation
            # This ensures the count check and increment happen within the same lock
            async with self._calls_lock:
                # Re-check limit before adding (defense in depth)
                if len(self.active_calls) >= self.max_concurrent_calls:
                    # Remove from queue if queued and release admission
                    await admission_controller.remove_from_queue(call_id)
                    await admission_controller.release_admission(clinic_id, call_id=call_id)
                    raise CallOrchestrationError("max_calls_exceeded", "Maximum concurrent calls exceeded")
                
                # Add call to active_calls atomically
                self.active_calls[call_id] = call_context
                self.call_metrics[call_id] = call_metrics
            
            # Issue 6.2: Initialize audio stream handler with error handling and verify connection
            try:
                if audio_stream_handler:
                    connection_id = await self._initialize_audio_stream(call_context)
                    # Issue 6.2: Verify that audio stream handler connection is established
                    if not connection_id:
                        self.logger.warning(
                            f"Audio stream handler connection returned None for call {call_id}",
                            LogCategory.CALL_ORCHESTRATION,
                            extra_data={"call_id": call_id}
                        )
                        # Continue without audio if connection fails - call can still proceed
                    else:
                        # Issue 171: Store connection_id in metadata for later use
                        call_context.metadata = call_context.metadata or {}
                        call_context.metadata['connection_id'] = connection_id
            except Exception as audio_error:
                # Issue 127: Handle audio stream handler initialization failures
                self.logger.error(
                    f"Failed to initialize audio stream handler for call {call_id}: {audio_error}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=audio_error,
                    extra_data={"call_id": call_id}
                )
                # Issue 127: Clean up on failure
                async with self._calls_lock:
                    if call_id in self.active_calls:
                        del self.active_calls[call_id]
                    if call_id in self.call_metrics:
                        del self.call_metrics[call_id]
                
                # Release admission if it was granted
                if admission_granted:
                    try:
                        await admission_controller.remove_from_queue(call_id)
                        await admission_controller.release_admission(clinic_id, call_id=call_id)
                    except Exception as cleanup_error:
                        self.logger.error(
                            f"Failed to release admission during audio init cleanup: {cleanup_error}",
                            LogCategory.CALL_ORCHESTRATION,
                            exception=cleanup_error
                        )
                
                raise CallOrchestrationError("audio_init_failed", f"Failed to initialize audio stream: {audio_error}")
            
            # Issue 140: Handle timeout task creation failures
            try:
                timeout_task = asyncio.create_task(self._monitor_call_timeout(call_id))
                call_context.metadata['timeout_task'] = timeout_task
            except Exception as timeout_error:
                # Issue 140: Handle timeout task creation failures
                self.logger.error(f"Failed to create timeout task for call {call_id}: {timeout_error}")
                # Clean up on failure
                async with self._calls_lock:
                    if call_id in self.active_calls:
                        del self.active_calls[call_id]
                    if call_id in self.call_metrics:
                        del self.call_metrics[call_id]
                
                # Release admission if it was granted
                if admission_granted:
                    try:
                        await admission_controller.remove_from_queue(call_id)
                        await admission_controller.release_admission(clinic_id, call_id=call_id)
                    except Exception as cleanup_error:
                        self.logger.error(
                            f"Failed to release admission during timeout task cleanup: {cleanup_error}",
                            LogCategory.CALL_ORCHESTRATION,
                            exception=cleanup_error
                        )
                
                raise CallOrchestrationError("timeout_task_failed", f"Failed to create timeout task: {timeout_error}")
            
            # Update state
            call_context.state = CallState.CONNECTED
            call_context.last_activity = datetime.now(AST)
            
            # Issue 150: Handle statistics update failures
            try:
                # Update statistics (with lock)
                async with self._stats_lock:
                    self.orchestration_stats["total_calls"] += 1
                    self.orchestration_stats["active_calls"] += 1
            except Exception as stats_error:
                # Issue 150: Handle statistics update failures gracefully
                self.logger.warning(f"Failed to update statistics for call {call_id}: {stats_error}")
                # Continue - statistics failure shouldn't stop the call
            
            
            # Get call_type value safely (handle both enum and string)
            call_type_value = call_type.value if isinstance(call_type, CallType) else str(call_type)
            
            self.logger.info(
                f"Call started: {call_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    "call_id": call_id,
                    "call_type": call_type_value,
                    "language": language.value,
                    "active_calls": len(self.active_calls)
                }
            )
            
            return call_context
            
        except Exception as e:
            # Clean up admission if it was granted but call failed to start
            # This prevents semaphore leaks when start_call() fails after admission
            if admission_granted:
                try:
                    await admission_controller.remove_from_queue(call_id)
                    await admission_controller.release_admission(clinic_id, call_id=call_id)
                    self.logger.info(
                        f"Released admission for failed call {call_id}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={"call_id": call_id, "clinic_id": clinic_id}
                    )
                except Exception as cleanup_error:
                    self.logger.error(
                        f"Failed to release admission during cleanup for call {call_id}: {cleanup_error}",
                        LogCategory.CALL_ORCHESTRATION,
                        exception=cleanup_error
                    )
            
            # Clean up active_calls if it was added
            async with self._calls_lock:
                if call_id in self.active_calls:
                    del self.active_calls[call_id]
                if call_id in self.call_metrics:
                    del self.call_metrics[call_id]
            
            self.logger.error(
                f"Failed to start call {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
            raise
    
    async def play_greeting(self, call_id: str):
        """Play greeting message to the caller."""
        try:
            async with self._calls_lock:
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
    
    async def _initialize_audio_stream(self, call_context: CallContext):
        """Initialize audio stream for the call."""
        try:
            if not call_context.audio_stream_handler:
                return
            
            # Register STT callback
            # Note: STT service calls callback with TranscriptionResult object, not tuple
            def stt_callback(transcription_result):
                # Extract fields from TranscriptionResult object
                text = transcription_result.text if hasattr(transcription_result, 'text') else ""
                detected_language = transcription_result.language if hasattr(transcription_result, 'language') else call_context.language.value
                # Issue 2: Add error handling for async task creation
                try:
                    task = asyncio.create_task(self._handle_speech_input(call_context.call_id, text, detected_language))
                    # Add done callback to handle errors
                    def task_done_callback(task):
                        try:
                            task.result()  # This will raise exception if task failed
                        except Exception as e:
                            self.logger.error(
                                f"Error in STT callback task for call {call_context.call_id}: {e}",
                                LogCategory.CALL_ORCHESTRATION,
                                exception=e,
                                extra_data={"call_id": call_context.call_id, "text": text}
                            )
                    task.add_done_callback(task_done_callback)
                except Exception as e:
                    self.logger.error(
                        f"Failed to create task for STT callback for call {call_context.call_id}: {e}",
                        LogCategory.CALL_ORCHESTRATION,
                        exception=e,
                        extra_data={"call_id": call_context.call_id, "text": text}
                    )
            
            call_context.audio_stream_handler.register_stt_callback(call_context.call_id, stt_callback)
            
            # Note: TTS callback registration removed - audio_stream_handler doesn't have register_tts_callback
            # TTS audio is sent directly via send_tts_audio() in _synthesize_response()
            
            self.logger.debug(f"Audio stream initialized for call {call_context.call_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize audio stream for call {call_context.call_id}: {e}")
    
    async def connect_audio_stream(self, call_id: str, connection_id: str) -> bool:
        """
        Connect audio stream for a call (called from WebSocket route).
        
        Args:
            call_id: ID of the call
            connection_id: Connection ID from audio stream handler
            
        Returns:
            True if connection succeeded
        """
        try:
            async with self._calls_lock:
                if call_id not in self.active_calls:
                    self.logger.warning(f"Call {call_id} not found for audio stream connection")
                    return False
                
                call_context = self.active_calls[call_id]
                
                # Store connection_id in metadata
                call_context.metadata = call_context.metadata or {}
                call_context.metadata['connection_id'] = connection_id
                
                # Initialize audio stream if not already done
                if call_context.audio_stream_handler:
                    await self._initialize_audio_stream(call_context)
                
                # Start STT recognition
                if self.stt_service:
                    try:
                        await self.stt_service.start_continuous_recognition(call_id)
                        self.logger.info(f"Started STT recognition for call {call_id}")
                    except Exception as stt_error:
                        self.logger.warning(
                            f"Failed to start STT recognition for call {call_id}: {stt_error}",
                            LogCategory.CALL_ORCHESTRATION,
                            exception=stt_error
                        )
                        # Continue - STT failure shouldn't stop the call
                
                return True
                
        except Exception as e:
            self.logger.error(
                f"Failed to connect audio stream for call {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
            return False
    
    async def handle_acs_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle ACS webhook events.
        
        Args:
            event_type: Type of ACS event
            payload: Event payload
            
        Returns:
            Event handling result
        """
        try:
            call_connection_id = payload.get('callConnectionId')
            if not call_connection_id:
                self.logger.warning("Missing callConnectionId in ACS event payload")
                return {"status": "ignored", "reason": "missing_call_connection_id"}
            
            # Get call_id from metadata
            call_id = None
            async with self._calls_lock:
                for cid, context in self.active_calls.items():
                    if context.metadata.get('acs_call_id') == call_connection_id:
                        call_id = cid
                        break
            
            if not call_id:
                self.logger.warning(f"No active call found for ACS call ID: {call_connection_id}")
                return {"status": "ignored", "reason": "call_not_found"}
            
            # Handle different event types
            if event_type == "CallConnectionStateChanged":
                new_state = payload.get("state")
                await self.update_call_metadata(call_id, 'acs_status', new_state.lower())
                if new_state == "Disconnected":
                    await self.end_call(call_id, "disconnected")
            elif event_type == "MediaStreamingStarted":
                await self.update_call_metadata(call_id, 'websocket_connected', True)
                await self.update_call_metadata(call_id, 'audio_stream_active', True)
            elif event_type == "MediaStreamingStopped":
                await self.update_call_metadata(call_id, 'websocket_connected', False)
                await self.update_call_metadata(call_id, 'audio_stream_active', False)
            else:
                self.logger.info(f"Unhandled ACS event type: {event_type}")
            
            return {"status": "processed", "call_id": call_id}
            
        except Exception as e:
            self.logger.error(
                f"Failed to handle ACS event: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
            return {"status": "error", "message": str(e)}
    
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
            
            # Issue 10: Classify intent using NLP service with error recovery
            try:
                intent_result = await self.nlp_service.classify_intent(
                    user_input=text,
                    call_id=call_context.call_id,
                    language=language
                )
            except Exception as nlp_error:
                # Issue 10: Fallback to cached responses or simple pattern matching
                self.logger.warning(
                    f"NLP classification failed for call {call_context.call_id}, using fallback: {nlp_error}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=nlp_error,
                    extra_data={"call_id": call_context.call_id, "text": text}
                )
                # Use fallback intent classification
                from services.nlp_service import IntentType
                from services.response_service import get_response_cache_service
                response_cache = get_response_cache_service()
                
                # Try to get cached response
                cached_response = await response_cache.get_cached_response(text, language.value)
                if cached_response:
                    intent_result = cached_response.get('intent_result')
                    if intent_result:
                        self.logger.info(f"Using cached intent result for call {call_context.call_id}")
                    else:
                        # Fallback to default intent
                        from services.nlp_service import IntentResult
                        intent_result = IntentResult(
                            intent=IntentType.GENERAL_INQUIRY,
                            confidence=0.3,
                            entities=[],
                            text=text
                        )
                else:
                    # Fallback to default intent
                    from services.nlp_service import IntentResult
                    intent_result = IntentResult(
                        intent=IntentType.GENERAL_INQUIRY,
                        confidence=0.3,
                        entities=[],
                        text=text
                    )
            
            # Update call context
            call_context.current_intent = intent_result.intent
            # Convert entities to list format if needed
            if isinstance(intent_result.entities, ExtractedEntities):
                entities_list = [{"type": k, "value": v} for k, v in intent_result.entities.__dict__.items() if v]
            else:
                entities_list = intent_result.entities if isinstance(intent_result.entities, list) else []
            call_context.entities = entities_list
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
            
            # Update metrics (with lock)
            async with self._calls_lock:
                if call_context.call_id not in self.call_metrics:
                    self.logger.warning(f"No metrics found for call {call_context.call_id}, creating default")
                    self.call_metrics[call_context.call_id] = CallMetrics(
                        call_id=call_context.call_id,
                        start_time=call_context.start_time or datetime.now(AST)
                    )
                call_metrics = self.call_metrics[call_context.call_id]
                call_metrics.total_interactions += 1
            
            # Route call based on intent: non-patient callers get outbound call to clinic
            is_non_patient = intent_result.intent in [
                IntentType.INSURANCE_INQUIRY,
                IntentType.PROVIDER_INQUIRY,
                IntentType.CLINIC_INQUIRY,
                IntentType.BILLING_INQUIRY
            ]
            
            if is_non_patient:
                # Non-patient caller: make outbound call to clinic and end current call
                await self._handle_non_patient_caller(call_context, intent_result.intent)
                return
            
            # Patient caller: continue with normal flow
            # Generate response
            await self._generate_response(call_context, intent_result)
            
        except Exception as e:
            self.logger.error(f"Failed to process user input for call {call_context.call_id}: {e}")
            await self._handle_call_error(call_context.call_id, e)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((Exception,))
    )
    async def _persist_call_flow_state(self, call_id: str, context):
        """
        Persist call flow state with retry logic and verification.
        
        Args:
            call_id: ID of the call
            context: CallFlowContext to persist
            
        Raises:
            Exception: If persistence fails after retries
        """
        from services.call_flow_service import store_call, get_call
        
        try:
            # Store previous state for rollback if needed
            previous_state = context.current_state
            
            # Persist state
            await store_call(call_id, context)
            
            # Verify persistence succeeded
            stored_context = await get_call(call_id)
            if stored_context is None:
                raise Exception(f"State persistence verification failed: stored context is None for call {call_id}")
            
            if hasattr(stored_context, 'current_state') and stored_context.current_state != context.current_state:
                raise Exception(
                    f"State persistence verification failed: state mismatch for call {call_id}. "
                    f"Expected {context.current_state}, got {stored_context.current_state}"
                )
            
            self.logger.debug(
                f"Successfully persisted and verified call flow state for call {call_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={"call_id": call_id, "state": str(context.current_state)}
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to persist call flow state for {call_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e,
                extra_data={"call_id": call_id}
            )
            raise
    
    async def _handle_non_patient_caller(self, call_context: CallContext, intent: IntentType) -> None:
        """
        Handle non-patient callers (physician, pharmacy, insurance) by making outbound call to clinic.
        
        Args:
            call_context: Call context
            intent: Intent type (INSURANCE_INQUIRY, PROVIDER_INQUIRY, CLINIC_INQUIRY, BILLING_INQUIRY)
        """
        try:
            # Map intent to caller type
            caller_type_map = {
                IntentType.INSURANCE_INQUIRY: "insurance",
                IntentType.PROVIDER_INQUIRY: "provider",
                IntentType.CLINIC_INQUIRY: "clinic",
                IntentType.BILLING_INQUIRY: "billing"
            }
            caller_type = caller_type_map.get(intent, "general")
            
            # Get clinic phone number from clinic_id
            from services.clinic_management import ClinicManagementService
            from services.database import get_async_db_session
            
            async with get_async_db_session() as db:
                clinic_service = ClinicManagementService(db)
                clinic = await clinic_service.get_clinic(call_context.clinic_id)
                
                if not clinic or not clinic.phone_number:
                    self.logger.error(
                        f"Failed to get clinic phone number for clinic_id: {call_context.clinic_id}, caller_type: {caller_type}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={"clinic_id": call_context.clinic_id, "caller_type": caller_type}
                    )
                    # Fallback: play message and end call
                    await self._synthesize_response(
                        call_context,
                        "I'm sorry, I'm unable to transfer your call at this time. Please call the clinic directly."
                    )
                    await self.end_call(call_context.call_id, "transfer_failed")
                    return
                
                clinic_phone = clinic.phone_number
                
                # Get ACS service and TTS service
                from services.azure_communication_service import get_azure_communication_service
                from services.azure_speech_tts import get_text_to_speech_service
                
                acs_service = get_azure_communication_service()
                tts_service = get_text_to_speech_service()
                
                # Generate message for outbound call
                message = f"Hello, this is a call transfer. A {caller_type} inquiry is being transferred to your clinic. Please hold."
                
                # Generate TTS audio
                audio_bytes = await tts_service.synthesize_speech(message, "en-US")
                
                if not audio_bytes:
                    self.logger.warning(
                        f"Failed to generate TTS audio for outbound call to clinic {clinic_phone}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={"clinic_id": call_context.clinic_id, "caller_type": caller_type}
                    )
                    # Continue without audio
                
                # Make outbound call to clinic
                call_result = await acs_service.make_outbound_call(
                    to_phone=clinic_phone,
                    audio_content=audio_bytes,
                    call_context={
                        'caller_type': caller_type,
                        'original_call_id': call_context.call_id,
                        'clinic_id': call_context.clinic_id,
                        'call_type': 'transfer'
                    }
                )
                
                if call_result.get('success'):
                    self.logger.info(
                        f"Outbound call made to clinic {clinic_phone} for {caller_type} inquiry",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={
                            "clinic_id": call_context.clinic_id,
                            "caller_type": caller_type,
                            "call_connection_id": call_result.get('call_connection_id')
                        }
                    )
                    # Play transfer message to caller
                    await self._synthesize_response(
                        call_context,
                        f"I'll connect you with our staff who can help with your {caller_type} inquiry. Please hold while I transfer you."
                    )
                    # End the current call after a short delay
                    await asyncio.sleep(2)
                    await self.end_call(call_context.call_id, "transferred")
                else:
                    self.logger.error(
                        f"Failed to make outbound call to clinic {clinic_phone}: {call_result.get('error_message')}",
                        LogCategory.CALL_ORCHESTRATION,
                        extra_data={
                            "clinic_id": call_context.clinic_id,
                            "caller_type": caller_type,
                            "error_code": call_result.get('error_code')
                        }
                    )
                    # Fallback: play message and end call
                    await self._synthesize_response(
                        call_context,
                        "I'm sorry, I'm unable to transfer your call at this time. Please call the clinic directly."
                    )
                    await self.end_call(call_context.call_id, "transfer_failed")
            
        except Exception as e:
            self.logger.error(
                f"Error handling non-patient caller: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e,
                extra_data={"clinic_id": call_context.clinic_id, "intent": intent.value if hasattr(intent, 'value') else str(intent)}
            )
            # Fallback: play message and end call
            try:
                await self._synthesize_response(
                    call_context,
                    "I'm sorry, I'm unable to transfer your call at this time. Please call the clinic directly."
                )
                await self.end_call(call_context.call_id, "transfer_error")
            except Exception as end_error:
                self.logger.error(
                    f"Failed to end call after transfer error: {end_error}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=end_error
                )
    
    async def _generate_response(self, call_context: CallContext, intent_result):
        """Generate and synthesize response based on intent. Always delegates to CallFlowService."""
        try:
            # Validate intent result
            if not intent_result or not hasattr(intent_result, 'intent') or not intent_result.intent:
                response_text = "I'm sorry, I'm having trouble understanding. Could you please repeat your request?"
            elif not call_context.conversation_history:
                response_text = "I'm sorry, I didn't catch that. Could you please repeat?"
            else:
                # Always delegate to CallFlowService for ALL intents
                from services.call_flow_service import CallFlowService
                from services.database import get_async_db_session
                
                async with get_async_db_session() as db:
                    flow_service = CallFlowService(db)
                    
                    # Extract entities from intent_result
                    entities_list = []
                    if intent_result.entities:
                        if isinstance(intent_result.entities, list):
                            entities_list = intent_result.entities
                        elif hasattr(intent_result.entities, '__dict__'):
                            entities_list = [{"type": k, "value": v} for k, v in intent_result.entities.__dict__.items() if v]
                    
                    # Pass entities to flow service - it handles ALL intents
                    flow_response = await flow_service.process_user_input(
                        call_context.call_id,
                        call_context.conversation_history[-1]['content'],
                        entities=entities_list if entities_list else None
                    )
                    
                    # Extract message from flow response
                    if hasattr(flow_response, 'message'):
                        response_text = flow_response.message
                    elif isinstance(flow_response, str):
                        response_text = flow_response
                    else:
                        response_text = str(flow_response)
                    
                    # Update call flow state in orchestrator context
                    if hasattr(flow_response, 'next_state'):
                        call_context.metadata = call_context.metadata or {}
                        call_context.metadata['call_flow_state'] = flow_response.next_state.value if hasattr(flow_response.next_state, 'value') else str(flow_response.next_state)
                        
                        # Update CallFlowContext reference in metadata if it exists
                        if 'call_flow_context' in call_context.metadata:
                            call_flow_context = call_context.metadata['call_flow_context']
                            previous_state = call_flow_context.current_state
                            call_flow_context.current_state = flow_response.next_state
                            try:
                                await self._persist_call_flow_state(call_context.call_id, call_flow_context)
                            except Exception as persist_error:
                                self.logger.error(
                                    f"Failed to persist CallFlowContext state for call {call_context.call_id}: {persist_error}",
                                    LogCategory.CALL_ORCHESTRATION,
                                    exception=persist_error,
                                    extra_data={"call_id": call_context.call_id}
                                )
                                call_flow_context.current_state = previous_state
            
            # Ensure response_text is not None
            if not response_text:
                response_text = "I'm sorry, I didn't understand that. Could you please repeat?"
            
            # Add response to conversation history
            call_context.conversation_history.append({
                "role": "assistant",
                "content": response_text,
                "timestamp": datetime.now(AST),
                "language": call_context.language.value,
                "intent": intent_result.intent.value if hasattr(intent_result, 'intent') and hasattr(intent_result.intent, 'value') else str(intent_result.intent) if hasattr(intent_result, 'intent') else None,
                "confidence": intent_result.confidence if hasattr(intent_result, 'confidence') else 0.0
            })
            
            # Update call state
            call_context.state = CallState.SPEAKING
            call_context.last_activity = datetime.now(AST)
            
            # Synthesize and play response
            await self._synthesize_response(call_context, response_text)
            
            # Update metrics (with lock)
            async with self._calls_lock:
                if call_context.call_id not in self.call_metrics:
                    self.call_metrics[call_context.call_id] = CallMetrics(
                        call_id=call_context.call_id,
                        start_time=call_context.start_time or datetime.now(AST)
                    )
            
            # Update state to listening
            call_context.state = CallState.LISTENING
            
        except Exception as e:
            self.logger.error(f"Failed to generate response for call {call_context.call_id}: {e}")
            await self._handle_call_error(call_context.call_id, e)
    
    async def _synthesize_response(self, call_context: CallContext, response_text: str):
        """Synthesize and play response using TTS with retry logic."""
        MAX_RETRIES = 2
        
        try:
            # Check TTS service availability
            if not self.tts_service or not hasattr(self.tts_service, 'synthesize_speech'):
                self.logger.error(f"TTS service not available for call {call_context.call_id}")
                await self._play_text_source_fallback(call_context, response_text)
                return
            
            # Synthesize speech
            synthesis_result = await self.tts_service.synthesize_speech(
                text=response_text,
                language=call_context.language.value,
                call_id=call_context.call_id
            )
            
            if not synthesis_result.success:
                self.logger.error(
                    f"TTS synthesis failed for call {call_context.call_id}: {synthesis_result.error_message}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_context.call_id, "error": synthesis_result.error_message}
                )
                await self._play_text_source_fallback(call_context, response_text)
                return
            
            # Try playback with retry logic (max 2 attempts)
            for attempt in range(MAX_RETRIES):
                try:
                    # Try WebSocket audio streaming first
                    if call_context.audio_stream_handler:
                        success = await call_context.audio_stream_handler.send_tts_audio(
                            call_context.call_id, 
                            synthesis_result.audio_data
                        )
                        if success:
                            return
                    
                    # Fallback: Use ACS Play API
                    from services.azure_communication_service import get_azure_communication_service
                    acs_service = get_azure_communication_service()
                    acs_call_id = await acs_service._get_acs_call_id(call_context.call_id)
                    
                    if acs_call_id:
                        success = await acs_service.play_audio_to_call(
                            acs_call_id,
                            synthesis_result.audio_data
                        )
                        if success:
                            return
                    
                    # Wait before retry
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(1)
                    
                except Exception as e:
                    self.logger.error(f"TTS playback attempt {attempt + 1} failed: {e}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(1)
            
            # All retries exhausted - fallback to TextSource
            self.logger.error(f"Failed to play TTS audio after {MAX_RETRIES} attempts")
            await self._play_text_source_fallback(call_context, response_text)
                
        except Exception as e:
            self.logger.error(f"Failed to synthesize response for call {call_context.call_id}: {e}", exc_info=True)
            await self._play_text_source_fallback(call_context, response_text)
    
    async def _play_text_source_fallback(self, call_context: CallContext, text: str):
        """Fallback to ACS TextSource when TTS synthesis fails."""
        try:
            from services.azure_communication_service import get_azure_communication_service
            acs_service = get_azure_communication_service()
            acs_call_id = await acs_service._get_acs_call_id(call_context.call_id)
            
            if acs_call_id:
                # Use ACS TextSource for immediate playback
                success = await acs_service.play_scripted_text(
                    acs_call_id, 
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
    
    async def _handle_language_switch(self, call_context: CallContext, new_language: LanguageCode):
        """Handle language switch during the call."""
        try:
            old_language = call_context.language
            call_context.language = new_language
            
            # Update language preference
            self.set_language_preference(call_context.call_id, new_language)
            
            # Note: TTS/STT services handle language automatically via AutoDetectSourceLanguageConfig
            # Language is passed per-request to synthesize_speech() and is detected automatically in STT
            # No explicit language update methods exist or are needed
            
            # Update metrics (with lock)
            async with self._calls_lock:
                if call_context.call_id not in self.call_metrics:
                    self.logger.warning(f"No metrics found for call {call_context.call_id}, creating default")
                    self.call_metrics[call_context.call_id] = CallMetrics(
                        call_id=call_context.call_id,
                        start_time=call_context.start_time or datetime.now(AST)
                    )
            
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
            
            async with self._calls_lock:
                if call_id not in self.active_calls:
                    return
                call_context = self.active_calls[call_id]
                call_context.error_count += 1
                
                # Issue 65: Check error type and handle recoverable vs non-recoverable errors differently
                error_type = type(error).__name__
                is_recoverable = error_type in [
                    'ConnectionError', 'TimeoutError', 'ExternalServiceUnavailableError',
                    'NetworkError', 'TemporaryError'
                ]
                
                if not is_recoverable:
                    # Non-recoverable errors (e.g., ValidationError, ValueError) - don't try to recover
                    call_context.state = CallState.ERROR
                    self.logger.error(f"Non-recoverable error for call {call_id}: {error}")
                    # Don't attempt recovery for non-recoverable errors
                    return
                
                # Update metrics
                if call_id not in self.call_metrics:
                    self.logger.warning(f"No metrics found for call {call_id}, creating default")
                    self.call_metrics[call_id] = CallMetrics(
                        call_id=call_id,
                        start_time=call_context.start_time or datetime.now(AST)
                    )
                call_metrics = self.call_metrics[call_id]
                call_metrics.errors += 1
            
            # Check if we should end the call due to too many errors
            if call_context.error_count >= call_context.max_errors:
                self.logger.error(f"Too many errors for call {call_id}, ending call")
                await self.end_call(call_id, "excessive_errors")
                return
            
            # Update call state
            call_context.state = CallState.ERROR
            
            # Try to recover
            await self._recover_from_error(call_context)
            
        except Exception as e:
            self.logger.error(f"Failed to handle call error for call {call_id}: {e}")
    
    async def _recover_from_error(self, call_context: CallContext):
        """Attempt to recover from an error."""
        try:
            # Issue 64: Reset call state from ERROR to a valid state after recovery
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
            
            while iteration < max_iterations:
                iteration += 1
                # Issue 86: Access call context values while holding lock to prevent race conditions
                async with self._calls_lock:
                    if call_id not in self.active_calls:
                        break
                    call_context = self.active_calls[call_id]
                    # Capture values while holding lock
                    last_activity = call_context.last_activity
                    start_time = call_context.start_time
                    conversation_history_len = len(call_context.conversation_history)
                
                # Issue 167: Check call state before ending the call
                async with self._calls_lock:
                    if call_id not in self.active_calls:
                        break
                    call_context = self.active_calls[call_id]
                    # Issue 167: Don't end call if it's already ending or ended
                    if call_context.state in [CallState.ENDING, CallState.ENDED, CallState.ERROR]:
                        break
                
                # Check for timeout
                time_since_activity = (datetime.now(AST) - last_activity).total_seconds()
                if time_since_activity > self.silence_timeout_seconds:
                    self.logger.warning(f"Call {call_id} timed out due to inactivity")
                    # Issue 200: Update call metrics when ending calls due to timeout
                    async with self._calls_lock:
                        if call_id in self.call_metrics:
                            self.call_metrics[call_id].errors += 1
                    await self.end_call(call_id, "timeout")
                    break
                
                # Check for maximum call duration
                call_duration = (datetime.now(AST) - start_time).total_seconds()
                if call_duration > (self.call_timeout_minutes * 60):
                    self.logger.warning(f"Call {call_id} exceeded maximum duration")
                    # Issue 200: Update call metrics when ending calls due to max duration
                    async with self._calls_lock:
                        if call_id in self.call_metrics:
                            self.call_metrics[call_id].errors += 1
                    await self.end_call(call_id, "max_duration")
                    break
                
                # Check for maximum conversation turns
                if conversation_history_len >= self.max_conversation_turns:
                    self.logger.warning(f"Call {call_id} exceeded maximum conversation turns")
                    # Issue 200: Update call metrics when ending calls due to max turns
                    async with self._calls_lock:
                        if call_id in self.call_metrics:
                            self.call_metrics[call_id].errors += 1
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
            
            # Issue 4.3: Cancel timeout monitoring task with proper state check
            timeout_task = call_context.metadata.get('timeout_task')
            if timeout_task:
                # Check task state before cancelling
                if not timeout_task.done():
                    timeout_task.cancel()
                    try:
                        await timeout_task
                    except asyncio.CancelledError:
                        # Task was successfully cancelled
                        self.logger.debug(f"Timeout task cancelled for call {call_id}")
                    except Exception as cancel_error:
                        self.logger.warning(
                            f"Error cancelling timeout task for call {call_id}: {cancel_error}",
                            LogCategory.CALL_ORCHESTRATION,
                            exception=cancel_error,
                            extra_data={"call_id": call_id}
                        )
                else:
                    # Task already done or cancelled
                    self.logger.debug(f"Timeout task already done for call {call_id}")
            
            # Update call state
            call_context.state = CallState.ENDING
            
            # Hang up call via ACS API (before cleanup)
            acs_call_id = call_context.metadata.get('acs_call_id')
            if acs_call_id:
                try:
                    from services.azure_communication_service import get_azure_communication_service
                    acs_service = get_azure_communication_service()
                    success = await acs_service.hangup_call(acs_call_id)
                    if not success:
                        self.logger.warning(
                            f"ACS hangup failed for call {call_id}",
                            LogCategory.CALL_ORCHESTRATION,
                            extra_data={"call_id": call_id, "acs_call_id": acs_call_id}
                        )
                except Exception as acs_error:
                    self.logger.warning(
                        f"Failed to hangup ACS call {acs_call_id}: {acs_error}",
                        LogCategory.CALL_ORCHESTRATION,
                        exception=acs_error,
                        extra_data={"call_id": call_id, "acs_call_id": acs_call_id}
                    )
            
            # Update database call record
            end_time = datetime.now(AST)
            try:
                from services.database import get_async_db_session
                from sqlalchemy import select
                from models.models import Call
                async with get_async_db_session() as db:
                    call_result = await db.execute(
                        select(Call).where(Call.call_id == call_id).with_for_update()
                    )
                    call_record = call_result.scalar_one_or_none()
                    if call_record:
                        call_record.status = "completed"
                        call_record.ended_at = end_time
                        try:
                            await db.commit()
                        except Exception as commit_error:
                            await db.rollback()
                            self.logger.error(f"Failed to commit call record update: {commit_error}")
                    else:
                        self.logger.warning(f"Call record not found for update: {call_id}")
            except Exception as db_error:
                self.logger.error(
                    f"Failed to update call record for {call_id}: {db_error}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=db_error
                )
            
            # Decrement clinic capacity and process queue
            if call_context.clinic_id:
                try:
                    from services.admission_controller import get_admission_controller
                    admission_controller = get_admission_controller()
                    # Remove from queue if queued (in case caller hung up before admission)
                    await admission_controller.remove_from_queue(call_id)
                    # Release admission (this will process the next queued call)
                    await admission_controller.release_admission(call_context.clinic_id, call_id=call_id)
                except Exception as capacity_error:
                    self.logger.error(
                        f"Failed to release admission for clinic {call_context.clinic_id}: {capacity_error}",
                        LogCategory.CALL_ORCHESTRATION,
                        exception=capacity_error
                    )
            
            # Note: Provider capacity release removed - capacity is never updated, so releasing does nothing
            # If provider capacity management is needed in the future, add it to provider_management.py with proper database persistence
            
            # Issue 4.1: Comprehensive resource cleanup with error tracking
            cleanup_errors = []
            cleanup_tasks = []
            
            # 1. Cancel timeout task
            timeout_task = call_context.metadata.get('timeout_task')
            if timeout_task and not timeout_task.done():
                async def cancel_timeout_task():
                    try:
                        timeout_task.cancel()
                        try:
                            await timeout_task
                        except asyncio.CancelledError:
                            pass
                    except Exception as e:
                        raise Exception(f"Failed to cancel timeout task: {e}")
                cleanup_tasks.append(('timeout_task', cancel_timeout_task()))
            
            # 2. Stop STT recognition
            if self.stt_service:
                async def stop_stt():
                    try:
                        await self.stt_service.stop_continuous_recognition(call_id)
                    except Exception as e:
                        raise Exception(f"Failed to stop STT recognition: {e}")
                cleanup_tasks.append(('stt', stop_stt()))
            
            # 3. Stop TTS synthesis
            if self.tts_service:
                async def cleanup_tts():
                    try:
                        # TTS service should clean up sessions automatically
                        self.logger.debug(f"TTS cleanup for call {call_id}")
                    except Exception as e:
                        raise Exception(f"Failed to cleanup TTS: {e}")
                cleanup_tasks.append(('tts', cleanup_tts()))
            
            # 4. Disconnect audio stream
            if call_context.audio_stream_handler:
                connection_id = call_context.metadata.get('connection_id')
                if connection_id:
                    async def disconnect_audio():
                        try:
                            await call_context.audio_stream_handler.disconnect_audio_stream(connection_id)
                        except Exception as e:
                            raise Exception(f"Failed to disconnect audio stream: {e}")
                    cleanup_tasks.append(('audio_stream', disconnect_audio()))
            
            # 5. Release admission (already done above, but keep for cleanup tracking)
            # Note: Admission is already released above, this is just for cleanup tracking
            
            # 6. Remove from call store
            async def remove_from_store():
                try:
                    from services.call_flow_service import remove_call
                    await remove_call(call_id)
                except Exception as e:
                    raise Exception(f"Failed to remove call from call store: {e}")
            cleanup_tasks.append(('call_store', remove_from_store()))
            
            # 7. End NLP conversation
            async def end_nlp_conversation():
                try:
                    await self.nlp_service.end_conversation(call_id)
                except Exception as e:
                    raise Exception(f"Failed to end NLP conversation: {e}")
            cleanup_tasks.append(('nlp', end_nlp_conversation()))
            
            # Execute all cleanup tasks
            for task_name, task in cleanup_tasks:
                try:
                    await task
                except Exception as e:
                    cleanup_errors.append((task_name, str(e)))
                    self.logger.warning(
                        f"Cleanup task {task_name} failed for call {call_id}: {e}",
                        LogCategory.CALL_ORCHESTRATION,
                        exception=e,
                        extra_data={"call_id": call_id, "task_name": task_name}
                    )
            
            # Verify cleanup
            if cleanup_errors:
                self.logger.error(
                    f"Some cleanup tasks failed for call {call_id}: {cleanup_errors}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_id, "cleanup_errors": cleanup_errors}
                )
            else:
                self.logger.info(
                    f"All cleanup tasks completed successfully for call {call_id}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={"call_id": call_id}
                )
            
            # Update metrics
            call_metrics.end_time = datetime.now(AST)
            call_metrics.total_duration_seconds = (call_metrics.end_time - call_metrics.start_time).total_seconds()
            
            # Update statistics
            async with self._stats_lock:
                self.orchestration_stats["active_calls"] -= 1
                self.orchestration_stats["completed_calls"] += 1
                
                if call_metrics.errors > 0:
                    self.orchestration_stats["failed_calls"] += 1
            
            # Calculate average call duration before cleanup (to avoid iterating over modified dict)
            async with self._calls_lock:
                # Create a copy of metrics to avoid iteration issues
                metrics_copy = dict(self.call_metrics)
            
            # Calculate outside lock
            total_duration = sum(m.total_duration_seconds for m in metrics_copy.values() if m.end_time)
            completed_calls = sum(1 for m in metrics_copy.values() if m.end_time)
            avg_duration = total_duration / completed_calls if completed_calls > 0 else 0.0
            
            # Clean up with lock
            async with self._calls_lock:
                if call_id in self.active_calls:
                    del self.active_calls[call_id]
                if call_id in self.call_metrics:
                    del self.call_metrics[call_id]

            # Update stats separately
            async with self._stats_lock:
                self.orchestration_stats["average_call_duration"] = avg_duration
            
            # Note: NLP service end_conversation() already called in cleanup_tasks above
            # azure_openai_service doesn't exist - NLP service handles OpenAI internally
            
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
    
    async def get_call_context(self, call_id: str) -> Optional[CallContext]:
        """Get call context by ID."""
        async with self._calls_lock:
            return self.active_calls.get(call_id)
    
    async def update_call_metadata(self, call_id: str, key: str, value: Any) -> bool:
        """
        Atomically update call context metadata with lock protection.
        
        Args:
            call_id: ID of the call
            key: Metadata key to update
            value: Value to set
            
        Returns:
            True if metadata was updated, False if call context not found
        """
        async with self._calls_lock:
            call_context = self.active_calls.get(call_id)
            if call_context:
                # Initialize metadata dicts if needed
                if call_context.metadata is None:
                    call_context.metadata = {}
                if call_context.call_metadata is None:
                    call_context.call_metadata = {}
                # Update both for compatibility
                call_context.metadata[key] = value
                call_context.call_metadata[key] = value
                return True
            return False
    
    async def get_call_metadata(self, call_id: str) -> Dict[str, Any]:
        """
        Atomically get call context metadata with lock protection.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Merged metadata dictionary (call_metadata + metadata, with metadata taking precedence)
        """
        async with self._calls_lock:
            call_context = self.active_calls.get(call_id)
            if call_context:
                metadata = call_context.metadata or {}
                call_metadata = call_context.call_metadata or {}
                # Merge both, with metadata taking precedence
                return {**call_metadata, **metadata}
            return {}
    
    
    # Bilingual manager methods (moved from bilingual_manager)
    def set_language_preference(self, call_id: str, language: LanguageCode) -> bool:
        """
        Set the language preference for a conversation.
        
        Args:
            call_id: ID of the call
            language: Preferred language
            
        Returns:
            True if preference was set successfully
        """
        try:
            self.language_preferences[call_id] = language
            
            self.logger.info(
                f"Language preference set for call {call_id}",
                LogCategory.LANGUAGE_DETECTION,
                extra_data={
                    "call_id": call_id,
                    "language": language.value
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to set language preference for call {call_id}: {e}",
                LogCategory.LANGUAGE_DETECTION,
                exception=e
            )
            return False
    

# Global service instance
_call_orchestrator: Optional[CallOrchestrator] = None


def get_call_orchestrator() -> CallOrchestrator:
    """Get the global Call Orchestrator instance."""
    global _call_orchestrator
    if _call_orchestrator is None:
        _call_orchestrator = CallOrchestrator()
    return _call_orchestrator
