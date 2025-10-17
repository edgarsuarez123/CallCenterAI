"""
Call Flow Service
Handles the conversation flow for incoming calls including patient identification,
appointment booking, and Google Calendar integration.
"""

from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, date
import logging
import re

from models.models import Call, Patient, Provider, AppointmentSlot, Clinic
from models.enums import YesNo
from models.enums import CallStatus
from models.call_flow_models import (
    CallFlowState, CallFlowResponse, CallFlowContext, 
    PatientIdentificationResult, ProviderOption, TimeSlotOption, DateOption,
    AppointmentBookingData
)
from services.appointment_service import AppointmentService
from services.provider_management import ProviderManagementService
from services.clinic_management import ClinicManagementService
from services.google_calendar_service import GoogleCalendarIntegrationService, GoogleCalendarConfig, GoogleCalendarService
from services.natural_language_processor import NaturalLanguageProcessor, IntentType, ExtractedEntities
from services.tokens import tokenize_text
from services.crypto import make_ulid_token
from services.response_cache import get_response_cache_service
from services.response_templates import get_response_templates
from models.schemas import AppointmentCreateRequest
from services.call_store import store_call, get_call, remove_call, list_calls
import os


class CallFlowService:
    """Service for managing call conversation flow and appointment booking."""
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(__name__)
        
        # Initialize Natural Language Processor
        self.nlp = NaturalLanguageProcessor()
        
        # Initialize cache services
        self.response_cache = get_response_cache_service()
        self.response_templates = get_response_templates()
        
        # Initialize Google Calendar service
        google_calendar_service = None
        try:
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
            redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8443/api/v1/google-calendar/oauth/callback')
            
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
    
    async def initialize_call(self, call_sid: str, caller_phone: str, clinic_id: str) -> CallFlowResponse:
        """
        Initialize a new call and start the conversation flow.
        
        Args:
            call_sid: Twilio call SID
            caller_phone: Caller's phone number
            clinic_id: Clinic ID
            
        Returns:
            Initial call flow response
        """
        try:
            # Create call record
            call = Call(
                call_sid=call_sid,
                call_id=f"CALL_{make_ulid_token('CALL')[:12]}",
                caller_phone_token=self._tokenize_phone(caller_phone),
                status=CallStatus.ACTIVE.value
            )
            self.db.add(call)
            self.db.flush()
            
            # Get clinic information
            clinic = self.clinic_service.get_clinic(clinic_id)
            if not clinic:
                raise ValueError(f"Clinic {clinic_id} not found")
            
            # Create call context
            context = CallFlowContext(
                call_sid=call_sid,
                current_state=CallFlowState.GET_INTENT,
                clinic_id=clinic_id
            )
            
            # Store context
            store_call(call_sid, context)
            
            # Generate greeting message using cache
            clinic_name = clinic.clinic_name
            cached_message = await self._get_cached_message(
                intent="greeting",
                language="en",  # Default to English, could be dynamic based on caller
                variables={"clinic_name": clinic_name}
            )
            message = cached_message or f"Hello! Thank you for calling {clinic_name}. How can I help you today?"
            
            return CallFlowResponse(
                next_state=CallFlowState.GET_INTENT,
                message=message,
                data={"clinic_name": clinic_name}
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initialize call {call_sid}: {str(e)}")
            raise ValueError(f"Failed to initialize call: {str(e)}")
    
    async def process_user_input(self, call_sid: str, user_input: str) -> CallFlowResponse:
        """
        Process user input and determine next conversation step.
        
        Args:
            call_sid: Call session ID
            user_input: User's speech or text input
            
        Returns:
            Call flow response with next step
        """
        try:
            # Get call context
            context = get_call(call_sid)
            if not context:
                raise ValueError(f"Call {call_sid} not found")
            
            # Add to conversation history
            context.conversation_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_input": user_input,
                "state": context.current_state
            })
            
            # Process based on current state
            if context.current_state == CallFlowState.GET_INTENT:
                response = await self._process_intent(context, user_input)
            elif context.current_state == CallFlowState.IDENTIFY_PATIENT:
                response = self._process_patient_identification(context, user_input)
            elif context.current_state == CallFlowState.NEW_PATIENT_INFO:
                response = self._process_new_patient_info(context, user_input)
            elif context.current_state == CallFlowState.RETURNING_PATIENT_INFO:
                response = await self._process_returning_patient_info(context, user_input)
            elif context.current_state == CallFlowState.SELECT_PROVIDER:
                response = await self._process_provider_selection(context, user_input)
            elif context.current_state == CallFlowState.SELECT_DATE:
                response = self._process_date_selection(context, user_input)
            elif context.current_state == CallFlowState.SELECT_TIME:
                response = self._process_time_selection(context, user_input)
            elif context.current_state == CallFlowState.CONFIRM_DETAILS:
                response = await self._process_confirmation(context, user_input)
            elif context.current_state == CallFlowState.POST_BOOKING_HELP:
                response = await self._process_post_booking_help(context, user_input)
            elif context.current_state == CallFlowState.CANCEL_APPOINTMENT:
                response = self._process_cancellation(context, user_input)
            elif context.current_state == CallFlowState.INSURANCE_INQUIRY:
                response = CallFlowResponse(
                    next_state=CallFlowState.TRANSFER_TO_HUMAN,
                    message="Transferring you to our insurance department. Please hold.",
                    is_complete=True
                )
            elif context.current_state == CallFlowState.DOCTOR_INQUIRY:
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
            
            # Update context state
            context.current_state = response.next_state
            context.updated_at = datetime.now(timezone.utc)
            
            return response
                
        except Exception as e:
            self.logger.error(f"Failed to process input for call {call_sid}: {str(e)}")
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message="I'm sorry, I'm having trouble understanding. Let me transfer you to our staff.",
                is_complete=True
            )
    
    async def _process_intent(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """
        Process user intent using natural language processing.
        
        Uses advanced pattern matching and context awareness to understand
        user intent more naturally and flexibly.
        """
        # Process input with natural language processor
        result = self.nlp.process_input(user_input, {
            'current_state': context.current_state.value if context.current_state else None,
            'call_type': context.call_type
        })
        
        # Handle different intents based on confidence and context
        if result.confidence >= 0.7:  # High confidence
            return self._handle_high_confidence_intent(result, context)
        elif result.confidence >= 0.4:  # Medium confidence
            return self._handle_medium_confidence_intent(result, context)
        else:  # Low confidence or unclear
            return self._handle_unclear_intent(result, context)

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
            return CallFlowResponse(
                next_state=CallFlowState.INSURANCE_INQUIRY,
                message="I'll connect you with our staff who can help with insurance matters. Please hold while I transfer you.",
                data={"intent": "insurance_inquiry"},
                is_complete=True
            )
        
        elif result.intent == IntentType.DOCTOR_INQUIRY:
            context.call_type = "doctor_inquiry"
            return CallFlowResponse(
                next_state=CallFlowState.DOCTOR_INQUIRY,
                message="I'll connect you with our medical staff. Please hold while I transfer you.",
                data={"intent": "doctor_inquiry"},
                is_complete=True
            )
        
        elif result.intent == IntentType.EMERGENCY:
            context.call_type = "emergency"
            return CallFlowResponse(
                next_state=CallFlowState.EMERGENCY_ROUTING,
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
        
        # Default for high confidence but unknown intent
        return CallFlowResponse(
            next_state=CallFlowState.GET_INTENT,
            message="I understand you need help, but I'm not sure exactly what you need. Could you tell me more about what you're looking for?",
            data={"intent": "unclear"}
        )

    def _handle_medium_confidence_intent(self, result, context: CallFlowContext) -> CallFlowResponse:
        """Handle medium confidence intent detection with clarification"""
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
            return self._handle_unclear_intent(result, context)

    def _handle_unclear_intent(self, result, context: CallFlowContext) -> CallFlowResponse:
        """Handle unclear or low confidence intent detection"""
        return CallFlowResponse(
            next_state=CallFlowState.GET_INTENT,
            message="I'm not sure I understand. Could you please tell me what you need help with today? You can say things like 'I need to book an appointment', 'I want to cancel my appointment', or 'I have an insurance question'.",
            data={"intent": "unclear"}
        )
    
    def _process_patient_identification(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process patient name and ask if they've been before."""
        # Use natural language processor to extract name
        result = self.nlp.process_input(user_input)
        name = result.entities.name or self._extract_name(user_input)
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
    
    async def _process_returning_patient_info(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process returning patient response and get appointment details."""
        # Use natural language processor to understand response
        result = self.nlp.process_input(user_input)
        
        if self.nlp.is_confirmation(user_input):
            context.is_returning_patient = True
            
            # Try to find existing patient
            patient_result = self._identify_patient(context.patient_name)
            if patient_result.is_found:
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
            else:
                # Patient says they've been before but not found - treat as new
                return CallFlowResponse(
                    next_state=CallFlowState.NEW_PATIENT_INFO,
                    message="I don't see you in our system yet. Let me get some information to set up your appointment. What's your date of birth?",
                    data={"patient_found": False}
                )
        
        elif self.nlp.is_negation(user_input):
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
    
    def _process_new_patient_info(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process new patient information collection."""
        if not context.patient_dob:
            # Collect date of birth using natural language processor
            result = self.nlp.process_input(user_input)
            dob = result.entities.date_of_birth or self._extract_date_of_birth(user_input)
            if dob:
                context.patient_dob = dob
                return CallFlowResponse(
                    next_state=CallFlowState.NEW_PATIENT_INFO,
                    message="Thank you. What's your insurance provider?",
                    data={"dob_collected": True}
                )
            else:
                return CallFlowResponse(
                    next_state=CallFlowState.NEW_PATIENT_INFO,
                    message="I need your date of birth. Please tell me your date of birth, for example, January 15th, 1990.",
                    requires_input=True
                )
        
        elif not context.insurance_provider:
            # Collect insurance provider using natural language processor
            result = self.nlp.process_input(user_input)
            insurance = result.entities.insurance_provider or self._extract_insurance_provider(user_input)
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
        providers = self._get_available_providers(context.clinic_id)
        
        # Try to match user input to a provider using natural language processor
        result = self.nlp.process_input(user_input)
        provider_name = result.entities.provider_name
        if provider_name:
            selected_provider = self._match_provider(provider_name, providers)
        else:
            selected_provider = self._match_provider(user_input, providers)
        
        if selected_provider:
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
    
    def _process_date_selection(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process date selection."""
        # Get available dates for the provider
        available_dates = self._get_available_dates(context.provider_id)
        
        user_input_lower = user_input.lower()
        
        # Check if user is asking for available dates using natural language processing
        result = self.nlp.process_input(user_input)
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
            if available_dates:
                # Select the first available date
                selected_date = available_dates[0]
                context.appointment_date = selected_date.date
                return CallFlowResponse(
                    next_state=CallFlowState.SELECT_TIME,
                    message=f"Great! {selected_date.day_name} works. What time would you prefer?",
                    data={"date_selected": selected_date.dict()}
                )
        
        # Try to match user input to a date
        selected_date = self._match_date(user_input, available_dates, context)
        
        if selected_date:
            context.appointment_date = selected_date.date
            
            # Check if user also mentioned a time in the same response
            available_times = self._get_available_times(context.provider_id, selected_date.date)
            selected_time = self._match_time(user_input, available_times)
            
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
    
    def _process_time_selection(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process time selection."""
        # Get available time slots for the selected date
        available_times = self._get_available_times(context.provider_id, context.appointment_date)
        
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
        selected_time = self._match_time(user_input, available_times)
        
        if selected_time:
            context.appointment_time = selected_time.start_time
            return CallFlowResponse(
                next_state=CallFlowState.CONFIRM_DETAILS,
                message=f"Perfect! {selected_time.start_time.strftime('%I:%M %p')} works. Let me confirm your appointment details.",
                data={"time_selected": selected_time.dict()}
            )
        
        # Check if user is confirming a suggested time (only if no time was matched)
        if any(word in user_input_lower for word in ["yes", "yeah", "correct", "that works", "perfect", "good"]):
            if available_times:
                # Select the first available time
                selected_time = available_times[0]
                context.appointment_time = selected_time.start_time
                return CallFlowResponse(
                    next_state=CallFlowState.CONFIRM_DETAILS,
                    message=f"Perfect! {selected_time.start_time.strftime('%I:%M %p')} works. Let me confirm your appointment details.",
                    data={"time_selected": selected_time.dict()}
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
            # Book the appointment
            try:
                appointment = self._book_appointment(context)
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
            provider = self._get_provider(context.provider_id)
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
        result = self.nlp.process_input(user_input)
        
        # Check for "nothing else" or similar phrases
        if self.nlp.is_goodbye(user_input) or self.nlp.is_negation(user_input):
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message="Perfect! Thank you for calling St. Peters Medical Center. Have a great day!",
                is_complete=True
            )
        
        # Check for "yes" or similar phrases
        if self.nlp.is_confirmation(user_input):
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
    
    def _process_cancellation(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
        """Process appointment cancellation."""
        user_input_lower = user_input.lower()
        
        # If this is the first input, it should be the patient name
        if not context.patient_name:
            # Extract patient name
            patient_name = self._extract_name(user_input)
            if patient_name:
                context.patient_name = patient_name
                
                # Try to find the patient
                patient_result = self._identify_patient(patient_name)
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
            # TODO: Implement actual cancellation logic
            return CallFlowResponse(
                next_state=CallFlowState.GOODBYE,
                message="I'll cancel your appointment. You'll receive a confirmation shortly. Thank you for calling St. Peters Medical Center. Have a great day!",
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
    
    def _identify_patient(self, patient_name: str) -> PatientIdentificationResult:
        """Try to identify patient by name."""
        # Simple name matching (in production, use fuzzy matching)
        patients = self.db.query(Patient).filter(
            Patient.name_token.ilike(f"%{patient_name}%")
        ).all()
        
        if patients:
            # Return first match (in production, use confidence scoring)
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
    
    def _get_available_providers(self, clinic_id: str) -> List[ProviderOption]:
        """Get available providers for the clinic."""
        providers = self.db.query(Provider).filter(
            Provider.is_available == YesNo.YES.value
        ).all()
        
        return [
            ProviderOption(
                provider_id=p.provider_id,
                name=p.name_token,
                title=p.title,
                specialty=p.specialty,
                is_available=True
            )
            for p in providers
        ]
    
    def _get_available_dates(self, provider_id: str) -> List[DateOption]:
        """Get available dates for a provider."""
        # Get next 14 days
        start_date = datetime.now() + timedelta(days=1)
        end_date = start_date + timedelta(days=14)
        
        available_dates = []
        current_date = start_date
        
        while current_date <= end_date:
            # Only include weekdays (Monday=0, Sunday=6)
            if current_date.weekday() < 5:  # Monday=0, Tuesday=1, ..., Friday=4
                # Check if provider has slots on this date
                slots = self.db.query(AppointmentSlot).filter(
                    AppointmentSlot.provider_id == provider_id,
                    AppointmentSlot.slot_datetime >= current_date,
                    AppointmentSlot.slot_datetime < current_date + timedelta(days=1),
                    AppointmentSlot.is_booked == YesNo.NO.value
                ).count()
                
                if slots > 0:
                    available_dates.append(DateOption(
                        date=current_date.date(),
                        day_name=current_date.strftime('%A'),
                        is_available=True,
                        available_slots=slots
                    ))
            
            current_date += timedelta(days=1)
        
        return available_dates
    
    def _get_available_times(self, provider_id: str, appointment_date: date) -> List[TimeSlotOption]:
        """Get available time slots for a provider on a specific date."""
        start_of_day = datetime.combine(appointment_date, datetime.min.time())
        end_of_day = start_of_day + timedelta(days=1)
        
        slots = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime >= start_of_day,
            AppointmentSlot.slot_datetime < end_of_day,
            AppointmentSlot.is_booked == "no"
        ).order_by(AppointmentSlot.slot_datetime).all()
        
        return [
            TimeSlotOption(
                slot_id=slot.slot_id,
                start_time=slot.slot_datetime,
                end_time=slot.slot_datetime + timedelta(minutes=slot.duration_minutes),
                duration_minutes=slot.duration_minutes,
                is_available=True
            )
            for slot in slots
        ]
    
    def _book_appointment(self, context: CallFlowContext) -> Any:
        """Book the appointment using the appointment service."""
        # Create or find patient
        if not context.patient_id:
            # Create new patient
            patient_id = f"PATIENT_{make_ulid_token('PATIENT')[:12]}"
            patient = Patient(
                patient_id=patient_id,
                name_token=context.patient_name,
                dob_token=context.patient_dob,
                insurance_provider_token=context.insurance_provider
            )
            self.db.add(patient)
            self.db.flush()
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
        
        appointment, google_event_id = self.appointment_service.create_appointment(
            appointment_data, context.patient_name
        )
        
        return appointment
    
    def _extract_name(self, text: str) -> Optional[str]:
        """Extract name from user input with better natural language processing."""
        # Remove common prefixes and suffixes
        text = text.lower().strip()
        
        # Remove common phrases
        prefixes_to_remove = [
            "my name is", "i'm", "i am", "this is", "it's", "it is",
            "call me", "i go by", "you can call me"
        ]
        
        for prefix in prefixes_to_remove:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        
        # Remove common suffixes
        suffixes_to_remove = [
            "speaking", "here", "on the phone", "calling"
        ]
        
        for suffix in suffixes_to_remove:
            if text.endswith(suffix):
                text = text[:-len(suffix)].strip()
                break
        
        # Extract name (first two words, capitalized)
        words = text.split()
        if len(words) >= 2:
            name = " ".join(words[:2])
            return name.title()
        elif len(words) == 1:
            return words[0].title()
        
        return None
    
    def _extract_date_of_birth(self, text: str) -> Optional[str]:
        """Extract date of birth from user input."""
        # Simple DOB extraction (in production, use date parsing)
        # Look for patterns like "January 15th, 1990" or "01/15/1990"
        dob_patterns = [
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{1,2}-\d{1,2}-\d{4})',
            r'(\w+ \d{1,2}(?:st|nd|rd|th)?,? \d{4})',
            r'(\w+ \d{1,2},? \d{4})',  # For speech: "January 15, 1990"
            r'(\d{1,2} \w+ \d{4})'     # For speech: "15 January 1990"
        ]
        
        for pattern in dob_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_insurance_provider(self, text: str) -> Optional[str]:
        """Extract insurance provider from user input with better NLP."""
        text_lower = text.lower().strip()
        
        # Remove common phrases
        phrases_to_remove = [
            "my insurance is", "i have", "i'm with", "i use", "my provider is",
            "i'm covered by", "covered by", "insurance provider", "insurance company"
        ]
        
        for phrase in phrases_to_remove:
            if phrase in text_lower:
                text_lower = text_lower.replace(phrase, "").strip()
                break
        
        # If no common phrases were found, try to extract the insurance name directly
        if not text_lower:
            return None
            
        # Check for known insurance providers first
        insurance_mappings = {
            "blue cross": ["blue cross", "blue cross blue shield", "bcbs", "blue cross blue shield"],
            "aetna": ["aetna", "aetna better health"],
            "medicare": ["medicare", "medicare advantage"],
            "medicaid": ["medicaid", "state insurance"],
            "cigna": ["cigna", "cigna health"],
            "humana": ["humana", "humana health"],
            "kaiser": ["kaiser", "kaiser permanente", "kp"],
            "united": ["united healthcare", "united health", "uhc"],
            "anthem": ["anthem", "anthem blue cross"],
            "tricare": ["tricare", "military insurance"]
        }
        
        for provider, keywords in insurance_mappings.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return provider.title()
        
        # If no known provider found, accept the cleaned input as the insurance provider
        # Capitalize first letter of each word
        return text_lower.title()
    
    def _match_provider(self, user_input: str, providers: List[ProviderOption]) -> Optional[ProviderOption]:
        """Match user input to a provider with better NLP."""
        user_input_lower = user_input.lower().strip()
        
        # Remove common phrases
        phrases_to_remove = [
            "i'd like to see", "i want to see", "i need to see", "can i see",
            "i would like", "i want", "i need", "book with", "schedule with",
            "make an appointment with", "see", "visit"
        ]
        
        for phrase in phrases_to_remove:
            if phrase in user_input_lower:
                user_input_lower = user_input_lower.replace(phrase, "").strip()
                break
        
        # Try exact matches first
        for provider in providers:
            provider_name_lower = provider.name.lower()
            provider_specialty_lower = provider.specialty.lower()
            
            # Check for exact name match
            if provider_name_lower in user_input_lower:
                return provider
            
            # Check for last name match (common in speech)
            last_name = provider_name_lower.split()[-1] if " " in provider_name_lower else provider_name_lower
            if last_name in user_input_lower:
                return provider
            
            # Check for specialty match
            if provider_specialty_lower in user_input_lower:
                return provider
        
        # Try partial matches
        for provider in providers:
            provider_name_lower = provider.name.lower()
            provider_specialty_lower = provider.specialty.lower()
            
            # Check if any word from provider name is in input
            provider_words = provider_name_lower.split()
            for word in provider_words:
                if len(word) > 3 and word in user_input_lower:  # Avoid short words
                    return provider
        
        return None
    
    def _match_date(self, user_input: str, dates: List[DateOption], context: CallFlowContext = None) -> Optional[DateOption]:
        """Match user input to a date with context awareness."""
        user_input_lower = user_input.lower()
        
        # Handle relative references like "the 13th", "13th", "the 15th"
        import re
        day_match = re.search(r'(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?', user_input_lower)
        if day_match:
            day_number = int(day_match.group(1))
            
            # First try to match from context (last mentioned dates)
            if context and context.last_mentioned_dates:
                for mentioned_date in context.last_mentioned_dates:
                    if mentioned_date.day == day_number:
                        # Find the corresponding DateOption
                        for date_option in dates:
                            if date_option.date == mentioned_date:
                                return date_option
            
            # Fallback to matching from available dates
            for date_option in dates:
                if date_option.date.day == day_number:
                    return date_option
        
        # Handle day names (Monday, Tuesday, etc.)
        for date_option in dates:
            if date_option.day_name.lower() in user_input_lower:
                return date_option
        
        # Handle full date formats (October 13, Oct 13, etc.)
        for date_option in dates:
            if (date_option.date.strftime('%B %d').lower() in user_input_lower or
                date_option.date.strftime('%b %d').lower() in user_input_lower):
                return date_option
        
        return None
    
    def _match_time(self, user_input: str, times: List[TimeSlotOption]) -> Optional[TimeSlotOption]:
        """Match user input to a time with better NLP and natural language support."""
        import re
        user_input_lower = user_input.lower().strip()
        
        # First check if the input contains time-related keywords or time words
        time_keywords = ['am', 'pm', 'morning', 'afternoon', 'evening', 'o\'clock', 'oclock', 'time']
        time_words = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve']
        has_time_keywords = any(keyword in user_input_lower for keyword in time_keywords)
        has_time_words = any(word in user_input_lower for word in time_words)
        
        # If no time keywords, time words, or explicit time patterns, don't try to match
        if not has_time_keywords and not has_time_words and not re.search(r'\d{1,2}:\d{2}', user_input_lower):
            return None
        
        # Remove common phrases
        phrases_to_remove = [
            "would be perfect", "works for me", "is good", "sounds good",
            "that works", "i'll take", "i want", "i'd like", "i need",
            "in the afternoon", "in the morning", "in the evening"
        ]
        
        for phrase in phrases_to_remove:
            if phrase in user_input_lower:
                user_input_lower = user_input_lower.replace(phrase, "").strip()
                break
        
        # Handle natural language time expressions
        
        # Convert word numbers to digits (one -> 1, two -> 2, etc.)
        word_to_number = {
            'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
            'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
            'eleven': '11', 'twelve': '12'
        }
        
        for word, number in word_to_number.items():
            user_input_lower = user_input_lower.replace(word, number)
        
        # Handle "1 PM", "1:00 PM", "1:30 PM" patterns - be more strict
        time_patterns = [
            (r'(\d{1,2}):(\d{2})\s*(am|pm)', 3),  # "1:30 PM" - 3 groups
            (r'(\d{1,2})\s*(am|pm)', 2),          # "1 PM" - 2 groups
            (r'(\d{1,2}):(\d{2})', 2),            # "1:30" - 2 groups
        ]
        
        # Use the single digit pattern if there are time keywords or time words
        if has_time_keywords or has_time_words:
            time_patterns.append((r'(\d{1,2})', 1))  # "1" or "nine" - 1 group
        
        for pattern, expected_groups in time_patterns:
            match = re.search(pattern, user_input_lower)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if expected_groups > 1 and match.group(2) and match.group(2).isdigit() else 0
                period = match.group(3) if expected_groups > 2 and match.group(3) else None
                
                # Convert to 24-hour format
                if period == 'pm' and hour != 12:
                    hour += 12
                elif period == 'am' and hour == 12:
                    hour = 0
                elif period is None:
                    # No AM/PM specified - assume morning for medical appointments
                    # If hour is 1-11, assume AM; if 12, assume PM; if 13-23, assume PM
                    if hour == 12:
                        hour = 12  # 12 PM (noon)
                    elif hour > 12:
                        hour = hour  # Already in 24-hour format
                    else:
                        hour = hour  # 1-11 AM
                
                # Find exact matching time slot first
                for time_option in times:
                    if time_option.start_time.hour == hour and time_option.start_time.minute == minute:
                        return time_option
                
                # If no exact match, find the closest available time
                if times:
                    # Find the closest time slot, preferring later times when there's a tie
                    target_time = hour * 60 + minute  # Convert to minutes for comparison
                    closest_time = min(times, key=lambda t: (abs(t.start_time.hour * 60 + t.start_time.minute - target_time), -t.start_time.hour * 60 - t.start_time.minute))
                    return closest_time
        
        return None
    
    def _get_provider(self, provider_id: str) -> Provider:
        """Get provider by ID."""
        return self.db.query(Provider).filter_by(provider_id=provider_id).first()
    
    def _tokenize_phone(self, phone: str) -> str:
        """Tokenize phone number."""
        # Simple tokenization (in production, use proper tokenization service)
        return f"PHONE_{hash(phone) % 100000:05d}"
    
    def get_call_status(self, call_sid: str) -> Optional[CallFlowContext]:
        """Get current call status."""
        return get_call(call_sid)
    
    def end_call(self, call_sid: str) -> bool:
        """End the call and clean up."""
        try:
            # Update call record
            call = self.db.query(Call).filter_by(call_sid=call_sid).first()
            if call:
                call.status = "completed"
                call.ended_at = datetime.now(timezone.utc)
                self.db.commit()
            
            # Remove from active calls
            remove_call(call_sid)
            
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
        Get cached message for given intent and language.
        
        Args:
            intent: Intent type
            language: Language code
            variables: Template variables
            
        Returns:
            Optional[str]: Cached message if found, None otherwise
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
            from services.bilingual_manager import LanguageCode
            language_code = LanguageCode.ENGLISH if language == "en" else LanguageCode.SPANISH
            
            # Check if template exists
            if self.response_templates.has_template(intent_type, language_code):
                # Use template with variable substitution
                template_response = self.response_templates.substitute_variables(
                    intent_type, language_code, variables or {}
                )
                if template_response:
                    # Cache the response
                    await self.response_cache.cache_response(
                        intent=intent,
                        language=language,
                        response=template_response,
                        template=self.response_templates.get_template(intent_type, language_code).template,
                        variables=variables,
                        source="template"
                    )
                    return template_response
            
            # Try cache for existing responses
            cached_response = await self.response_cache.get_cached_response(
                intent=intent,
                language=language,
                variables=variables
            )
            
            return cached_response
            
        except Exception as e:
            self.logger.warning(f"Error getting cached message: {e}")
            return None
