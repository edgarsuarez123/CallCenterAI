import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

# ============================================================================
# ENUMS
# ============================================================================

class YesNo(str, Enum):
    YES = "yes"
    NO = "no"

class CallStatus(str, Enum):
    RINGING = "ringing"
    ANSWERED = "answered"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"

class PriorityLevel(str, Enum):
    NORMAL = "normal"
    EMERGENCY = "emergency"

class SubscriptionTier(str, Enum):
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"

class LicenseStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"

# ============================================================================
# EXISTING TOKENIZATION SCHEMAS
# ============================================================================

class TokenizeRequest(BaseModel):
    call_id: str = Field(..., min_length=3, max_length=64)
    text: str = Field(..., min_length=1)
    mode: str = Field("strict")  # future: "lenient" to bypass 422 on residual

class TokenizeResponse(BaseModel):
    text_tokenized: str
    tokens: list[str]
    safety: dict

class HydrateRequest(BaseModel):
    text_tokenized: str

class HydrateResponse(BaseModel):
    text_hydrated: str
    missing_tokens: list[str]

# ============================================================================
# CLINIC MANAGEMENT SCHEMAS
# ============================================================================

class ClinicCreateRequest(BaseModel):
    clinic_name: str = Field(..., min_length=1, max_length=200)
    phone_number: str = Field(..., min_length=10, max_length=20)
    timezone: str = Field(default="America/New_York", max_length=50)
    default_language: str = Field(default="en", max_length=10)
    supported_languages: str = Field(default="en,es", max_length=100)
    ehr_system: str = Field(..., min_length=1, max_length=50)
    ehr_api_endpoint: Optional[str] = Field(None, max_length=500)
    ehr_credentials_vault_key: Optional[str] = Field(None, max_length=200)
    max_concurrent_calls: int = Field(default=10, ge=1, le=100)
    queue_timeout_seconds: int = Field(default=45, ge=10, le=300)
    subscription_tier: SubscriptionTier = Field(default=SubscriptionTier.BASIC)
    
    @field_validator('phone_number')
    @classmethod
    def validate_phone_number(cls, v):
        # Basic phone number validation
        if not v.startswith('+'):
            raise ValueError('Phone number must start with +')
        return v

class ClinicUpdateRequest(BaseModel):
    clinic_name: Optional[str] = Field(None, min_length=1, max_length=200)
    phone_number: Optional[str] = Field(None, min_length=10, max_length=20)
    timezone: Optional[str] = Field(None, max_length=50)
    default_language: Optional[str] = Field(None, max_length=10)
    supported_languages: Optional[str] = Field(None, max_length=100)
    ehr_system: Optional[str] = Field(None, min_length=1, max_length=50)
    ehr_api_endpoint: Optional[str] = Field(None, max_length=500)
    ehr_credentials_vault_key: Optional[str] = Field(None, max_length=200)
    max_concurrent_calls: Optional[int] = Field(None, ge=1, le=100)
    queue_timeout_seconds: Optional[int] = Field(None, ge=10, le=300)
    subscription_tier: Optional[SubscriptionTier] = None
    is_active: Optional[YesNo] = None

class ClinicResponse(BaseModel):
    clinic_id: str
    clinic_name: str
    phone_number: str
    timezone: str
    default_language: str
    supported_languages: str
    ehr_system: str
    ehr_api_endpoint: Optional[str]
    ehr_credentials_vault_key: Optional[str]
    max_concurrent_calls: int
    queue_timeout_seconds: int
    subscription_tier: str
    is_active: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# PROVIDER MANAGEMENT SCHEMAS
# ============================================================================

class ProviderCreateRequest(BaseModel):
    name_token: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=20)
    specialty: str = Field(..., min_length=1, max_length=100)
    license_number: Optional[str] = Field(None, max_length=50)
    npi_number: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    
    @field_validator('npi_number')
    @classmethod
    def validate_npi_number(cls, v):
        if v and not v.isdigit():
            raise ValueError('NPI number must contain only digits')
        return v

class ProviderUpdateRequest(BaseModel):
    name_token: Optional[str] = Field(None, min_length=1, max_length=64)
    title: Optional[str] = Field(None, min_length=1, max_length=20)
    specialty: Optional[str] = Field(None, min_length=1, max_length=100)
    license_number: Optional[str] = Field(None, max_length=50)
    npi_number: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    is_available: Optional[YesNo] = None

class ProviderResponse(BaseModel):
    provider_id: str
    name_token: str
    title: str
    specialty: str
    license_number: Optional[str]
    npi_number: Optional[str]
    is_available: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# PATIENT MANAGEMENT SCHEMAS
# ============================================================================

