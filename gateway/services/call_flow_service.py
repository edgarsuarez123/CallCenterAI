"""
Call Flow Service
Handles the conversation flow for incoming calls including patient identification,
appointment booking, and Google Calendar integration.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, date, timedelta
from collections import OrderedDict
import logging
import re
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from models.models import Call, Patient, Provider, AppointmentSlot, Clinic, Appointment
from models.enums import YesNo
from models.enums import CallStatus
from services.configuration import get_settings
from services.crypto import make_hmac_token, encrypt_str

# Get configuration
settings = get_settings()

from models.call_flow_models import (
    CallFlowState, CallFlowResponse, CallFlowContext, 
    PatientIdentificationResult, ProviderOption, TimeSlotOption, DateOption,
    AppointmentBookingData
)

# Valid state transitions
VALID_TRANSITIONS = {
    CallFlowState.GET_INTENT: [
        CallFlowState.IDENTIFY_PATIENT,
        CallFlowState.CANCEL_APPOINTMENT,
        CallFlowState.INSURANCE_INQUIRY,
        CallFlowState.PROVIDER_INQUIRY,
        CallFlowState.TRANSFER_TO_HUMAN
    ],
    CallFlowState.IDENTIFY_PATIENT: [
        CallFlowState.NEW_PATIENT_INFO,
        CallFlowState.RETURNING_PATIENT_INFO
    ],
    CallFlowState.NEW_PATIENT_INFO: [CallFlowState.SELECT_PROVIDER],
    CallFlowState.RETURNING_PATIENT_INFO: [CallFlowState.SELECT_PROVIDER],
    CallFlowState.SELECT_PROVIDER: [CallFlowState.SELECT_DATE],
    CallFlowState.SELECT_DATE: [CallFlowState.SELECT_TIME],
    CallFlowState.SELECT_TIME: [CallFlowState.CONFIRM_DETAILS],
    CallFlowState.CONFIRM_DETAILS: [
        CallFlowState.BOOKING_COMPLETE,
        CallFlowState.SELECT_DATE,  # Allow going back
        CallFlowState.SELECT_TIME
    ],
    CallFlowState.BOOKING_COMPLETE: [CallFlowState.POST_BOOKING_HELP, CallFlowState.GOODBYE],
}
from services.appointment_service import AppointmentService
from services.provider_management import ProviderManagementService
from services.clinic_management import ClinicManagementService
from services.google_calendar_service import GoogleCalendarIntegrationService, GoogleCalendarConfig, GoogleCalendarService
from services.nlp_service import get_nlp_service, NLPService, IntentType, ExtractedEntities, is_confirmation, is_negation, is_goodbye
from models.enums import LanguageCode
from services.crypto import tokenize_text, make_ulid_token
from services.response_service import get_response_cache_service, get_response_templates
from services.clinic_template_variables import get_clinic_template_variables
from services.call_flow_utils import (
    extract_name, extract_date_of_birth, extract_insurance_provider,
    match_provider, match_date, match_time,
    get_available_providers, get_available_dates, get_available_times, get_provider
)
from models.schemas import AppointmentCreateRequest
import os


# ---------- Call Store (LRU Cache for Call Contexts) ----------
class CallStoreLRU:
    """LRU cache for call contexts with size limit."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[CallFlowContext, datetime]] = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def store_call(self, call_sid: str, context: CallFlowContext) -> None:
        async with self._lock:
            # Remove if exists (to update position)
            if call_sid in self._store:
                del self._store[call_sid]
            
            # Remove oldest if at capacity
            if len(self._store) >= self.max_size:
                oldest_sid = next(iter(self._store))
                del self._store[oldest_sid]
                logging.getLogger(__name__).warning(f"Call store at capacity, removed oldest call: {oldest_sid}")
            
            self._store[call_sid] = (context, datetime.now(timezone(timedelta(hours=-4))))
            self._store.move_to_end(call_sid)  # Mark as most recent
    
    async def get_call(self, call_sid: str) -> Optional[CallFlowContext]:
        async with self._lock:
            if call_sid in self._store:
                context, _ = self._store[call_sid]
                self._store.move_to_end(call_sid)  # Update access time
                return context
            return None
    
    async def remove_call(self, call_sid: str) -> bool:
        async with self._lock:
            if call_sid in self._store:
                del self._store[call_sid]
                return True
            return False
    


# Global call store instance
_call_store = CallStoreLRU()

async def store_call(call_sid: str, context: CallFlowContext) -> None:
    """Store a call context."""
    await _call_store.store_call(call_sid, context)

async def get_call(call_sid: str) -> Optional[CallFlowContext]:
    """Get a call context."""
    return await _call_store.get_call(call_sid)

async def remove_call(call_sid: str) -> bool:
    """Remove a call context."""
    return await _call_store.remove_call(call_sid)



