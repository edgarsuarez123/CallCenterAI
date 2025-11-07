"""
Call Flow Models
Defines the conversation states and data structures for the call flow system.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, date


class CallFlowState(str, Enum):
    """States in the call conversation flow."""
    GREETING = "greeting"
    GET_INTENT = "get_intent"
    IDENTIFY_PATIENT = "identify_patient"
    NEW_PATIENT_INFO = "new_patient_info"
    RETURNING_PATIENT_INFO = "returning_patient_info"
    SELECT_PROVIDER = "select_provider"
    SELECT_DATE = "select_date"
    SELECT_TIME = "select_time"
    CONFIRM_DETAILS = "confirm_details"
    BOOKING_COMPLETE = "booking_complete"
    POST_BOOKING_HELP = "post_booking_help"
    CANCEL_APPOINTMENT = "cancel_appointment"
    INSURANCE_INQUIRY = "insurance_inquiry"
    PROVIDER_INQUIRY = "provider_inquiry"
    GOODBYE = "goodbye"
    TRANSFER_TO_HUMAN = "transfer_to_human"


class CallFlowResponse(BaseModel):
    """Response from call flow processing."""
    next_state: CallFlowState
    message: str
    options: List[str] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)
    requires_input: bool = True
    is_complete: bool = False


class CallFlowContext(BaseModel):
    """Context data maintained throughout the call."""
    call_sid: str
    current_state: CallFlowState
    clinic_id: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_dob: Optional[str] = None
    insurance_provider: Optional[str] = None
    provider_id: Optional[str] = None
    appointment_date: Optional[date] = None
    appointment_time: Optional[datetime] = None
    appointment_type: str = "consultation"
    is_returning_patient: Optional[bool] = None
    call_type: str = "appointment_booking"  # appointment_booking, cancellation, insurance_inquiry, doctor_inquiry
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    # Context for interpreting relative references
    last_mentioned_dates: List[date] = Field(default_factory=list)
    last_mentioned_times: List[datetime] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CallSimulationRequest(BaseModel):
    """Request to start a call simulation."""
    caller_phone: str = Field(..., description="Caller's phone number")
    clinic_id: str = Field(..., description="Clinic ID for the call")
    caller_name: Optional[str] = Field(None, description="Caller's name (optional)")


class CallInputRequest(BaseModel):
    """Request to process user input during a call."""
    user_input: str = Field(..., description="User's speech or text input")


class CallStatusResponse(BaseModel):
    """Response with current call status."""
    call_sid: str
    current_state: CallFlowState
    message: str
    options: List[str] = Field(default_factory=list)
    requires_input: bool = True
    is_complete: bool = False
    context: CallFlowContext


class AppointmentBookingData(BaseModel):
    """Data collected for appointment booking."""
    patient_name: str
    patient_dob: Optional[str] = None
    insurance_provider: Optional[str] = None
    provider_id: str
    appointment_date: datetime
    appointment_time: datetime
    appointment_type: str = "consultation"
    is_returning_patient: bool = False


class PatientIdentificationResult(BaseModel):
    """Result of patient identification attempt."""
    is_found: bool
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    confidence: float = 0.0
    match_reason: Optional[str] = None
    multiple_matches: bool = False  # Issue 43: Indicate if multiple matches were found


class ProviderOption(BaseModel):
    """Provider option for selection."""
    provider_id: str
    name: str
    title: str
    specialty: str
    is_available: bool = True


class TimeSlotOption(BaseModel):
    """Time slot option for selection."""
    slot_id: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    is_available: bool = True


class DateOption(BaseModel):
    """Date option for selection."""
    date: date
    day_name: str
    is_available: bool = True
    available_slots: int = 0