class PatientCreateRequest(BaseModel):
    first_name_token: str = Field(..., min_length=1, max_length=64)
    last_name_token: str = Field(..., min_length=1, max_length=64)
    phone_token: str = Field(..., min_length=1, max_length=64)
    email_token: Optional[str] = Field(None, max_length=64)
    date_of_birth_token: Optional[str] = Field(None, max_length=64)
    insurance_provider_token: Optional[str] = Field(None, max_length=64)
    insurance_member_id_token: Optional[str] = Field(None, max_length=64)
    insurance_plan_type: Optional[str] = Field(None, max_length=50)

class PatientUpdateRequest(BaseModel):
    first_name_token: Optional[str] = Field(None, min_length=1, max_length=64)
    last_name_token: Optional[str] = Field(None, min_length=1, max_length=64)
    phone_token: Optional[str] = Field(None, min_length=1, max_length=64)
    email_token: Optional[str] = Field(None, max_length=64)
    date_of_birth_token: Optional[str] = Field(None, max_length=64)
    insurance_provider_token: Optional[str] = Field(None, max_length=64)
    insurance_member_id_token: Optional[str] = Field(None, max_length=64)
    insurance_plan_type: Optional[str] = Field(None, max_length=50)

class PatientResponse(BaseModel):
    patient_id: str
    first_name_token: str
    last_name_token: str
    phone_token: str
    email_token: Optional[str]
    date_of_birth_token: Optional[str]
    insurance_provider_token: Optional[str]
    insurance_member_id_token: Optional[str]
    insurance_plan_type: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# APPOINTMENT MANAGEMENT SCHEMAS
# ============================================================================

class AppointmentCreateRequest(BaseModel):
    patient_id: str = Field(..., min_length=1, max_length=64)
    provider_id: str = Field(..., min_length=1, max_length=64)
    appointment_date: datetime = Field(...)
    start_time: datetime = Field(...)
    end_time: datetime = Field(...)
    appointment_type: str = Field(..., min_length=1, max_length=50)
    notes_token: Optional[str] = Field(None, max_length=64)
    
    @field_validator('end_time')
    @classmethod
    def validate_end_time(cls, v, values):
        if 'start_time' in values and v <= values['start_time']:
            raise ValueError('End time must be after start time')
        return v

class AppointmentUpdateRequest(BaseModel):
    provider_id: Optional[str] = Field(None, min_length=1, max_length=64)
    appointment_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    appointment_type: Optional[str] = Field(None, min_length=1, max_length=50)
    notes_token: Optional[str] = Field(None, max_length=64)
    status: Optional[str] = Field(None, max_length=20)

class AppointmentResponse(BaseModel):
    appointment_id: str
    patient_id: str
    provider_id: str
    appointment_date: datetime
    start_time: datetime
    end_time: datetime
    appointment_type: str
    notes_token: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# APPOINTMENT SLOT SCHEMAS
# ============================================================================

class AppointmentSlotCreateRequest(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=64)
    slot_datetime: datetime = Field(...)
    duration_minutes: int = Field(..., ge=15, le=480)  # 15 min to 8 hours
    clinic_id: str = Field(..., min_length=1, max_length=64)

class AppointmentSlotUpdateRequest(BaseModel):
    slot_datetime: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, ge=15, le=480)
    is_booked: Optional[YesNo] = None
    booked_by_appointment_id: Optional[str] = Field(None, max_length=64)
    held_until: Optional[datetime] = None
    held_by_call_sid: Optional[str] = Field(None, max_length=64)

class AppointmentSlotResponse(BaseModel):
    slot_id: str
    provider_id: str
    slot_datetime: datetime
    duration_minutes: int
    is_booked: str
    booked_by_appointment_id: Optional[str]
    held_until: Optional[datetime]
    held_by_call_sid: Optional[str]
    clinic_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# CALL MANAGEMENT SCHEMAS
# ============================================================================

class CallCreateRequest(BaseModel):
    call_sid: str = Field(..., min_length=1, max_length=64)
    caller_phone_token: str = Field(..., min_length=1, max_length=64)
    status: CallStatus = Field(default=CallStatus.RINGING)
    patient_id: Optional[str] = Field(None, max_length=64)

class CallUpdateRequest(BaseModel):
    status: Optional[CallStatus] = None
    patient_id: Optional[str] = Field(None, max_length=64)
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = Field(None, ge=0)

class CallResponse(BaseModel):
    call_id: str
    call_sid: str
    caller_phone_token: str
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    patient_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# CALL QUEUE SCHEMAS
# ============================================================================

class CallQueueCreateRequest(BaseModel):
    call_id: str = Field(..., min_length=1, max_length=64)
    clinic_id: str = Field(..., min_length=1, max_length=64)
    priority_level: PriorityLevel = Field(default=PriorityLevel.NORMAL)
    is_emergency: YesNo = Field(default=YesNo.NO)
    emergency_reason: Optional[str] = Field(None, max_length=200)