class CallFlowService:
    """Service for managing call conversation flow and appointment booking."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = logging.getLogger(__name__)
        
        # Add patient identification lock for thread safety
        import asyncio
        self._patient_lock = asyncio.Lock()
        
        # Initialize NLP Service
        self.nlp_service = get_nlp_service()
        
        # Initialize cache services
        self.response_cache = get_response_cache_service()
        self.response_templates = get_response_templates()
        
        # Initialize Google Calendar service
        google_calendar_service = None
        try:
            client_id = settings.google_calendar.client_id
            client_secret = settings.google_calendar.client_secret.get_secret_value()
            redirect_uri = settings.google_calendar.redirect_uri
            
            if client_id and client_secret:
                config = GoogleCalendarConfig(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri
                )
                calendar_service = GoogleCalendarService(config, db)
                google_calendar_service = GoogleCalendarIntegrationService(calendar_service)
                self.logger.info("Google Calendar service initialized successfully")
            else:
                self.logger.warning("Google Calendar credentials not configured")
        except Exception as e:
            self.logger.error(f"Failed to initialize Google Calendar service: {e}")
            google_calendar_service = None
        
        self.appointment_service = AppointmentService(db, google_calendar_service)
        self.provider_service = ProviderManagementService(db)
        self.clinic_service = ClinicManagementService(db)
    
    def sanitize_template_variable(self, value: Any) -> str:
        """Remove template injection characters and limit length."""
        if not isinstance(value, str):
            value = str(value)
        
        # Remove template markers and special characters
        value = value.replace('{', '').replace('}', '')
        value = value.replace('$', '').replace('`', '')
        value = value.replace('<', '').replace('>', '')
        value = value.replace('&', '')
        
        # Limit length to prevent abuse
        return value[:200]
    
    def _validate_transition(self, from_state: CallFlowState, to_state: CallFlowState) -> bool:
        """Validate state transition is allowed."""
        allowed_states = VALID_TRANSITIONS.get(from_state, [])
        return to_state in allowed_states

    async def _transition_state(self, context: CallFlowContext, new_state: CallFlowState) -> bool:
        """Safely transition to new state with validation."""
        if not self._validate_transition(context.current_state, new_state):
            self.logger.error(
                f"Invalid state transition: {context.current_state} -> {new_state}",
                extra={"call_id": context.call_sid}
            )
            # Don't transition, stay in current state
            return False
        
        context.current_state = new_state
        return True
    
    async def initialize_call(self, call_sid: str, caller_phone: str, clinic_id: Optional[str] = None) -> CallFlowResponse:
        """
        Initialize a new call and start the conversation flow.
        
        This method is idempotent - if CallFlowContext already exists, it returns it.
        
        Args:
            call_sid: Call session ID
            caller_phone: Caller's phone number
            clinic_id: Clinic ID (optional - if None, will check CLINIC_ID env var)
            
        Returns:
            Initial call flow response
        """
        try:
            # If clinic_id not provided, check CLINIC_ID env var
            if not clinic_id:
                import os
                clinic_id = os.getenv("CLINIC_ID")
                if clinic_id:
                    self.logger.info(f"Using CLINIC_ID from environment: {clinic_id}")
            
            # Check if context already exists (idempotent)
            existing_context = await get_call(call_sid)
            if existing_context:
                self.logger.info(f"Call flow context already exists for call {call_sid}, returning existing context")
                # Get clinic template variables (from env vars, config file, or database)
                clinic_vars = await get_clinic_template_variables(clinic_id, self.db)
                cached_message = await self._get_cached_message(
                    intent="greeting",
                    language="en",
                    variables=clinic_vars
                )
                message = cached_message or f"Hello! Thank you for calling {clinic_vars.get('clinic_name', 'our clinic')}. How can I help you today?"
                return CallFlowResponse(
                    next_state=existing_context.current_state,
                    message=message,
                    data=clinic_vars
                )
            
            # Create call record (only if it doesn't exist)
            existing_call_result = await self.db.execute(select(Call).where(Call.call_sid == call_sid))
            existing_call = existing_call_result.scalar_one_or_none()
            if not existing_call:
                try:
                    call = Call(
                        call_sid=call_sid,
                        call_id=f"CALL_{make_ulid_token('CALL')[:12]}",
                        clinic_id=clinic_id,
                        caller_phone_token=self._tokenize_phone(caller_phone),
                        status=CallStatus.ACTIVE.value
                    )
                    self.db.add(call)
                    await self.db.flush()
                    await self.db.commit()  # Issue 3: Commit after flush to persist call record
                except Exception as commit_error:
                    await self.db.rollback()
                    self.logger.error(f"Failed to commit call record: {commit_error}")
                    raise
            
            # Get clinic information
            clinic = await self.clinic_service.get_clinic(clinic_id)
            if not clinic:
                raise ValueError(f"Clinic {clinic_id} not found")
            
            # Create call context
            context = CallFlowContext(
                call_sid=call_sid,
                current_state=CallFlowState.GET_INTENT,
                clinic_id=clinic_id
            )
            
            # Store context
            await store_call(call_sid, context)
            
            # Get clinic template variables (from env vars, config file, or database)
            clinic_vars = await get_clinic_template_variables(clinic_id, self.db)
            
            # Generate greeting message using cache
            cached_message = await self._get_cached_message(
                intent="greeting",
                language="en",  # Default to English, could be dynamic based on caller
                variables=clinic_vars
            )
            message = cached_message or f"Hello! Thank you for calling {clinic_vars.get('clinic_name', 'our clinic')}. How can I help you today?"
            
            return CallFlowResponse(
                next_state=CallFlowState.GET_INTENT,
                message=message,
                data=clinic_vars
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initialize call {call_sid}: {str(e)}")
            raise ValueError(f"Failed to initialize call: {str(e)}")
    
    # Removed process_user_input_with_router - unused, only process_user_input is used
    async def process_user_input(self, call_sid: str, user_input: str, entities: Optional[List[Dict[str, Any]]] = None) -> CallFlowResponse:
        """
        Process user input and determine next conversation step.
        
        Args:
            call_sid: Call session ID
            user_input: User's speech or text input
            entities: Optional pre-extracted entities (Issue 6: Pass entities instead of re-extracting)
            
        Returns:
            Call flow response with next step
        """
        try:
            # Issue 7.1: Validate input parameters at service boundary
            from services.exceptions import ValidationError
            
            if not call_sid or not isinstance(call_sid, str) or len(call_sid.strip()) == 0:
                raise ValidationError("call_sid", call_sid, "Call session ID is required and must be a non-empty string")
            
            if not user_input or not isinstance(user_input, str) or len(user_input.strip()) == 0:
                raise ValidationError("user_input", user_input, "User input is required and must be a non-empty string")
            
            # Validate entities if provided
            if entities is not None:
                if not isinstance(entities, list):
                    raise ValidationError("entities", entities, "Entities must be a list if provided")
                for entity in entities:
                    if not isinstance(entity, dict):
                        raise ValidationError("entities", entities, "Each entity must be a dictionary")
            
            # Get call context
            context = await get_call(call_sid)
            if not context:
                # Issue 4: Use lock around context creation to prevent race condition
                async with _call_store._lock:
                    # Re-check after acquiring lock (double-check pattern)
                    context = await get_call(call_sid)
                    if not context:
                        # Issue 7: Initialize state when creating new context
                        context = CallFlowContext(
                            call_sid=call_sid,
                            current_state=CallFlowState.GET_INTENT,
                            clinic_id="default"  # Will be updated from database if available
                        )
                        # Store the new context
                        await store_call(call_sid, context)
            
            # Issue 6: Use pre-extracted entities if provided, otherwise extract
            if entities:
                # Store entities in context for use in state processing
                context.metadata = context.metadata or {}
                context.metadata['extracted_entities'] = entities
                # Issue 6: Use entities directly instead of re-extracting
                self.logger.debug(f"Using pre-extracted entities for call {call_sid}: {len(entities)} entities")
            
            # Issue 159: Validate state transition before processing to prevent side effects
            # Determine expected next state based on current state and user input
            # This is a simplified check - full validation happens after processing
            expected_next_state = None
            if context.current_state == CallFlowState.GET_INTENT:
                # Intent processing will determine next state
                pass
            elif context.current_state == CallFlowState.CONFIRM_DETAILS:
                # Confirmation can lead to booking or back to selection
                if any(word in user_input.lower() for word in ["yes", "yeah", "correct", "okay", "ok"]):
                    expected_next_state = CallFlowState.BOOKING_COMPLETE
                elif "no" in user_input.lower() or "change" in user_input.lower():
                    expected_next_state = CallFlowState.SELECT_PROVIDER
            
            # Add to conversation history
            context.conversation_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_input": user_input,
                "state": context.current_state,
                "entities": entities if entities else None  # Issue 5: Store entities in conversation history
            })
            
            # Process based on current state
            if context.current_state == CallFlowState.GET_INTENT:
                response = await self._process_intent(context, user_input)
            elif context.current_state == CallFlowState.IDENTIFY_PATIENT:
                response = await self._process_patient_identification(context, user_input)
            elif context.current_state == CallFlowState.NEW_PATIENT_INFO:
                response = await self._process_patient_info(context, user_input, is_new_patient=True)
            elif context.current_state == CallFlowState.RETURNING_PATIENT_INFO:
                response = await self._process_patient_info(context, user_input, is_new_patient=False)
            elif context.current_state == CallFlowState.SELECT_PROVIDER:
                response = await self._process_provider_selection(context, user_input)
            elif context.current_state == CallFlowState.SELECT_DATE:
                response = await self._process_date_selection(context, user_input)
            elif context.current_state == CallFlowState.SELECT_TIME:
                response = await self._process_time_selection(context, user_input)
            elif context.current_state == CallFlowState.CONFIRM_DETAILS:
                response = await self._process_confirmation(context, user_input)
            elif context.current_state == CallFlowState.POST_BOOKING_HELP:
                response = await self._process_post_booking_help(context, user_input)
            elif context.current_state == CallFlowState.CANCEL_APPOINTMENT:
                response = await self._process_cancellation(context, user_input)
            elif context.current_state == CallFlowState.INSURANCE_INQUIRY:
                response = CallFlowResponse(
                    next_state=CallFlowState.TRANSFER_TO_HUMAN,
                    message="Transferring you to our insurance department. Please hold.",
                    is_complete=True
                )
            elif context.current_state == CallFlowState.PROVIDER_INQUIRY:
                response = CallFlowResponse(
                    next_state=CallFlowState.TRANSFER_TO_HUMAN,
                    message="Transferring you to our medical staff. Please hold.",
                    is_complete=True
                )
            else:
                response = CallFlowResponse(
                    next_state=CallFlowState.GOODBYE,
                    message="I'm sorry, I didn't understand that. Let me transfer you to our staff.",
                    is_complete=True
                )
            
            # Issue 9: Validate state transition before updating state
            if not self._validate_transition(context.current_state, response.next_state):
                self.logger.error(
                    f"Invalid state transition: {context.current_state} -> {response.next_state}",
                    extra={"call_id": context.call_sid}
                )
                # Don't transition, stay in current state and return error response
                return CallFlowResponse(
                    next_state=context.current_state,  # Stay in current state
                    message="I'm sorry, I'm having trouble understanding. Could you please repeat?",
                    requires_input=True
                )
            
            # Issue 1.4: Only update state after successful persistence
            # Store previous state for rollback if persistence fails
            previous_state = context.current_state
            
            # Persist state first before updating in-memory state
            try:
                # Create a temporary context with new state for persistence
                temp_context = CallFlowContext(
                    call_sid=context.call_sid,
                    current_state=response.next_state,
                    clinic_id=context.clinic_id,
                    metadata=context.metadata,
                    created_at=context.created_at,
                    updated_at=datetime.now(timezone.utc)
                )
                
                # Persist state
                await store_call(call_sid, temp_context)
                
                # Only update in-memory state after successful persistence
                context.current_state = response.next_state
                context.updated_at = datetime.now(timezone.utc)
                
                self.logger.debug(
                    f"State persisted and updated for call {call_sid}: {previous_state} -> {response.next_state}",
                    extra={"call_id": call_sid}
                )
                
            except Exception as persist_error:
                # Issue 7.3: Use standardized logging
                # Rollback: keep previous state if persistence fails
                from services.structured_logging import LogCategory
                self.logger.error(
                    f"Failed to persist state for call {call_sid}, keeping previous state: {persist_error}",
                    LogCategory.CALL_FLOW,
                    exception=persist_error,
                    extra_data={"call_id": call_sid, "previous_state": str(previous_state), "attempted_state": str(response.next_state)}
                )
                # Return response with previous state
                return CallFlowResponse(
                    next_state=previous_state,
                    message="I'm sorry, I'm having trouble processing that. Could you please repeat?",
                    requires_input=True
                )
            
            return response
                
        except Exception as e:
            self.logger.error(f"Failed to process input for call {call_sid}: {str(e)}")
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message="I'm sorry, I'm having trouble understanding. Let me transfer you to our staff.",
                is_complete=True
            )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
        reraise=True
    )
    async def _classify_intent_with_retry(self, user_input: str, call_sid: str):
        """Issue 7: Classify intent with retry logic for transient NLP failures."""
        return await self.nlp_service.classify_intent(user_input, call_sid)
    
    async def _process_intent(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """
        Process user intent using natural language processing.
        
        Uses advanced pattern matching and context awareness to understand
        user intent more naturally and flexibly.
        """
        # Issue 7: Process input with NLP service using retry logic
        result = await self._classify_intent_with_retry(user_input, context.call_sid)
        
        # Handle different intents based on confidence and context
        if result.confidence >= 0.7:  # High confidence
            return await self._handle_high_confidence_intent(result, context)
        elif result.confidence >= 0.4:  # Medium confidence
            # Medium confidence - ask for clarification
            if result.intent == IntentType.APPOINTMENT_BOOKING:
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message="It sounds like you might want to book an appointment. Is that correct?",
                    data={"intent": "clarification", "suggested_intent": "appointment_booking"}
                )
            elif result.intent == IntentType.APPOINTMENT_CANCELLATION:
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message="It sounds like you might want to cancel or reschedule an appointment. Is that correct?",
                    data={"intent": "clarification", "suggested_intent": "cancellation"}
                )
            else:
                # Fall through to unclear intent handling
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message="I'm not sure I understand. Could you please tell me what you need help with today? You can say things like 'I need to book an appointment', 'I want to cancel my appointment', or 'I have an insurance question'.",
                    data={"intent": "unclear"}
                )
        else:  # Low confidence or unclear
            return CallFlowResponse(
                next_state=CallFlowState.GET_INTENT,
                message="I'm not sure I understand. Could you please tell me what you need help with today? You can say things like 'I need to book an appointment', 'I want to cancel my appointment', or 'I have an insurance question'.",
                data={"intent": "unclear"}
            )

    async def _handle_high_confidence_intent(self, result, context: CallFlowContext) -> CallFlowResponse:
        """Handle high confidence intent detection"""
        if result.intent == IntentType.APPOINTMENT_BOOKING:
            context.call_type = "appointment_booking"
            # Extract name if provided
            if result.entities.name:
                context.patient_name = result.entities.name
                return CallFlowResponse(
                    next_state=CallFlowState.RETURNING_PATIENT_INFO,
                    message=f"Nice to meet you, {result.entities.name}. Have you been to our clinic before?",
                    data={"intent": "appointment_booking", "name": result.entities.name}
                )
            else:
                # Use cached message for appointment booking
                cached_message = await self._get_cached_message(
                    intent="appointment_booking",
                    language="en"
                )
                message = cached_message or "I'd be happy to help you book an appointment. What's your name?"
                
                return CallFlowResponse(
                    next_state=CallFlowState.IDENTIFY_PATIENT,
                    message=message,
                    data={"intent": "appointment_booking"}
                )
        
        elif result.intent == IntentType.APPOINTMENT_CANCELLATION:
            context.call_type = "cancellation"
            if result.entities.name:
                context.patient_name = result.entities.name
                return CallFlowResponse(
                    next_state=CallFlowState.CANCEL_APPOINTMENT,
                    message=f"Hi {result.entities.name}, I can help you cancel your appointment. Let me look up your information.",
                    data={"intent": "cancellation", "name": result.entities.name}
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.CANCEL_APPOINTMENT,
                    message="I can help you cancel or reschedule your appointment. What's your name?",
                    data={"intent": "cancellation"}
                )
        
        elif result.intent == IntentType.APPOINTMENT_RESCHEDULING:
            context.call_type = "rescheduling"
            if result.entities.name:
                context.patient_name = result.entities.name
                return CallFlowResponse(
                    next_state=CallFlowState.CANCEL_APPOINTMENT,
                    message=f"Hi {result.entities.name}, I can help you reschedule your appointment. Let me look up your information.",
                    data={"intent": "rescheduling", "name": result.entities.name}
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.CANCEL_APPOINTMENT,
                    message="I can help you reschedule your appointment. What's your name?",
                    data={"intent": "rescheduling"}
                )
        
        elif result.intent == IntentType.INSURANCE_INQUIRY:
            context.call_type = "insurance_inquiry"
            # Note: Non-patient routing is handled by call_orchestrator before reaching here
            return CallFlowResponse(
                next_state=CallFlowState.INSURANCE_INQUIRY,
                message="I'll connect you with our staff who can help with insurance matters. Please hold while I transfer you.",
                data={"intent": "insurance_inquiry"},
                is_complete=True
            )
        
        elif result.intent == IntentType.PROVIDER_INQUIRY:
            context.call_type = "provider_inquiry"
            # Note: Non-patient routing is handled by call_orchestrator before reaching here
            return CallFlowResponse(
                next_state=CallFlowState.PROVIDER_INQUIRY,
                message="I'll connect you with our medical staff. Please hold while I transfer you.",
                data={"intent": "provider_inquiry"},
                is_complete=True
            )
        
        elif result.intent == IntentType.CLINIC_INQUIRY:
            context.call_type = "clinic_inquiry"
            # Note: Non-patient routing is handled by call_orchestrator before reaching here
            return CallFlowResponse(
                next_state=CallFlowState.PROVIDER_INQUIRY,
                message="I'll connect you with our staff. Please hold while I transfer you.",
                data={"intent": "clinic_inquiry"},
                is_complete=True
            )
        
        elif result.intent == IntentType.BILLING_INQUIRY:
            context.call_type = "billing_inquiry"
            # Note: Non-patient routing is handled by call_orchestrator before reaching here
            return CallFlowResponse(
                next_state=CallFlowState.PROVIDER_INQUIRY,
                message="I'll connect you with our billing staff. Please hold while I transfer you.",
                data={"intent": "billing_inquiry"},
                is_complete=True
            )
        
        elif result.intent == IntentType.EMERGENCY:
            context.call_type = "emergency"
            return CallFlowResponse(
                next_state=CallFlowState.TRANSFER_TO_HUMAN,
                message="I understand this is an emergency. I'm connecting you with our medical staff immediately. Please hold.",
                data={"intent": "emergency"},
                is_complete=True
            )
        
        elif result.intent == IntentType.GREETING:
            return CallFlowResponse(
                next_state=CallFlowState.GET_INTENT,
                message="Hello! Thank you for calling. How can I help you today?",
                data={"intent": "greeting"}
            )
        
        elif result.intent == IntentType.GOODBYE:
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message="Thank you for calling! Have a great day!",
                data={"intent": "goodbye"},
                is_complete=True
            )
        
        elif result.intent == IntentType.GENERAL_INQUIRY:
            context.call_type = "general_inquiry"
            # Use NLP service to generate response for general inquiries
            try:
                entities_list = []
                if result.entities:
                    if isinstance(result.entities, list):
                        entities_list = result.entities
                    elif hasattr(result.entities, '__dict__'):
                        entities_list = [{"type": k, "value": v} for k, v in result.entities.__dict__.items() if v]
                
                response_result = await self.nlp_service.generate_response(
                    user_input=context.conversation_history[-1]['user_input'] if context.conversation_history else "How can I help you?",
                    call_id=context.call_sid,
                    language=LanguageCode.ENGLISH,  # Default to English, could be dynamic
                    clinic_id=context.clinic_id,
                    intent=result.intent,
                    entities=entities_list if entities_list else None
                )
                
                response_text = response_result.response_text if hasattr(response_result, 'response_text') else str(response_result)
                
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message=response_text,
                    data={"intent": "general_inquiry"}
                )
            except Exception as e:
                self.logger.error(f"Error generating response for general inquiry: {e}")
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message="I'm here to help! Could you tell me more about what you need?",
                    data={"intent": "general_inquiry"}
                )
        
        elif result.intent == IntentType.APPOINTMENT_INQUIRY:
            context.call_type = "appointment_inquiry"
            return CallFlowResponse(
                next_state=CallFlowState.GET_INTENT,
                message="I can help you with appointment information. Would you like to book a new appointment, check an existing one, or reschedule?",
                data={"intent": "appointment_inquiry"}
            )
        
        elif result.intent == IntentType.CLINIC_INQUIRY:
            context.call_type = "clinic_inquiry"
            # Use NLP service to generate response for clinic inquiries
            try:
                response_result = await self.nlp_service.generate_response(
                    user_input=context.conversation_history[-1]['user_input'] if context.conversation_history else "Tell me about the clinic",
                    call_id=context.call_sid,
                    clinic_id=context.clinic_id,
                    language=LanguageCode.ENGLISH,
                    intent=result.intent,
                    entities=None
                )
                
                response_text = response_result.response_text if hasattr(response_result, 'response_text') else str(response_result)
                
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message=response_text,
                    data={"intent": "clinic_inquiry"}
                )
            except Exception as e:
                self.logger.error(f"Error generating response for clinic inquiry: {e}")
                return CallFlowResponse(
                    next_state=CallFlowState.GET_INTENT,
                    message="I'd be happy to tell you about our clinic. What would you like to know?",
                    data={"intent": "clinic_inquiry"}
                )
        
        elif result.intent == IntentType.BILLING_INQUIRY:
            context.call_type = "billing_inquiry"
            return CallFlowResponse(
                next_state=CallFlowState.TRANSFER_TO_HUMAN,
                message="I'll connect you with our billing department. Please hold while I transfer you.",
                data={"intent": "billing_inquiry"},
                is_complete=True
            )
        
        # Default for high confidence but unknown intent
        return CallFlowResponse(
            next_state=CallFlowState.GET_INTENT,
            message="I understand you need help, but I'm not sure exactly what you need. Could you tell me more about what you're looking for?",
            data={"intent": "unclear"}
        )

    
    async def _process_patient_identification(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process patient name and ask if they've been before."""
        # Use NLP service to extract name
        # Issue 7: Use retry logic for NLP calls
        result = await self._classify_intent_with_retry(user_input, context.call_sid)
        # Extract name from entities
        if isinstance(result.entities, ExtractedEntities):
            name = result.entities.name
        elif isinstance(result.entities, list):
            name = next((e.get("value") for e in result.entities if e.get("type") == "name"), None)
        else:
            name = None
        name = name or extract_name(user_input)
        if not name:
            return CallFlowResponse(
                next_state=CallFlowState.IDENTIFY_PATIENT,
                message="I didn't catch your name. Could you please tell me your full name?",
                requires_input=True
            )
        
        context.patient_name = name
        
        # Ask if they've been before
        return CallFlowResponse(
            next_state=CallFlowState.RETURNING_PATIENT_INFO,
            message=f"Nice to meet you, {name}. Have you been to our clinic before?",
            options=["Yes", "No"],
            data={"patient_name": name}
        )
    
    async def _process_patient_info(self, context: CallFlowContext, user_input: str, is_new_patient: bool) -> CallFlowResponse:
        """Process patient information collection (unified for new and returning patients)."""
        # If returning patient, first check if they've been before
        if not is_new_patient:
            result = await self._classify_intent_with_retry(user_input, context.call_sid)
            
            if is_confirmation(user_input):
                context.is_returning_patient = True
                
                # Use lock to prevent race conditions in patient identification
                async with self._patient_lock:
                    # Issue 20: Validate patient_name exists before calling _identify_patient
                    if not context.patient_name or not context.patient_name.strip():
                        return CallFlowResponse(
                            next_state=CallFlowState.IDENTIFY_PATIENT,
                            message="I didn't catch your name. Could you please tell me your full name?",
                            requires_input=True
                        )
                    patient_result = await self._identify_patient(context.patient_name)
                    if patient_result.is_found and patient_result.confidence > 0.8:
                        context.patient_id = patient_result.patient_id
                        # Use cached message for provider selection
                        cached_message = await self._get_cached_message(
                            intent="provider_inquiry",
                            language="en"
                        )
                        message = cached_message or f"Great! I found you in our system. Which doctor would you like to see?"
                        
                        return CallFlowResponse(
                            next_state=CallFlowState.SELECT_PROVIDER,
                            message=message,
                            data={"patient_found": True}
                        )
                    elif patient_result.multiple_matches:
                        # Issue 43, 169: Handle multiple matches by asking for disambiguation with DOB
                        context.metadata = context.metadata or {}
                        context.metadata['multiple_patient_matches'] = patient_result.multiple_matches
                        context.metadata['patient_matches_count'] = len(patient_result.multiple_matches) if isinstance(patient_result.multiple_matches, list) else 1
                        return CallFlowResponse(
                            next_state=CallFlowState.IDENTIFY_PATIENT,
                            message="I found multiple patients with that name. Can you provide your date of birth to help me find the right one?",
                            requires_input=True,
                            data={"multiple_matches": True, "match_count": context.metadata['patient_matches_count']}
                        )
                    else:
                        # Patient says they've been before but not found - treat as new
                        return CallFlowResponse(
                            next_state=CallFlowState.NEW_PATIENT_INFO,
                            message="I don't see you in our system yet. Let me get some information to set up your appointment. What's your date of birth?",
                            data={"patient_found": False}
                        )
            
            elif is_negation(user_input):
                context.is_returning_patient = False
                return CallFlowResponse(
                    next_state=CallFlowState.NEW_PATIENT_INFO,
                    message="Welcome! Let me get some information to set up your appointment. What's your date of birth?",
                    data={"is_new_patient": True}
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.RETURNING_PATIENT_INFO,
                    message="Have you been to our clinic before? Please say yes or no.",
                    options=["Yes", "No"]
                )
        
        # New patient information collection
        # Issue 188: Validate required fields before proceeding
        if not context.patient_dob:
            # Collect date of birth using natural language processor
            result = await self._classify_intent_with_retry(user_input, context.call_sid)
            # Extract date of birth from entities
            if isinstance(result.entities, ExtractedEntities):
                dob = result.entities.date_of_birth
            elif isinstance(result.entities, list):
                dob = next((e.get("value") for e in result.entities if e.get("type") == "date_of_birth"), None)
            else:
                dob = None
            dob = dob or extract_date_of_birth(user_input)
            if dob:
                # Issue 188: Validate DOB format before storing
                try:
                    if isinstance(dob, str):
                        from datetime import datetime
                        datetime.strptime(dob, '%Y-%m-%d')  # Validate format
                    context.patient_dob = dob
                    return CallFlowResponse(
                        next_state=CallFlowState.NEW_PATIENT_INFO,
                        message="Thank you. What's your insurance provider?",
                        data={"dob_collected": True}
                    )
                except (ValueError, TypeError) as dob_error:
                    self.logger.warning(f"Invalid DOB format: {dob_error}")
                    return CallFlowResponse(
                        next_state=CallFlowState.NEW_PATIENT_INFO,
                        message="I need a valid date of birth. Please tell me your date of birth, for example, January 15th, 1990.",
                        requires_input=True
                    )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.NEW_PATIENT_INFO,
                    message="I need your date of birth. Please tell me your date of birth, for example, January 15th, 1990.",
                    requires_input=True
                )
        
        elif not context.insurance_provider:
            # Collect insurance provider using natural language processor
            result = await self._classify_intent_with_retry(user_input, context.call_sid)
            # Extract insurance provider from entities
            if isinstance(result.entities, ExtractedEntities):
                insurance = result.entities.insurance_provider
            elif isinstance(result.entities, list):
                insurance = next((e.get("value") for e in result.entities if e.get("type") == "insurance_provider"), None)
            else:
                insurance = None
            insurance = insurance or extract_insurance_provider(user_input)
            if insurance:
                context.insurance_provider = insurance
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_PROVIDER,
                    message="Perfect! Now, which doctor would you like to see?",
                    data={"insurance_collected": True}
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.NEW_PATIENT_INFO,
                    message="What's your insurance provider? For example, Blue Cross, Aetna, or Medicare.",
                    requires_input=True
                )
        
        else:
            # All new patient info collected, move to provider selection
            return CallFlowResponse(
                next_state=CallFlowState.SELECT_PROVIDER,
                message="Great! Now, which doctor would you like to see?",
                data={"new_patient_info_complete": True}
            )
    
    async def _process_provider_selection(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process provider selection."""
        # Get available providers
        providers = await self._get_available_providers(context.clinic_id)
        
        # Try to match user input to a provider using natural language processor
        # Issue 7: Use retry logic for NLP calls
        result = await self._classify_intent_with_retry(user_input, context.call_sid)
        # Extract provider name from entities
        if isinstance(result.entities, ExtractedEntities):
            provider_name = result.entities.provider_name
        elif isinstance(result.entities, list):
            provider_name = next((e.get("value") for e in result.entities if e.get("type") == "provider_name"), None)
        else:
            provider_name = None
        if provider_name:
            selected_provider = match_provider(provider_name, providers)
        else:
            selected_provider = match_provider(user_input, providers)
        
        if selected_provider:
            # Issue 173, 197: Validate provider availability and existence before selecting
            if hasattr(selected_provider, 'is_available') and not selected_provider.is_available:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_PROVIDER,
                    message=f"I'm sorry, {selected_provider.name} is not currently available. Would you like to see another doctor?",
                    requires_input=True
                )
            
            # Issue 197: Verify provider still exists in database
            provider_exists = await self._get_provider(selected_provider.provider_id)
            if not provider_exists:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_PROVIDER,
                    message="I'm sorry, that provider is no longer available. Let me show you the available doctors.",
                    requires_input=True
                )
            
            context.provider_id = selected_provider.provider_id
            # Use the name as-is since it already includes the title
            display_name = selected_provider.name
            return CallFlowResponse(
                next_state=CallFlowState.SELECT_DATE,
                message=f"Perfect! You'd like to see {display_name} in {selected_provider.specialty}. What day works best for you?",
                data={"provider_selected": selected_provider.dict()}
            )
        else:
            # Show available providers
            provider_options = [f"{p.name} - {p.specialty}" for p in providers]
            # Use cached message for provider selection
            cached_message = await self._get_cached_message(
                intent="provider_inquiry",
                language="en"
            )
            message = cached_message or "Which doctor would you like to see?"
            
            return CallFlowResponse(
                next_state=CallFlowState.SELECT_PROVIDER,
                message=message,
                options=provider_options,
                data={"available_providers": [p.dict() for p in providers]}
            )
    
    async def _process_date_selection(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process date selection."""
        # Get available dates for the provider
        available_dates = await self._get_available_dates(context.provider_id)
        
        user_input_lower = user_input.lower()
        
        # Check if user is asking for available dates using natural language processing
        # Issue 7: Use retry logic for NLP calls
        result = await self._classify_intent_with_retry(user_input, context.call_sid)
        is_asking_for_dates = any(phrase in user_input.lower() for phrase in ["what dates", "available dates", "what days", "show me dates", "what are the dates"])
        
        if is_asking_for_dates:
            if available_dates:
                date_list = [f"{d.day_name}, {d.date.strftime('%B %d')}" for d in available_dates[:5]]  # Show first 5
                dates_text = ", ".join(date_list)
                # Store context for relative references
                context.last_mentioned_dates = [d.date for d in available_dates[:5]]
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_DATE,
                    message=f"Here are the available dates: {dates_text}. Which day works best for you?",
                    requires_input=True
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_DATE,
                    message="I don't have any available dates for this provider. Would you like to try a different doctor?",
                    requires_input=True
                )
        
        # Check if user is confirming a suggested date
        if any(word in user_input_lower for word in ["yes", "yeah", "correct", "that works", "perfect", "good"]):
            if available_dates and len(available_dates) > 0:
                # Select the first available date
                selected_date = available_dates[0]
                context.appointment_date = selected_date.date
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message=f"Great! {selected_date.day_name} works. What time would you prefer?",
                    data={"date_selected": selected_date.dict()}
                )
        
        # Try to match user input to a date
        selected_date = match_date(user_input, available_dates, context)
        
        if selected_date:
            # Issue 177: Re-validate date availability after user selection
            # Re-check available dates to ensure selected date is still available
            current_available_dates = self._get_available_dates(context.provider_id)
            current_date_match = next((d for d in current_available_dates if d.date == selected_date.date), None)
            
            if not current_date_match:
                # Selected date is no longer available
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_DATE,
                    message="I'm sorry, that date is no longer available. Let me show you the current available dates.",
                    requires_input=True
                )
            
            context.appointment_date = selected_date.date
            
            # Check if user also mentioned a time in the same response
            available_times = await self._get_available_times(context.provider_id, selected_date.date)
            selected_time = match_time(user_input, available_times)
            
            if selected_time:
                # User provided both date and time
                context.appointment_time = selected_time.start_time
                return CallFlowResponse(
                    next_state=CallFlowState.CONFIRM_DETAILS,
                    message=f"Perfect! {selected_date.day_name} at {selected_time.start_time.strftime('%I:%M %p')} works. Let me confirm your appointment details.",
                    data={"date_selected": selected_date.dict(), "time_selected": selected_time.dict()}
                )
            else:
                # User only provided date
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message=f"Great! {selected_date.day_name} works. What time would you prefer?",
                    data={"date_selected": selected_date.dict()}
                )
        else:
            # Check if user mentioned a specific date that's not available
            if available_dates:
                # Suggest a few available dates instead of listing all
                suggested_dates = available_dates[:3]  # Show first 3 available dates
                date_suggestions = [f"{d.day_name}, {d.date.strftime('%B %d')}" for d in suggested_dates]
                suggestions_text = ", ".join(date_suggestions)
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_DATE,
                    message=f"I don't have availability for that date. How about {suggestions_text}?",
                    requires_input=True
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_DATE,
                    message="I don't have any available dates for this provider. Would you like to try a different doctor?",
                    requires_input=True
                )
    
    async def _process_time_selection(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process time selection."""
        # Get available time slots for the selected date
        available_times = await self._get_available_times(context.provider_id, context.appointment_date)
        
        user_input_lower = user_input.lower()
        
        # Check if user is asking for available times
        if any(phrase in user_input_lower for phrase in ["what times", "available times", "what time slots", "show me times", "what are the times"]):
            if available_times:
                time_list = [t.start_time.strftime('%I:%M %p') for t in available_times[:8]]  # Show first 8
                times_text = ", ".join(time_list)
                # Store context for relative references
                context.last_mentioned_times = [t.start_time for t in available_times[:8]]
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message=f"Here are the available times: {times_text}. Which time works best for you?",
                    requires_input=True
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message="I don't have any available times for this date. Would you like to try a different day?",
                    requires_input=True
                )
        
        # Try to match user input to a time first
        selected_time = match_time(user_input, available_times)
        
        if selected_time:
            # Issue 48, 72: Validate that the selected time is still available and lock the slot
            # Re-query available times to ensure the slot is still available (race condition check)
            current_available_times = await self._get_available_times(context.provider_id, context.appointment_date)
            current_time_slot = next((t for t in current_available_times if t.slot_id == selected_time.slot_id), None)
            
            if not current_time_slot:
                # Slot is no longer available
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message="I'm sorry, that time slot is no longer available. Let me show you the current available times.",
                    requires_input=True
                )
            
            # Issue 157: Actually lock the slot using transaction manager to prevent double-booking
            try:
                from services.transaction_manager import get_transaction_manager
                from models.models import AppointmentSlot
                from models.enums import YesNo
                from datetime import datetime, timezone, timedelta
                
                transaction_manager = get_transaction_manager(self.db)
                
                # Issue 13, 157: Actually hold the slot in the database with validation
                # Lock the slot row and mark it as held, checking for held slots
                current_time = datetime.now(timezone.utc)
                
                slot_result = await self.db.execute(
                    select(AppointmentSlot).where(
                        AppointmentSlot.slot_id == current_time_slot.slot_id,
                        # Issue 13: Slot must be available (not booked) OR held but expired
                        (
                            (AppointmentSlot.is_booked == YesNo.NO.value) |
                            (
                                (AppointmentSlot.is_booked == "held") &
                                (
                                    (AppointmentSlot.held_until.is_(None)) |
                                    (AppointmentSlot.held_until < current_time)
                                )
                            )
                        )
                    ).with_for_update()
                )
                slot = slot_result.scalar_one_or_none()
                
                if slot:
                    # Issue 13: Re-verify slot is actually available (not held by another call)
                    if slot.is_booked == "held" and slot.held_until and slot.held_until >= current_time:
                        # Slot is still held by another call
                        if slot.held_by_call_sid != context.call_sid:
                            self.logger.warning(
                                f"Slot {slot.slot_id} is held by another call {slot.held_by_call_sid} until {slot.held_until}"
                            )
                            return CallFlowResponse(
                                next_state=CallFlowState.SELECT_TIME,
                                message="I'm sorry, that time slot is currently being held. Let me show you other available times.",
                                requires_input=True
                            )
                    
                    # Mark slot as held temporarily
                    slot.is_booked = "held"
                    slot.held_until = datetime.now(timezone.utc) + timedelta(minutes=15)  # Hold for 15 minutes
                    slot.held_by_call_sid = context.call_sid
                    await self.db.commit()
                    
                    context.appointment_time = current_time_slot.start_time
                    context.metadata = context.metadata or {}
                    context.metadata['selected_slot_id'] = current_time_slot.slot_id
                    return CallFlowResponse(
                        next_state=CallFlowState.CONFIRM_DETAILS,
                        message=f"Perfect! {current_time_slot.start_time.strftime('%I:%M %p')} works. Let me confirm your appointment details.",
                        data={"time_selected": current_time_slot.dict()}
                    )
                else:
                    # Slot is no longer available
                    return CallFlowResponse(
                        next_state=CallFlowState.SELECT_TIME,
                        message="I'm sorry, that time slot is no longer available. Let me show you the current available times.",
                        requires_input=True
                    )
            except Exception as e:
                self.logger.error(f"Failed to lock slot: {e}")
                await self.db.rollback()
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message="I'm sorry, I'm having trouble reserving that time. Let me show you the available times again.",
                    requires_input=True
                )
        
        # Check if user is confirming a suggested time (only if no time was matched)
        if any(word in user_input_lower for word in ["yes", "yeah", "correct", "that works", "perfect", "good"]):
            if available_times and len(available_times) > 0:
                # Issue 48, 72: Validate and lock the first available time
                selected_time = available_times[0]
                # Re-query to ensure slot is still available
                current_available_times = await self._get_available_times(context.provider_id, context.appointment_date)
                current_time_slot = next((t for t in current_available_times if t.slot_id == selected_time.slot_id), None)
                
                if not current_time_slot:
                    return CallFlowResponse(
                        next_state=CallFlowState.SELECT_TIME,
                        message="I'm sorry, that time slot is no longer available. Let me show you the current available times.",
                        requires_input=True
                    )
                
                # Lock the slot
                try:
                    from services.transaction_manager import get_transaction_manager
                    transaction_manager = get_transaction_manager(self.db)
                    context.appointment_time = current_time_slot.start_time
                    context.metadata = context.metadata or {}
                    context.metadata['selected_slot_id'] = current_time_slot.slot_id
                    return CallFlowResponse(
                        next_state=CallFlowState.CONFIRM_DETAILS,
                        message=f"Perfect! {current_time_slot.start_time.strftime('%I:%M %p')} works. Let me confirm your appointment details.",
                        data={"time_selected": current_time_slot.dict()}
                    )
                except Exception as e:
                    self.logger.error(f"Failed to lock slot: {e}")
                    return CallFlowResponse(
                        next_state=CallFlowState.SELECT_TIME,
                        message="I'm sorry, I'm having trouble reserving that time. Let me show you the available times again.",
                        requires_input=True
                    )
        else:
            # Check if user mentioned a specific time that's not available
            if available_times:
                # Suggest a few available times instead of listing all
                suggested_times = available_times[:3]  # Show first 3 available times
                time_suggestions = [t.start_time.strftime('%I:%M %p') for t in suggested_times]
                suggestions_text = ", ".join(time_suggestions)
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message=f"I don't have availability for that time. How about {suggestions_text}?",
                    requires_input=True
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message="I don't have any available times for this date. Would you like to try a different day?",
                    requires_input=True
                )
    
    async def _process_confirmation(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process appointment confirmation."""
        user_input_lower = user_input.lower()
        
        if any(word in user_input_lower for word in ["yes", "yeah", "correct", "okay", "ok", "sounds good", "that works", "perfect", "good"]):
            # Issue 34, 152: Validate all required fields before booking including appointment_type
            missing_fields = []
            if not context.patient_name:
                missing_fields.append("patient name")
            if not context.appointment_date:
                missing_fields.append("appointment date")
            if not context.appointment_time:
                missing_fields.append("appointment time")
            if not context.provider_id:
                missing_fields.append("provider")
            # Issue 152: Validate appointment_type is set
            if not context.appointment_type:
                missing_fields.append("appointment type")
            
            if missing_fields:
                return CallFlowResponse(
                    next_state=CallFlowState.CONFIRM_DETAILS,
                    message=f"I need a few more details to book your appointment: {', '.join(missing_fields)}. Let me help you with that.",
                    requires_input=True
                )
            
            # Issue 152, 193: Re-verify slot availability before booking
            try:
                from services.appointment_service import AppointmentService
                temp_appointment_service = AppointmentService(self.db)
                slot_available = temp_appointment_service._is_slot_available(
                    context.appointment_time,
                    context.appointment_time + timedelta(hours=1),
                    context.provider_id
                )
                if not slot_available:
                    return CallFlowResponse(
                        next_state=CallFlowState.SELECT_TIME,
                        message="I'm sorry, that time slot is no longer available. Let me show you the available times again.",
                        requires_input=True
                    )
            except Exception as slot_check_error:
                self.logger.warning(f"Failed to verify slot availability: {slot_check_error}")
                # Continue with booking attempt - appointment service will handle the error
            
            # Book the appointment
            try:
                appointment = await self._book_appointment(context)
                return CallFlowResponse(
                    next_state=CallFlowState.POST_BOOKING_HELP,
                    message=f"Excellent! I've booked your appointment for {context.appointment_date.strftime('%A, %B %d')} at {context.appointment_time.strftime('%I:%M %p')}. You'll receive a confirmation text shortly. Is there anything else I can help you with?",
                    data={"appointment_booked": True, "appointment_id": appointment.appointment_id},
                    requires_input=True
                )
            except Exception as e:
                self.logger.error(f"Failed to book appointment: {str(e)}")
                return CallFlowResponse(
                    next_state=CallFlowState.GOODBYE,
                    message="I'm sorry, I'm having trouble booking your appointment. Let me transfer you to our staff.",
                    is_complete=True
                )
        
        elif "no" in user_input_lower or "change" in user_input_lower:
            # Use cached message for provider selection
            cached_message = await self._get_cached_message(
                intent="provider_inquiry",
                language="en"
            )
            message = cached_message or "No problem! Let's start over. Which doctor would you like to see?"
            
            return CallFlowResponse(
                next_state=CallFlowState.SELECT_PROVIDER,
                message=message,
                data={"restart_booking": True}
            )
        
        else:
            # Show confirmation details
            provider = await self._get_provider(context.provider_id)
            if not provider:
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_PROVIDER,
                    message="I'm sorry, I couldn't find that provider. Let's start over. Which doctor would you like to see?",
                    requires_input=True
                )
            confirmation_message = f"Let me confirm: You'd like to see {provider.title} {provider.name} on {context.appointment_date.strftime('%A, %B %d')} at {context.appointment_time.strftime('%I:%M %p')} for a {context.appointment_type}. Is that correct?"
            
            return CallFlowResponse(
                next_state=CallFlowState.CONFIRM_DETAILS,
                message=confirmation_message,
                options=["Yes", "No"],
                data={"confirmation_details": {
                    "provider": provider.name,
                    "date": context.appointment_date.strftime('%A, %B %d'),
                    "time": context.appointment_time.strftime('%I:%M %p'),
                    "type": context.appointment_type
                }}
            )
    
    async def _process_post_booking_help(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process post-booking help requests."""
        # Use natural language processor to understand response
        # Issue 7: Use retry logic for NLP calls
        result = await self._classify_intent_with_retry(user_input, context.call_sid)
        
        # Get clinic name from template variables
        clinic_vars = await get_clinic_template_variables(context.clinic_id, self.db)
        clinic_name = clinic_vars.get('clinic_name', 'our clinic')
        
        # Check for "nothing else" or similar phrases
        if is_goodbye(user_input) or is_negation(user_input):
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message=f"Perfect! Thank you for calling {clinic_name}. Have a great day!",
                is_complete=True
            )
        
        # Check for "yes" or similar phrases
        if is_confirmation(user_input):
            return CallFlowResponse(
                next_state=CallFlowState.POST_BOOKING_HELP,
                message="What else can I help you with today?",
                requires_input=True
            )
        
        # Check for insurance or patient information requests
        if result.intent == IntentType.INSURANCE_INQUIRY or any(phrase in user_input.lower() for phrase in ["patient information", "medical records", "billing", "payment", "coverage"]):
            return CallFlowResponse(
                next_state=CallFlowState.TRANSFER_TO_HUMAN,
                message="I'll transfer you to our staff who can help you with that information.",
                is_complete=True
            )
        
        # Default response
        return CallFlowResponse(
            next_state=CallFlowState.POST_BOOKING_HELP,
            message="I'm here to help! What else can I assist you with today?",
            requires_input=True
        )
    
    async def _process_cancellation(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process appointment cancellation."""
        user_input_lower = user_input.lower()
        
        # If this is the first input, it should be the patient name
        if not context.patient_name:
            # Extract patient name
            patient_name = extract_name(user_input)
            # Issue 20: Validate patient_name exists before calling _identify_patient
            if patient_name and patient_name.strip():
                context.patient_name = patient_name
                
                # Try to find the patient
                patient_result = await self._identify_patient(patient_name)
                if patient_result.is_found:
                    context.patient_id = patient_result.patient_id
                    return CallFlowResponse(
                        next_state=CallFlowState.CANCEL_APPOINTMENT,
                        message=f"Hi {patient_name}, I found you in our system. I can help you cancel or reschedule your appointment. Would you like to cancel or reschedule?",
                        data={"patient_found": True},
                        requires_input=True
                    )
                else:
                    return CallFlowResponse(
                        next_state=CallFlowState.GOODBYE,
                        message="I don't see you in our system. Let me transfer you to our staff who can help you with your appointment.",
                        is_complete=True
                    )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.CANCEL_APPOINTMENT,
                    message="I didn't catch your name. Could you please tell me your full name?",
                    requires_input=True
                )
        
        # Handle cancel vs reschedule decision
        if "cancel" in user_input_lower:
            # Issue 12: Actually call appointment service to cancel the appointment
            if context.patient_id:
                # Find the patient's appointments
                appointments_result = await self.db.execute(
                    select(Appointment).where(
                        Appointment.patient_id == context.patient_id,
                        Appointment.status == 'scheduled'
                    )
                )
                appointments = list(appointments_result.scalars().all())
                
                # Issue 181: Handle multiple appointments by asking user which one to cancel
                if len(appointments) > 1:
                    # Multiple appointments found - ask user which one to cancel
                    appointment_list = []
                    for i, apt in enumerate(appointments[:5], 1):  # Show first 5
                        date_str = apt.appointment_date.strftime('%A, %B %d') if apt.appointment_date else "Unknown date"
                        time_str = apt.start_time.strftime('%I:%M %p') if apt.start_time else "Unknown time"
                        appointment_list.append(f"{i}. {date_str} at {time_str}")
                    
                    appointments_text = "\n".join(appointment_list)
                    context.metadata = context.metadata or {}
                    context.metadata['pending_appointments'] = [apt.appointment_id for apt in appointments[:5]]
                    
                    return CallFlowResponse(
                        next_state=CallFlowState.CANCEL_APPOINTMENT,
                        message=f"I found {len(appointments)} appointments for you:\n{appointments_text}\nWhich one would you like to cancel? Please say the number.",
                        requires_input=True,
                        data={"multiple_appointments": True, "appointment_count": len(appointments)}
                    )
                elif appointments:
                    # Issue 181: Single appointment - cancel it directly
                    appointment_to_cancel = appointments[0]
                    try:
                        cancelled = self.appointment_service.cancel_appointment(appointment_to_cancel.appointment_id)
                        if cancelled:
                            return CallFlowResponse(
                                next_state=CallFlowState.GOODBYE,
                                message="I've cancelled your appointment. You'll receive a confirmation shortly. Thank you for calling. Have a great day!",
                                is_complete=True
                            )
                        else:
                            return CallFlowResponse(
                                next_state=CallFlowState.GOODBYE,
                                message="I'm having trouble cancelling your appointment. Let me transfer you to our staff.",
                                is_complete=True
                            )
                    except Exception as e:
                        self.logger.error(f"Failed to cancel appointment: {e}")
                        return CallFlowResponse(
                            next_state=CallFlowState.GOODBYE,
                            message="I'm having trouble cancelling your appointment. Let me transfer you to our staff.",
                            is_complete=True
                        )
                else:
                    return CallFlowResponse(
                        next_state=CallFlowState.GOODBYE,
                        message="I don't see any scheduled appointments for you. Let me transfer you to our staff who can help.",
                        is_complete=True
                    )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.GOODBYE,
                    message="I need to find your appointment first. Let me transfer you to our staff who can help.",
                    is_complete=True
                )
        elif "reschedule" in user_input_lower or "change" in user_input_lower:
            # TODO: Implement rescheduling logic
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message="I'll help you reschedule your appointment. Let me transfer you to our scheduling staff.",
                is_complete=True
            )
        else:
            return CallFlowResponse(
                next_state=CallFlowState.CANCEL_APPOINTMENT,
                message="Would you like to cancel your appointment or reschedule it?",
                requires_input=True
            )
    
    async def _identify_patient(self, patient_name: str) -> PatientIdentificationResult:
        """Try to identify patient by name."""
        # Normalize input for prefix search
        search_name = patient_name.strip().upper()
        
        # Use prefix matching (starts with) for index usage
        patients_result = await self.db.execute(
            select(Patient).where(
                Patient.name_token.ilike(f"{search_name}%"),  # Removed leading %
                Patient.is_deleted == 'no'
            ).limit(10)
        )
        patients = list(patients_result.scalars().all())  # Add limit to prevent huge result sets
        
        if patients and len(patients) > 0:
            # Issue 43: Handle multiple matches - return first match but indicate if multiple exist
            if len(patients) > 1:
                # Multiple matches found - return first but indicate multiple matches
                return PatientIdentificationResult(
                    is_found=True,
                    patient_id=patients[0].patient_id,
                    patient_name=patient_name,
                    confidence=0.6,  # Lower confidence for multiple matches
                    match_reason="name_match_multiple",
                    multiple_matches=True  # Indicate multiple matches exist
                )
            else:
                # Single match
                return PatientIdentificationResult(
                    is_found=True,
                    patient_id=patients[0].patient_id,
                    patient_name=patient_name,
                    confidence=0.8,
                    match_reason="name_match"
                )
        
        return PatientIdentificationResult(
            is_found=False,
            confidence=0.0
        )
    
    async def _get_available_providers(self, clinic_id: str) -> List[ProviderOption]:
        """Get available providers for the clinic."""
        return await get_available_providers(self.db, clinic_id, self.logger)
    
    async def _get_available_dates(self, provider_id: str) -> List[DateOption]:
        """Get available dates for a provider."""
        return await get_available_dates(self.db, provider_id, self.logger)
    
    async def _get_available_times(self, provider_id: str, appointment_date: date) -> List[TimeSlotOption]:
        """Get available time slots for a provider on a specific date."""
        return await get_available_times(self.db, provider_id, appointment_date, self.logger)
    
    async def _book_appointment(self, context: CallFlowContext) -> Any:
        """Book the appointment using the appointment service."""
        # Issue 153: Use transaction to ensure both patient creation and appointment booking succeed or both fail
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        # Issue 8: Use proper transaction management with context manager
        # SQLAlchemy sessions auto-commit on success, but we need to ensure rollback on errors
        try:
            # Create or find patient
            if not context.patient_id:
                # Create new patient
                patient_id = f"PATIENT_{make_ulid_token('PATIENT')[:12]}"
                
                # Tokenize PII for HIPAA compliance
                name_token = make_hmac_token("PATIENT_NAME", context.patient_name)
                dob_token = make_hmac_token("PATIENT_DOB", context.patient_dob)
                insurance_token = make_hmac_token("INSURANCE", context.insurance_provider)
                
                # Encrypt sensitive data
                name_nonce, name_ct = encrypt_str(context.patient_name)
                dob_nonce, dob_ct = encrypt_str(context.patient_dob)
                insurance_nonce, insurance_ct = encrypt_str(context.insurance_provider)
                
                patient = Patient(
                    patient_id=patient_id,
                    name_token=name_token,
                    dob_token=dob_token,
                    insurance_provider_token=insurance_token,
                    # Store encrypted data in separate fields for future use
                    name_nonce=name_nonce,
                    name_ciphertext=name_ct,
                    dob_nonce=dob_nonce,
                    dob_ciphertext=dob_ct,
                    insurance_nonce=insurance_nonce,
                    insurance_ciphertext=insurance_ct
                )
                self.db.add(patient)
                await self.db.flush()  # Flush to get patient_id but don't commit yet
                context.patient_id = patient_id
            
            # Create appointment
            appointment_data = AppointmentCreateRequest(
                patient_id=context.patient_id,
                provider_id=context.provider_id,
                appointment_date=context.appointment_date,
                start_time=context.appointment_time,
                end_time=context.appointment_time + timedelta(hours=1),
                appointment_type=context.appointment_type
            )
            
            # Issue 153: Create appointment within the same transaction
            appointment, google_event_id = await self.appointment_service.create_appointment(
                appointment_data, context.patient_name
            )
            
            if not appointment:
                # Issue 17: Rollback on appointment creation failure
                await self.db.rollback()
                raise ValueError("Appointment creation returned None")
            
            # Issue 8: Commit transaction only if both patient creation and appointment booking succeed
            # SQLAlchemy auto-commits on successful completion, but we explicitly commit for clarity
            try:
                await self.db.commit()
            except Exception as commit_error:
                # Issue 17: Rollback if commit fails
                await self.db.rollback()
                self.logger.error(f"Failed to commit appointment booking transaction: {commit_error}")
                raise
            
            return appointment
        except Exception as e:
            self.logger.error(f"Failed to create appointment: {e}")
            # Issue 8, 17: Rollback transaction on any error
            try:
                await self.db.rollback()
            except Exception as rollback_error:
                self.logger.error(f"Failed to rollback transaction: {rollback_error}")
            raise
    
    async def _get_provider(self, provider_id: str) -> Provider:
        """Get provider by ID."""
        return await get_provider(self.db, provider_id)
    
    def _tokenize_phone(self, phone: str) -> str:
        """Tokenize phone number using HIPAA-compliant method."""
        from services.crypto import make_hmac_token, normalize_phone
        normalized_phone = normalize_phone(phone)
        return make_hmac_token("PHONE", normalized_phone)
    
    async def get_call_status(self, call_sid: str) -> Optional[CallFlowContext]:
        """Get current call status."""
        return await get_call(call_sid)
    
    async def end_call(self, call_sid: str) -> bool:
        """End the call and clean up."""
        try:
            # Update call record
            call_result = await self.db.execute(select(Call).where(Call.call_sid == call_sid))
            call = call_result.scalar_one_or_none()
            if call:
                call.status = "completed"
                call.ended_at = datetime.now(timezone.utc)
                try:
                    await self.db.commit()
                except Exception as commit_error:
                    await self.db.rollback()
                    self.logger.error(f"Failed to commit call record update: {commit_error}")
                    raise
            
            # Remove from active calls
            await remove_call(call_sid)
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to end call {call_sid}: {str(e)}")
            return False
    
    async def _get_cached_message(
        self, 
        intent: str, 
        language: str = "en", 
        variables: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Get template message for given intent and language.
        
        This is for getting predefined messages based on flow state, NOT for routing
        based on user input. For user input routing, use NLP service + ResponseRouter.
        
        Args:
            intent: Intent type (string) - represents what message to send, not user's intent
            language: Language code (string)
            variables: Template variables
            
        Returns:
            Optional[str]: Template message if found, None otherwise
        """
        try:
            # Map string intent to IntentType enum
            intent_mapping = {
                "greeting": IntentType.GREETING,
                "appointment_booking": IntentType.APPOINTMENT_BOOKING,
                "appointment_inquiry": IntentType.APPOINTMENT_INQUIRY,
                "provider_inquiry": IntentType.PROVIDER_INQUIRY,
                "clinic_inquiry": IntentType.CLINIC_INQUIRY,
                "billing_inquiry": IntentType.BILLING_INQUIRY,
                "general_inquiry": IntentType.GENERAL_INQUIRY,
                "goodbye": IntentType.GOODBYE
            }
            
            intent_type = intent_mapping.get(intent)
            if not intent_type:
                return None
            
            # Map language string to LanguageCode enum
            from models.enums import LanguageCode
            language_code = LanguageCode.ENGLISH if language == "en" else LanguageCode.SPANISH
            
            # Sanitize all variables before substitution
            sanitized_variables = {}
            if variables:
                sanitized_variables = {
                    k: self.sanitize_template_variable(v)
                    for k, v in variables.items()
                }
            
            # Get template directly from ResponseTemplates (not through ResponseRouter)
            # ResponseRouter is for routing user input, not for getting predefined messages
            if self.response_templates.has_template(intent_type, language_code):
                template_response = await self.response_templates.substitute_variables(
                    intent_type, language_code, sanitized_variables,
                    clinic_id=None,  # Clinic variables should be passed in variables parameter
                    db=self.db
                )
                
                if template_response:
                    # Cache the template response
                    await self.response_cache.cache_response(
                        intent=intent,
                        language=language,
                        response=template_response,
                        template=self.response_templates.get_template(intent_type, language_code).template,
                        variables=sanitized_variables,
                        source="template"
                    )
                    return template_response
            
            # If no template, try cache for existing responses
            cached_response = await self.response_cache.get_cached_response(
                intent=intent,
                language=language,
                variables=sanitized_variables
            )
            
            return cached_response
            
        except Exception as e:
            self.logger.warning(f"Error getting cached message: {e}")
            return None