class CallQueueUpdateRequest(BaseModel):
    priority_level: Optional[PriorityLevel] = None
    is_emergency: Optional[YesNo] = None
    emergency_reason: Optional[str] = Field(None, max_length=200)
    transferred_to_human: Optional[YesNo] = None
    assigned_human_agent: Optional[str] = Field(None, max_length=100)
    ai_processing_started_at: Optional[datetime] = None
    ai_processing_completed_at: Optional[datetime] = None
    human_transfer_at: Optional[datetime] = None

class CallQueueResponse(BaseModel):
    queue_id: str
    call_id: str
    clinic_id: str
    priority_level: str
    is_emergency: str
    emergency_reason: Optional[str]
    transferred_to_human: str
    assigned_human_agent: Optional[str]
    ai_processing_started_at: Optional[datetime]
    ai_processing_completed_at: Optional[datetime]
    human_transfer_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# SYSTEM CONFIG SCHEMAS
# ============================================================================

class SystemConfigCreateRequest(BaseModel):
    config_key: str = Field(..., min_length=1, max_length=100)
    config_value: str = Field(..., min_length=1, max_length=1000)
    description: Optional[str] = Field(None, max_length=500)

class SystemConfigUpdateRequest(BaseModel):
    config_value: Optional[str] = Field(None, min_length=1, max_length=1000)
    description: Optional[str] = Field(None, max_length=500)

class SystemConfigResponse(BaseModel):
    config_id: str
    config_key: str
    config_value: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# AUDIT LOG SCHEMAS
# ============================================================================

class AuditLogResponse(BaseModel):
    log_id: str
    table_name: str
    record_id: str
    action_type: str
    old_values: Optional[str]
    new_values: Optional[str]
    user_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# CLINIC LICENSE SCHEMAS
# ============================================================================

class ClinicLicenseCreateRequest(BaseModel):
    clinic_id: str = Field(..., min_length=1, max_length=64)
    tier: SubscriptionTier = Field(...)
    max_calls_per_month: Optional[int] = Field(None, ge=1)
    max_concurrent_calls: int = Field(..., ge=1, le=100)
    max_providers: Optional[int] = Field(None, ge=1)
    monthly_fee_usd: float = Field(..., ge=0.0)
    billing_cycle: BillingCycle = Field(default=BillingCycle.MONTHLY)

class ClinicLicenseUpdateRequest(BaseModel):
    tier: Optional[SubscriptionTier] = None
    max_calls_per_month: Optional[int] = Field(None, ge=1)
    max_concurrent_calls: Optional[int] = Field(None, ge=1, le=100)
    max_providers: Optional[int] = Field(None, ge=1)
    monthly_fee_usd: Optional[float] = Field(None, ge=0.0)
    billing_cycle: Optional[BillingCycle] = None
    license_status: Optional[LicenseStatus] = None

class ClinicLicenseResponse(BaseModel):
    license_id: str
    clinic_id: str
    tier: str
    max_calls_per_month: Optional[int]
    max_concurrent_calls: int
    max_providers: Optional[int]
    monthly_fee_usd: float
    billing_cycle: str
    license_status: str
    current_month_calls: int
    billing_cycle_start: datetime
    billing_cycle_end: datetime
    next_billing_date: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# CLINIC USAGE SCHEMAS
# ============================================================================

class ClinicUsageResponse(BaseModel):
    usage_id: str
    clinic_id: str
    billing_period_start: datetime
    billing_period_end: datetime
    total_calls: int
    ai_tokens_used: int
    speech_minutes: float
    telephony_minutes: float
    cost_breakdown: str
    total_cost_usd: float
    invoice_generated: str
    invoice_number: Optional[str]
    payment_status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# BULK OPERATION SCHEMAS
# ============================================================================

class BulkClinicSetupRequest(BaseModel):
    clinics: List[dict] = Field(..., min_items=1, max_items=100)

class BulkClinicSetupResponse(BaseModel):
    total_clinics: int
    successful_clinics: int
    failed_clinics: int
    results: List[dict]

# ============================================================================
# SEARCH AND FILTER SCHEMAS
# ============================================================================

class ClinicSearchRequest(BaseModel):
    clinic_name: Optional[str] = None
    phone_number: Optional[str] = None
    subscription_tier: Optional[SubscriptionTier] = None
    is_active: Optional[YesNo] = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

class ProviderSearchRequest(BaseModel):
    clinic_id: Optional[str] = None
    specialty: Optional[str] = None
    is_available: Optional[YesNo] = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

class AppointmentSearchRequest(BaseModel):
    clinic_id: Optional[str] = None
    patient_id: Optional[str] = None
    provider_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

# ============================================================================
# RESPONSE WRAPPER SCHEMAS
# ============================================================================

class PaginatedResponse(BaseModel):
    items: List[dict]
    total: int
    page: int
    per_page: int
    pages: int

class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[dict] = None

class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[dict] = None