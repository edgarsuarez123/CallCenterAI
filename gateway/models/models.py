from sqlalchemy import Column, String, LargeBinary, DateTime, ForeignKey, Integer, Float, Text, UniqueConstraint, Index, Boolean, text, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import __init__  # keep package marker import happy
from services.database import Base

# Import CallStatus enum for default values
from .enums import CallStatus

# Association table for many-to-many relationship between providers and clinics
provider_clinics = Table(
    'provider_clinics',
    Base.metadata,
    Column('provider_id', String(64), ForeignKey('providers.provider_id', ondelete='CASCADE'), primary_key=True),
    Column('clinic_id', String(64), ForeignKey('clinics.clinic_id', ondelete='CASCADE'), primary_key=True),
    Column('assigned_at', DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column('is_active', String(10), default='yes', nullable=False),
    Index('idx_provider_clinics_provider', 'provider_id'),
    Index('idx_provider_clinics_clinic', 'clinic_id')
)

class Mapping(Base):
    __tablename__ = "mappings"
    token = Column(String(64), primary_key=True)
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this mapping belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new mappings
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    value_nonce = Column(LargeBinary(12), nullable=False)
    value_ciphertext = Column(LargeBinary, nullable=False)
    value_type = Column(String(32), nullable=False)
    call_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of encrypted PHI tokens
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this mapping was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this mapping (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this mapping was deleted (compliance, cleanup, etc.)


class Call(Base):
    """
    Tracks individual phone calls from start to finish.
    Each row represents one phone conversation.
    """
    __tablename__ = "calls"
    
    # ============================================================================
    # PRIMARY IDENTIFIERS
    # ============================================================================
    
    call_sid = Column(String(64), primary_key=True)
    # Twilio's unique identifier for this call (e.g., "CA1234567890abcdef")
    # This comes from Twilio and is their system of record ID
    # Primary key because Twilio guarantees uniqueness
    
    call_id = Column(String(64), nullable=False, unique=True, index=True)
    # Our internal tracking ID (e.g., "CALL_20251010_001")
    # We generate this for our own correlation across logs, tokens, etc.
    # Indexed because we'll frequently query by this ID
    # Unique constraint ensures we don't accidentally create duplicates
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this call belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new calls
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    # ============================================================================
    # CALLER INFORMATION (Tokenized for HIPAA)
    # ============================================================================
    
    caller_phone_token = Column(String(64), nullable=True)
    # The tokenized phone number of the caller (e.g., "PHONE_ABC123")
    # Nullable because: 
    #   - Caller ID might be blocked/unavailable
    #   - Call might fail before we can tokenize
    # References a token in the Mapping table where actual phone is encrypted
    
    # ============================================================================
    # CALL STATUS TRACKING
    # ============================================================================
    
    status = Column(String(20), default=CallStatus.INITIATED.value, nullable=False)
    # Current state of the call. Possible values:
    #   - "initiated": Call received, setting up
    #   - "active": Currently in conversation
    #   - "completed": Call ended normally
    #   - "failed": Technical failure (network, service error)
    #   - "abandoned": Caller hung up before completion
    # Default is "initiated" when call first comes in
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When the call was first received
    # Uses server_default so PostgreSQL automatically sets this
    # Timezone-aware for proper handling across regions
    # Never null - every call has a start time
    
    ended_at = Column(DateTime(timezone=True), nullable=True)
    # When the call ended (any reason: completion, failure, hangup)
    # Nullable because active calls haven't ended yet
    # We'll update this field when call terminates

    # ============================================================================
    # CALLER TYPE DETECTION & ROUTING
    # ============================================================================
    
    detected_caller_type = Column(String(50), nullable=True)
    # Detected caller type: "patient", "physician", "pharmacy", "insurance", "emergency", "unknown"
    
    caller_type_confidence = Column(Float, nullable=True)
    # Confidence score for caller type detection (0.0 - 1.0)
    
    routing_rule_id = Column(String(64), ForeignKey('routing_rules.rule_id', ondelete='SET NULL'), nullable=True)
    # Routing rule applied to this call
    
    assigned_provider_id = Column(String(64), ForeignKey('providers.provider_id', ondelete='SET NULL'), nullable=True)
    # Provider assigned to handle this call
    
    queue_id = Column(String(64), ForeignKey('call_queue.queue_id', ondelete='SET NULL'), nullable=True)
    # Queue this call was placed in (if any)
    
    routing_metadata = Column(Text, nullable=True)
    # JSON metadata about routing decisions and processing
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    # Optional link to patient (if caller is identified as existing patient)
    patient_id = Column(String(64), ForeignKey("patients.patient_id"), nullable=True)
    patient = relationship("Patient", back_populates="calls")
    
    # Routing relationships
    routing_rule = relationship("RoutingRule", back_populates="calls")
    assigned_provider = relationship("Provider", foreign_keys=[assigned_provider_id])
    queue = relationship("CallQueue", foreign_keys=[queue_id], uselist=False)
    queued_call = relationship("QueuedCall", back_populates="call", uselist=False)
    detection_logs = relationship("CallerDetectionLog", back_populates="call")
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of call records containing PHI
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this call was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this call (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this call was deleted (compliance, cleanup, etc.)
    
    # ============================================================================
    # DATABASE INDEXES
    # ============================================================================
    
    __table_args__ = (
        # Performance indexes for call queries
        Index('idx_calls_patient_date', 'patient_id', 'started_at'),
        Index('idx_calls_status_date', 'status', 'started_at'),
        Index('idx_calls_phone_token', 'caller_phone_token'),
    )

class Patient(Base):
    """
    Patient records with tokenized PHI for HIPAA compliance.
    All personally identifiable information is stored as tokens.
    """
    __tablename__ = "patients"
    
    # ============================================================================
    # PRIMARY IDENTIFIERS
    # ============================================================================
    
    patient_id = Column(String(64), primary_key=True)
    # Our internal patient ID (e.g., "PATIENT_20250110_001")
    # Generated by our system for internal tracking
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this patient belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new patients
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    # ============================================================================
    # TOKENIZED PHI (All sensitive data is tokenized)
    # ============================================================================
    
    name_token = Column(String(64), nullable=True)
    # Tokenized full name (e.g., "PATIENT_ABC123")
    # References Mapping table where actual name is encrypted
    
    phone_token = Column(String(64), nullable=True)
    # Tokenized primary phone number (e.g., "PHONE_XYZ789")
    # References Mapping table where actual phone is encrypted
    
    email_token = Column(String(64), nullable=True)
    # Tokenized email address (e.g., "EMAIL_DEF456")
    # References Mapping table where actual email is encrypted
    
    dob_token = Column(String(64), nullable=True)
    # Tokenized date of birth (e.g., "DATE_GHI789")
    # References Mapping table where actual DOB is encrypted
    
    address_token = Column(String(64), nullable=True)
    # Tokenized patient address (e.g., "ADDRESS_ABC123")
    # References Mapping table where actual address is encrypted
    
    # ============================================================================
    # INSURANCE (Most patients have one primary insurance)
    # ============================================================================
    
    insurance_provider_token = Column(String(64), nullable=True)
    # Tokenized insurance provider name (e.g., "INSURANCE_ABC123")
    
    insurance_member_id_token = Column(String(64), nullable=True)
    # Tokenized insurance member ID (e.g., "MEMBER_XYZ789")
    
    insurance_plan_type = Column(String(50), nullable=True)  # HMO, PPO, EPO, etc.
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    # One patient can have many calls
    calls = relationship("Call", back_populates="patient")
    # One patient can have many appointments
    appointments = relationship("Appointment", back_populates="patient")
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of patient records containing PHI
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this patient was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this patient (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this patient was deleted (compliance, cleanup, etc.)
    
    # ============================================================================
    # DATABASE INDEXES
    # ============================================================================
    
    __table_args__ = (
        # Performance indexes for patient queries
        Index('idx_patients_phone_token', 'phone_token'),
        Index('idx_patients_email_token', 'email_token'),
        Index('idx_patients_address_token', 'address_token'),
    )

class Appointment(Base):
    """
    Medical appointments linking patients to calls and providers.
    """
    __tablename__ = "appointments"
    
    appointment_id = Column(String(64), primary_key=True)
    # Our internal appointment ID (e.g., "APPT_20250110_001")
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this appointment belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new appointments
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    # ============================================================================
    # RELATIONSHIPS TO OTHER ENTITIES
    # ============================================================================
    
    patient_id = Column(String(64), ForeignKey("patients.patient_id"), nullable=False)
    provider_id = Column(String(64), ForeignKey("providers.provider_id"), nullable=True)
    call_id = Column(String(64), ForeignKey("calls.call_id"), nullable=True)
    # Optional link to the call that created this appointment
    
    # ============================================================================
    # APPOINTMENT TIMING (Non-PHI for scheduling logic)
    # ============================================================================
    
    appointment_date = Column(DateTime(timezone=True), nullable=True)
    # Actual appointment date and time (non-PHI for scheduling)
    
    start_time = Column(DateTime(timezone=True), nullable=True)
    # Appointment start time
    
    end_time = Column(DateTime(timezone=True), nullable=True)
    # Appointment end time (calculated from start_time + duration_minutes)
    
    # ============================================================================
    # TOKENIZED APPOINTMENT DATA
    # ============================================================================
    
    reason_token = Column(String(64), nullable=True)
    # Tokenized appointment reason/chief complaint
    
    notes_token = Column(String(64), nullable=True)
    # Tokenized appointment notes
    
    # ============================================================================
    # NON-PHI APPOINTMENT DATA
    # ============================================================================
    
    appointment_type = Column(String(50), nullable=True)  # consultation, follow-up, procedure, etc.
    duration_minutes = Column(Integer, default=30, nullable=False)
    status = Column(String(20), default="scheduled", nullable=False)
    # scheduled, confirmed, completed, cancelled, no_show
    
    google_event_id = Column(String(255), nullable=True)
    # Google Calendar event ID for syncing updates/deletions
    
    needs_calendar_sync = Column(Boolean, default=False, nullable=False)
    # Flag to indicate if appointment needs calendar sync (e.g., sync failed during creation)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of appointment records containing PHI
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this appointment was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this appointment (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this appointment was deleted (compliance, cleanup, etc.)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    patient = relationship("Patient", back_populates="appointments")
    provider = relationship("Provider", back_populates="appointments")
    call = relationship("Call", foreign_keys=[call_id])
    reminders = relationship("Reminder", back_populates="appointment")


class AppointmentBlock(Base):
    """
    Manages consistent appointment time blocks for providers.
    Ensures appointments are scheduled in standard time slots.
    """
    __tablename__ = "appointment_blocks"
    
    block_id = Column(String(64), primary_key=True)
    # Our internal block ID (e.g., "BLOCK_20250110_001")
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this appointment block belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new appointment blocks
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    provider_id = Column(String(64), ForeignKey("providers.provider_id"), nullable=False)
    
    # ============================================================================
    # TIME BLOCK DEFINITION
    # ============================================================================
    
    block_date = Column(DateTime(timezone=True), nullable=False)
    # Date for this time block (e.g., 2025-01-10)
    
    start_time = Column(DateTime(timezone=True), nullable=False)
    # Block start time (e.g., 2025-01-10 09:00:00)
    
    end_time = Column(DateTime(timezone=True), nullable=False)
    # Block end time (e.g., 2025-01-10 17:00:00)
    
    # ============================================================================
    # BLOCK CONFIGURATION
    # ============================================================================
    
    slot_duration_minutes = Column(Integer, default=30, nullable=False)
    # Duration of each appointment slot (15, 30, 45, 60 minutes)
    
    break_duration_minutes = Column(Integer, default=0, nullable=False)
    # Break time between appointments
    
    max_appointments = Column(Integer, nullable=True)
    # Maximum number of appointments in this block
    
    # ============================================================================
    # BLOCK STATUS
    # ============================================================================
    
    is_available = Column(String(10), default="yes", nullable=False)
    # yes, no, partially_booked
    
    status = Column(String(20), default="active", nullable=False)
    # active, cancelled, completed
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    provider = relationship("Provider", back_populates="appointment_blocks")
    # One block belongs to one provider


class Provider(Base):
    """
    Healthcare providers (doctors, nurses, staff) that the AI can schedule with.
    """
    __tablename__ = "providers"
    
    provider_id = Column(String(64), primary_key=True)
    # Our internal provider ID (e.g., "PROVIDER_20250110_001")
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this provider belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new providers
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    # ============================================================================
    # TOKENIZED PROVIDER INFO
    # ============================================================================
    
    name_token = Column(String(64), nullable=False)
    # Tokenized provider name (e.g., "PROVIDER_ABC123")
    
    # ============================================================================
    # NON-PHI PROVIDER DATA
    # ============================================================================
    
    title = Column(String(50), nullable=True)  # Dr., Nurse, etc.
    specialty = Column(String(100), nullable=True)  # Cardiology, General Practice, etc.
    email = Column(String(255), nullable=True)  # Provider email for Google Calendar integration
    
    # Availability for AI scheduling
    is_available = Column(String(10), default="yes", nullable=False)  # yes, no, limited
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    # One provider can have many appointments
    appointments = relationship("Appointment", back_populates="provider")
    # One provider can have many appointment blocks
    appointment_blocks = relationship("AppointmentBlock", back_populates="provider")
    # One provider can have Google Calendar credentials
    google_calendar_credentials = relationship("GoogleCalendarCredentials", back_populates="provider", uselist=False)
    # One provider can have capacity information
    capacity = relationship("ProviderCapacity", back_populates="provider", uselist=False)
    # Many-to-many relationship: providers can work at multiple clinics
    clinics = relationship(
        "Clinic",
        secondary=provider_clinics,
        back_populates="providers"
    )


class CallNotes(Base):
    """
    AI-generated summaries and notes from call conversations.
    Tracks patient call history with datetime for when same patient calls multiple times.
    """
    __tablename__ = "call_notes"
    
    notes_id = Column(String(64), primary_key=True)
    # Our internal notes ID (e.g., "NOTES_20250110_001")
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this call note belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new call notes
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    call_id = Column(String(64), ForeignKey("calls.call_id"), nullable=False)
    patient_id = Column(String(64), ForeignKey("patients.patient_id"), nullable=True)
    # Link to patient for tracking call history
    
    # ============================================================================
    # TOKENIZED CALL CONTENT
    # ============================================================================
    
    summary_token = Column(String(64), nullable=True)
    # Tokenized AI-generated call summary
    
    key_points_token = Column(String(64), nullable=True)
    # Tokenized key discussion points from the call
    
    action_items_token = Column(String(64), nullable=True)
    # Tokenized follow-up actions needed
    
    # ============================================================================
    # NON-PHI CALL ANALYSIS
    # ============================================================================
    
    sentiment_score = Column(String(20), nullable=True)  # positive, negative, neutral
    urgency_level = Column(String(20), nullable=True)  # low, medium, high, emergency
    call_duration_seconds = Column(Integer, nullable=True)
    ai_confidence_score = Column(String(20), nullable=True)  # low, medium, high
    
    # Structured data extracted by AI
    symptoms_detected = Column(String(500), nullable=True)  # Comma-separated symptoms
    medications_mentioned = Column(String(500), nullable=True)  # Comma-separated medications
    concerns_raised = Column(String(500), nullable=True)  # Comma-separated concerns
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of call notes containing PHI
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this call note was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this call note (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this call note was deleted (compliance, cleanup, etc.)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    call = relationship("Call", foreign_keys=[call_id])
    patient = relationship("Patient", foreign_keys=[patient_id])


class AuditLog(Base):
    """
    Audit trail for all PHI access and system changes.
    Essential for HIPAA compliance and security monitoring.
    """
    __tablename__ = "audit_logs"
    
    log_id = Column(String(64), primary_key=True)
    # Our internal log ID (e.g., "AUDIT_20250110_001")
    
    # ============================================================================
    # CLINIC ISOLATION (CRITICAL for data security)
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=True, index=True)
    # Which clinic this audit log belongs to - CRITICAL for data isolation
    # Nullable for backward compatibility, but should be set for all new audit logs
    clinic = relationship("Clinic", foreign_keys=[clinic_id])
    
    # ============================================================================
    # AUDIT TRAIL INFORMATION
    # ============================================================================
    
    user_id = Column(String(64), nullable=True)
    # Who performed the action (system, admin, api_key, etc.)
    
    action_type = Column(String(50), nullable=False)
    # create, read, update, delete, tokenize, hydrate, access_phi
    
    table_name = Column(String(50), nullable=True)
    # Which table was affected (patients, calls, mappings, etc.)
    
    record_id = Column(String(64), nullable=True)
    # Which specific record was affected
    
    # ============================================================================
    # REQUEST CONTEXT
    # ============================================================================
    
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    request_id = Column(String(64), nullable=True)  # For tracing requests
    
    # ============================================================================
    # DETAILS
    # ============================================================================
    
    details = Column(String(1000), nullable=True)
    # Additional context about what happened
    
    success = Column(String(10), default="yes", nullable=False)  # yes, no
    # Whether the action was successful
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When the action occurred
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of audit logs (critical for compliance)
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this audit log was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this audit log (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this audit log was deleted (compliance, cleanup, etc.)
    
    # ============================================================================
    # DATABASE INDEXES
    # ============================================================================
    
    __table_args__ = (
        # Performance indexes for audit queries
        Index('idx_audit_logs_table_date', 'table_name', 'created_at'),
        Index('idx_audit_logs_user_date', 'user_id', 'created_at'),
        Index('idx_audit_logs_action_date', 'action_type', 'created_at'),
    )


class CallQueue(Base):
    """
    Manages call routing, priority, and queue management.
    Routes calls to appropriate AI models or human agents.
    """
    __tablename__ = "call_queue"
    
    queue_id = Column(String(64), primary_key=True)
    # Our internal queue ID (e.g., "QUEUE_20250110_001")
    
    call_id = Column(String(64), ForeignKey("calls.call_id"), nullable=False)
    
    # ============================================================================
    # QUEUE MANAGEMENT
    # ============================================================================
    
    priority_level = Column(String(20), default="normal", nullable=False)
    # normal, emergency (based on call arrival and caller statements)
    
    queue_status = Column(String(20), default="waiting", nullable=False)
    # waiting, processing, completed, failed, transferred_to_human
    
    # ============================================================================
    # EMERGENCY ROUTING
    # ============================================================================
    
    is_emergency = Column(String(10), default="no", nullable=False)
    # yes, no (determined by AI analysis of caller statements)
    
    emergency_reason = Column(String(200), nullable=True)
    # What the caller said that indicated emergency (tokenized)
    
    transferred_to_human = Column(String(10), default="no", nullable=False)
    # yes, no (if emergency, automatically route to human agent)
    
    assigned_human_agent = Column(String(64), nullable=True)
    # Which human agent at the clinic is handling the emergency call
    
    # ============================================================================
    # PROCESSING TIMELINE
    # ============================================================================
    
    ai_processing_started_at = Column(DateTime(timezone=True), nullable=True)
    # When AI started processing the call
    
    ai_processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    # When AI finished processing (before potential human transfer)
    
    human_transfer_at = Column(DateTime(timezone=True), nullable=True)
    # When call was transferred to human agent (if emergency)
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    call = relationship("Call", foreign_keys=[call_id])


class SystemConfig(Base):
    """
    System configuration settings and AI model configurations.
    Stores emergency keywords, clinic hours, AI model versions, etc.
    """
    __tablename__ = "system_config"
    
    config_id = Column(String(64), primary_key=True)
    # Our internal config ID (e.g., "CONFIG_20250110_001")
    
    # ============================================================================
    # CONFIGURATION DATA
    # ============================================================================
    
    config_key = Column(String(100), nullable=False, unique=True)
    # Configuration key (e.g., "emergency_keywords", "clinic_hours", "ai_model_version")
    
    config_value = Column(String(1000), nullable=False)
    # Configuration value (JSON string or simple value)
    
    config_type = Column(String(20), default="string", nullable=False)
    # string, json, number, boolean
    
    # ============================================================================
    # CATEGORIZATION
    # ============================================================================
    
    category = Column(String(50), nullable=True)
    # emergency, ai_models, clinic_settings, security, etc.
    
    description = Column(String(500), nullable=True)
    # Human-readable description of what this config does
    
    # ============================================================================
    # ACCESS CONTROL
    # ============================================================================
    
    is_sensitive = Column(String(10), default="no", nullable=False)
    # yes, no (whether this config contains sensitive data)
    
    requires_restart = Column(String(10), default="no", nullable=False)
    # yes, no (whether changing this config requires system restart)
    
    # ============================================================================
    # AUDIT TRAIL
    # ============================================================================
    
    updated_by = Column(String(64), nullable=True)
    # Who last updated this configuration
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
class AppointmentSlot(Base):
    """
    Tracks individual time slots for providers.
    Prevents double-booking by marking slots as taken.
    """
    __tablename__ = "appointment_slots"
    
    # ============================================================================
    # PRIMARY IDENTIFIER
    # ============================================================================
    
    slot_id = Column(String(64), primary_key=True)
    # Unique slot ID (e.g., "SLOT_20250115_1400_PROVIDER001")
    # Format: SLOT_{DATE}_{TIME}_{PROVIDER_ID}
    
    # ============================================================================
    # PROVIDER RELATIONSHIP
    # ============================================================================
    
    provider_id = Column(String(64), ForeignKey("providers.provider_id"), nullable=False, index=True)
    # Which provider this slot belongs to
    # Indexed for fast "show me all slots for Dr. Smith"
    
    # ============================================================================
    # SLOT TIMING
    # ============================================================================
    
    slot_datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    # Exact start time of this slot: 2025-01-15 14:00:00
    # Indexed for fast "show me slots on January 15th"
    
    duration_minutes = Column(Integer, default=30, nullable=False)
    # How long this slot is (15, 30, 45, 60 minutes)
    # Used to calculate when slot ends: slot_datetime + duration_minutes
    
    # ============================================================================
    # BOOKING STATUS - Prevents Double Booking
    # ============================================================================
    
    is_booked = Column(String(10), default="no", nullable=False)
    # "no" = available for booking
    # "held" = temporarily reserved during booking process (5 min timeout)
    # "yes" = confirmed booking exists
    # This prevents race condition where two patients try to book simultaneously
    
    booked_by_appointment_id = Column(String(64), ForeignKey("appointments.appointment_id"), nullable=True)
    # Which appointment is using this slot
    # NULL if is_booked = "no" or "held"
    # SET when is_booked = "yes"
    
    held_until = Column(DateTime(timezone=True), nullable=True)
    # If is_booked="held", when does the temporary hold expire?
    # Example: Patient says "I want 2pm Tuesday"
    #   - We set is_booked="held", held_until=now()+5min
    #   - Patient confirms → is_booked="yes", held_until=NULL
    #   - Patient doesn't confirm → background job releases slot after 5min
    
    held_by_call_sid = Column(String(64), nullable=True)
    # Which call is holding this slot (for tracking)
    
    # ============================================================================
    # CLINIC MULTI-TENANCY
    # ============================================================================
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=False, index=True)
    # Which clinic this slot belongs to (for multi-tenant isolation)
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When this slot was created (usually bulk-created for the month)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Last time this slot was modified (booked, released, etc.)
    
    # ============================================================================
    # DATABASE CONSTRAINTS & INDEXES
    # ============================================================================
    
    __table_args__ = (
        # CRITICAL: Prevents double booking
        # A provider cannot have two different appointments at the same datetime
        UniqueConstraint('provider_id', 'slot_datetime', name='unique_provider_slot'),
        
        # Performance indexes for fast queries
        Index('idx_appointment_slots_clinic_datetime', 'clinic_id', 'slot_datetime'),
        Index('idx_appointment_slots_provider_datetime', 'provider_id', 'slot_datetime'),
        Index('idx_appointment_slots_available', 'clinic_id', 'slot_datetime', 'is_booked'),
    )
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    provider = relationship("Provider")
    appointment = relationship("Appointment")
    clinic = relationship("Clinic")


class Clinic(Base):
    """
    Individual medical clinics using the system.
    Each clinic is a separate tenant with isolated data.
    """
    __tablename__ = "clinics"
    
    # ============================================================================
    # PRIMARY IDENTIFIER
    # ============================================================================
    
    clinic_id = Column(String(64), primary_key=True)
    # Unique clinic identifier (e.g., "CLINIC_PR_001", "CLINIC_TX_045")
    # Format: CLINIC_{STATE}_{NUMBER}
    
    # ============================================================================
    # CLINIC INFORMATION
    # ============================================================================
    
    clinic_name = Column(String(200), nullable=False)
    # Business name: "San Juan Family Medicine"
    # NOT PHI - this is the business entity name
    
    clinic_name_token = Column(String(64), nullable=True)
    # If clinic name contains sensitive info, tokenize it
    # Most clinics won't need this
    
    # ============================================================================
    # CONTACT INFORMATION
    # ============================================================================
    
    phone_number = Column(String(20), nullable=False, unique=True)
    # Main clinic phone number (Twilio number assigned to them)
    # Example: "+17875551234"
    # Each clinic gets a dedicated Twilio number
    
    email_token = Column(String(64), nullable=True)
    # Tokenized clinic contact email (for admin notifications)
    
    address_token = Column(String(64), nullable=True)
    # Tokenized physical address (if needed for scheduling)
    
    # ============================================================================
    # TIMEZONE & LANGUAGE
    # ============================================================================
    
    timezone = Column(String(50), default="America/Puerto_Rico", nullable=False)
    # For appointment scheduling and reminder calls
    # Examples: "America/Puerto_Rico", "America/New_York", "America/Chicago"
    
    default_language = Column(String(5), default="en", nullable=False)
    # Primary language for this clinic: "en" or "es"
    # Used as fallback if caller language can't be detected
    
    supported_languages = Column(String(20), default="en,es", nullable=False)
    # Comma-separated list of supported languages
    # Most Puerto Rico clinics: "en,es"
    # Bilingual AI will auto-detect and switch
    
    # ============================================================================
    # EHR INTEGRATION
    # ============================================================================
    
    ehr_system = Column(String(20), nullable=False)
    # Which EHR system: "nextgen", "google_calendar", "epic", "cerner"
    # Determines which connector to use
    
    ehr_api_endpoint = Column(String(500), nullable=True)
    # API URL for their EHR system
    # Example: "https://api.nextgen.com/v1"
    # NULL if using Google Calendar (uses standard endpoint)
    
    ehr_credentials_vault_key = Column(String(100), nullable=True)
    # Reference to Azure Key Vault secret containing EHR credentials
    # Example: "clinic-pr-001-nextgen-creds"
    # We NEVER store API keys directly in database
    
    ehr_enabled = Column(String(10), default="yes", nullable=False)
    # "yes" = use EHR, "no" = use fallback (Google Calendar)
    
    # ============================================================================
    # FALLBACK SYSTEM
    # ============================================================================
    
    fallback_system = Column(String(20), default="google_calendar", nullable=False)
    # What to use if EHR is down: "google_calendar", "none"
    
    fallback_credentials_vault_key = Column(String(100), nullable=True)
    # Azure Key Vault reference for fallback system credentials
    
    # ============================================================================
    # CALL ROUTING & CAPACITY
    # ============================================================================
    
    max_concurrent_calls = Column(Integer, default=10, nullable=False)
    # Maximum simultaneous calls this clinic can handle
    # Prevents overload; excess calls go to queue or forward to staff
    
    queue_timeout_seconds = Column(Integer, default=45, nullable=False)
    # How long to keep caller in queue before giving up
    # Per your planning doc: 45 seconds
    
    overload_action = Column(String(20), default="forward", nullable=False)
    # What to do when max_concurrent_calls reached:
    # "queue" = put in queue for queue_timeout_seconds
    # "forward" = immediately forward to staff_forward_number
    # "busy" = play busy signal and hangup
    
    staff_forward_number = Column(String(20), nullable=True)
    # Phone number to forward calls to when overloaded
    # Example: "+17875559999" (clinic receptionist)
    
    # ============================================================================
    # REMINDER SETTINGS
    # ============================================================================
    
    reminders_enabled = Column(String(10), default="yes", nullable=False)
    # "yes" = send automated reminder calls
    # "no" = reminders disabled for this clinic
    
    reminder_hours_before = Column(Integer, default=24, nullable=False)
    # How many hours before appointment to call
    # Per your planning doc: 24 hours
    
    reminder_retry_minutes = Column(Integer, default=30, nullable=False)
    # If no answer, retry after this many minutes
    # Per your planning doc: 30 minutes
    
    # ============================================================================
    # SUBSCRIPTION STATUS
    # ============================================================================
    
    subscription_tier = Column(String(20), default="basic", nullable=False)
    # "basic", "professional", "enterprise"
    # Determines feature access and usage limits
    
    subscription_status = Column(String(20), default="active", nullable=False)
    # "active" = fully operational
    # "grace_period" = payment failed, still working (5-7 days)
    # "suspended" = grace period expired, calls disabled
    # "cancelled" = customer cancelled, data retained encrypted
    
    # ============================================================================
    # OPERATIONAL STATUS
    # ============================================================================
    
    is_active = Column(String(10), default="yes", nullable=False)
    # "yes" = clinic is operational
    # "no" = clinic disabled (billing issue, customer request, etc.)
    # When "no", all calls immediately fail with message
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When clinic was onboarded
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Last configuration change
    
    last_call_at = Column(DateTime(timezone=True), nullable=True)
    # Most recent call received (for monitoring inactive clinics)
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of clinic data
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this clinic was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this clinic (user_id, system, etc.)
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    # One clinic has many appointment slots
    appointment_slots = relationship("AppointmentSlot", back_populates="clinic")
    
    # One clinic has one license
    license = relationship("ClinicLicense", back_populates="clinic", uselist=False)
    
    # One clinic has many usage records (one per billing period)
    usage_records = relationship("ClinicUsage", back_populates="clinic")
    # Many-to-many relationship: clinics can have multiple providers
    providers = relationship(
        "Provider",
        secondary=provider_clinics,
        back_populates="clinics"
    )


class ClinicUsage(Base):
    """
    Tracks usage metrics for billing purposes.
    Records minutes, tokens, and costs per clinic per billing period.
    """
    __tablename__ = "clinic_usage"
    
    # ============================================================================
    # PRIMARY IDENTIFIER
    # ============================================================================
    
    usage_id = Column(String(64), primary_key=True)
    # Unique usage record ID (e.g., "USAGE_CLINIC001_202501")
    # Format: USAGE_{CLINIC_ID}_{YYYYMM}
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=False, index=True)
    # Which clinic this usage belongs to
    
    # ============================================================================
    # BILLING PERIOD
    # ============================================================================
    
    billing_period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    # Start of billing month: 2025-01-01 00:00:00
    # Indexed for fast "get current month usage"
    
    billing_period_end = Column(DateTime(timezone=True), nullable=False)
    # End of billing month: 2025-01-31 23:59:59
    
    # ============================================================================
    # CALL METRICS
    # ============================================================================
    
    total_calls = Column(Integer, default=0, nullable=False)
    # Total number of calls this period (all statuses)
    
    total_call_minutes = Column(Integer, default=0, nullable=False)
    # Total minutes of call time (for billing)
    # Sum of all call durations this period
    
    completed_calls = Column(Integer, default=0, nullable=False)
    # Calls that ended normally (status="completed")
    
    failed_calls = Column(Integer, default=0, nullable=False)
    # Calls that had technical failures (status="failed")
    # Still count toward usage for billing
    
    abandoned_calls = Column(Integer, default=0, nullable=False)
    # Calls where caller hung up (status="abandoned")
    
    forwarded_calls = Column(Integer, default=0, nullable=False)
    # Calls forwarded to human staff (overload or emergency)
    
    # ============================================================================
    # LANGUAGE BREAKDOWN (for analytics)
    # ============================================================================
    
    calls_english = Column(Integer, default=0, nullable=False)
    # Calls conducted in English
    
    calls_spanish = Column(Integer, default=0, nullable=False)
    # Calls conducted in Spanish
    
    # ============================================================================
    # AI TOKEN USAGE (Azure OpenAI costs)
    # ============================================================================
    
    total_llm_prompt_tokens = Column(Integer, default=0, nullable=False)
    # Total tokens sent TO Azure OpenAI this period
    # Each conversation turn adds to this
    
    total_llm_completion_tokens = Column(Integer, default=0, nullable=False)
    # Total tokens received FROM Azure OpenAI this period
    
    total_llm_cost_usd = Column(Float, default=0.0, nullable=False)
    # Estimated Azure OpenAI cost this period
    # Formula: (prompt_tokens * $0.03/1K) + (completion_tokens * $0.06/1K)
    # Adjust rates based on actual Azure pricing
    
    # ============================================================================
    # SPEECH USAGE (Azure Speech costs)
    # ============================================================================
    
    total_stt_minutes = Column(Integer, default=0, nullable=False)
    # Speech-to-Text minutes (audio transcription)
    
    total_stt_cost_usd = Column(Float, default=0.0, nullable=False)
    # Azure Speech STT cost: ~$1.00 per hour
    
    total_tts_characters = Column(Integer, default=0, nullable=False)
    # Text-to-Speech character count (AI responses spoken)
    
    total_tts_cost_usd = Column(Float, default=0.0, nullable=False)
    # Azure Speech TTS cost: ~$16 per 1M characters
    
    # ============================================================================
    # TELEPHONY (Twilio costs)
    # ============================================================================
    
    total_twilio_minutes = Column(Integer, default=0, nullable=False)
    # Total Twilio voice minutes (inbound + outbound)
    
    total_twilio_cost_usd = Column(Float, default=0.0, nullable=False)
    # Twilio voice charges
    # Inbound: ~$0.0085/min, Outbound: ~$0.013/min in US
    
    # ============================================================================
    # REMINDER CALLS (separate tracking)
    # ============================================================================
    
    reminder_calls_sent = Column(Integer, default=0, nullable=False)
    # How many reminder calls made this period
    
    reminder_calls_answered = Column(Integer, default=0, nullable=False)
    # How many reminders were answered
    
    reminder_calls_cost_usd = Column(Float, default=0.0, nullable=False)
    # Cost of reminder calls (Twilio + TTS)
    
    # ============================================================================
    # APPOINTMENT METRICS
    # ============================================================================
    
    appointments_scheduled = Column(Integer, default=0, nullable=False)
    # New appointments created this period
    
    appointments_cancelled = Column(Integer, default=0, nullable=False)
    # Appointments cancelled this period
    
    appointments_confirmed = Column(Integer, default=0, nullable=False)
    # Appointments confirmed this period
    
    # ============================================================================
    # TOTALS FOR BILLING
    # ============================================================================
    
    total_cost_usd = Column(Float, default=0.0, nullable=False)
    # Sum of all costs this period:
    # llm_cost + stt_cost + tts_cost + twilio_cost + reminder_cost
    
    subscription_fee_usd = Column(Float, default=0.0, nullable=False)
    # Base monthly subscription fee (from ClinicLicense)
    
    overage_fee_usd = Column(Float, default=0.0, nullable=False)
    # Additional charges if exceeded plan limits
    
    total_billable_usd = Column(Float, default=0.0, nullable=False)
    # Final amount to bill:
    # subscription_fee + overage_fee + total_cost
    
    # ============================================================================
    # BILLING STATUS
    # ============================================================================
    
    invoice_generated = Column(String(10), default="no", nullable=False)
    # "yes" = invoice created and sent
    # "no" = still accumulating usage
    
    invoice_id = Column(String(64), nullable=True)
    # Reference to external billing system invoice
    
    payment_status = Column(String(20), default="pending", nullable=False)
    # "pending", "paid", "failed", "refunded"
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When this usage record was created (start of billing period)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Last time usage was updated (every call adds to this)
    
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    # When usage was finalized for billing (end of period)
    
    # ============================================================================
    # SOFT DELETE FIELDS (HIPAA Compliance)
    # ============================================================================
    
    is_deleted = Column(String(10), default="no", nullable=False)
    # "yes" = soft deleted, "no" = active
    # Prevents hard delete of usage records (may contain PHI patterns)
    
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # When this usage record was soft deleted
    
    deleted_by = Column(String(64), nullable=True)
    # Who deleted this usage record (user_id, system, etc.)
    
    deletion_reason = Column(String(200), nullable=True)
    # Why this usage record was deleted (compliance, cleanup, etc.)
    
    # ============================================================================
    # DATABASE INDEXES
    # ============================================================================
    
    __table_args__ = (
        # Performance indexes for fast billing queries
        Index('idx_clinic_usage_period', 'clinic_id', 'billing_period_start'),
        Index('idx_clinic_usage_current', 'clinic_id', 'billing_period_start', 'invoice_generated'),
    )
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    clinic = relationship("Clinic", back_populates="usage_records")


class ClinicLicense(Base):
    """
    License and quota management per clinic.
    Enforces usage limits and manages subscription lifecycle.
    """
    __tablename__ = "clinic_licenses"
    
    # ============================================================================
    # PRIMARY IDENTIFIER
    # ============================================================================
    
    license_id = Column(String(64), primary_key=True)
    # Unique license ID (e.g., "LICENSE_CLINIC001")
    
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=False, unique=True, index=True)
    # One license per clinic (unique constraint enforced)
    
    # ============================================================================
    # LICENSE STATUS
    # ============================================================================
    
    license_status = Column(String(20), default="active", nullable=False)
    # "active" = license valid, system operational
    # "grace_period" = payment failed, still working temporarily
    # "suspended" = grace period expired, calls disabled
    # "expired" = subscription ended, data retained encrypted
    # "cancelled" = customer cancelled voluntarily
    
    license_token = Column(String(256), nullable=True)
    # Encrypted license key for offline validation
    # Can be used to verify license without database access
    
    # ============================================================================
    # SUBSCRIPTION TIER & LIMITS
    # ============================================================================
    
    tier = Column(String(20), default="basic", nullable=False)
    # "basic" = small clinic, limited features
    # "professional" = medium clinic, more capacity
    # "enterprise" = large clinic, unlimited usage
    
    max_calls_per_month = Column(Integer, nullable=True)
    # Monthly call limit by tier:
    # Basic: 500 calls
    # Professional: 2000 calls
    # Enterprise: NULL (unlimited)
    
    max_concurrent_calls = Column(Integer, default=5, nullable=False)
    # How many simultaneous calls allowed
    # Basic: 5, Professional: 15, Enterprise: 50
    
    max_call_duration_minutes = Column(Integer, default=30, nullable=False)
    # Auto-hangup after this duration (prevent abuse)
    # Protects against infinitely running calls
    
    max_providers = Column(Integer, nullable=True)
    # How many providers can be in the system
    # Basic: 5, Professional: 20, Enterprise: NULL (unlimited)
    
    # ============================================================================
    # FEATURE FLAGS (what's included in tier)
    # ============================================================================
    
    feature_reminders = Column(String(10), default="yes", nullable=False)
    # "yes" = automated reminders included
    # Basic: yes, Professional: yes, Enterprise: yes
    
    feature_analytics = Column(String(10), default="no", nullable=False)
    # "yes" = advanced analytics dashboard
    # Basic: no, Professional: yes, Enterprise: yes
    
    feature_api_access = Column(String(10), default="no", nullable=False)
    # "yes" = API access for custom integrations
    # Basic: no, Professional: no, Enterprise: yes
    
    feature_priority_support = Column(String(10), default="no", nullable=False)
    # "yes" = priority support queue
    # Basic: no, Professional: yes, Enterprise: yes
    
    # ============================================================================
    # CURRENT USAGE (real-time tracking)
    # ============================================================================
    
    current_month_calls = Column(Integer, default=0, nullable=False)
    # How many calls so far this billing period
    # Reset to 0 at start of each billing cycle
    
    current_month_minutes = Column(Integer, default=0, nullable=False)
    # Total minutes used this billing period
    
    current_concurrent_calls = Column(Integer, default=0, nullable=False)
    # How many calls are active RIGHT NOW
    # Incremented when call starts, decremented when call ends
    # Used to enforce max_concurrent_calls limit
    
    usage_percentage = Column(Float, default=0.0, nullable=False)
    # (current_month_calls / max_calls_per_month) * 100
    # Example: 450 calls / 500 limit = 90%
    
    # ============================================================================
    # AUTO-UPGRADE LOGIC
    # ============================================================================
    
    auto_upgrade_threshold = Column(Float, default=115.0, nullable=False)
    # When usage reaches this percentage, offer upgrade
    # Per your planning doc: 115% to prevent service degradation
    # Example: 575 calls on 500 limit = 115% = show upgrade prompt
    
    auto_upgrade_offered = Column(String(10), default="no", nullable=False)
    # "yes" = we already sent upgrade offer this month
    # "no" = haven't offered yet
    # Reset to "no" at start of new billing cycle
    
    auto_upgrade_offered_at = Column(DateTime(timezone=True), nullable=True)
    # When we sent the upgrade offer
    
    # ============================================================================
    # GRACE PERIOD (payment failure handling)
    # ============================================================================
    
    grace_period_days = Column(Integer, default=7, nullable=False)
    # How many days to keep working after payment failure
    # Per your planning doc: 5-7 days
    
    grace_period_start = Column(DateTime(timezone=True), nullable=True)
    # When grace period started (when payment failed)
    # NULL if not in grace period
    
    grace_period_end = Column(DateTime(timezone=True), nullable=True)
    # When grace period expires
    # After this, license_status → "suspended"
    
    # ============================================================================
    # BILLING CYCLE
    # ============================================================================
    
    billing_cycle_start = Column(DateTime(timezone=True), nullable=False)
    # When current billing month started
    # Example: 2025-01-01 00:00:00
    
    billing_cycle_end = Column(DateTime(timezone=True), nullable=False)
    # When current billing month ends
    # Example: 2025-01-31 23:59:59
    
    next_billing_date = Column(DateTime(timezone=True), nullable=False)
    # When next payment is due
    # Usually same as billing_cycle_end
    
    # ============================================================================
    # PRICING
    # ============================================================================
    
    monthly_fee_usd = Column(Float, default=0.0, nullable=False)
    # Base subscription fee (before usage costs)
    # Basic: $199, Professional: $599, Enterprise: $1499
    
    overage_rate_per_call_usd = Column(Float, default=0.50, nullable=False)
    # Cost per call if exceeded max_calls_per_month
    # Example: 575 calls on 500 limit = 75 overage calls * $0.50 = $37.50
    
    # ============================================================================
    # SUSPENSION HANDLING
    # ============================================================================
    
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    # When license was suspended (grace period expired)
    
    suspension_reason = Column(String(100), nullable=True)
    # Why suspended: "payment_failed", "exceeded_limits", "fraud", "customer_request"
    
    data_retention_days = Column(Integer, default=90, nullable=False)
    # How long to keep encrypted data after suspension
    # Default: 90 days, then purge
    
    # ============================================================================
    # REACTIVATION
    # ============================================================================
    
    reactivation_count = Column(Integer, default=0, nullable=False)
    # How many times license was suspended and reactivated
    # High number might indicate payment issues
    
    last_reactivated_at = Column(DateTime(timezone=True), nullable=True)
    # Most recent reactivation timestamp
    
    # ============================================================================
    # TIMESTAMPS
    # ============================================================================
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When license was first created (clinic onboarding)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Last modification to license
    
    # ============================================================================
    # DATABASE INDEXES
    # ============================================================================
    
    __table_args__ = (
        # Performance indexes for fast license queries
        Index('idx_license_current_usage', 'clinic_id', 'current_month_calls'),
        Index('idx_license_status', 'license_status', 'tier'),
        Index('idx_license_billing_cycle', 'clinic_id', 'billing_cycle_start'),
    )
    
    # ============================================================================
    # RELATIONSHIPS
    # ============================================================================
    
    clinic = relationship("Clinic", back_populates="license")


class GoogleCalendarCredentials(Base):
    """
    Stores encrypted Google Calendar OAuth credentials for providers.
    
    This table securely stores OAuth tokens and refresh tokens for each provider
    to enable Google Calendar integration without requiring re-authentication.
    """
    __tablename__ = "google_calendar_credentials"
    
    # Primary key
    credential_id = Column(String(64), primary_key=True)
    
    # Foreign key to provider
    provider_id = Column(String(64), ForeignKey("providers.provider_id"), nullable=False, unique=True)
    
    # Encrypted OAuth credentials
    access_token_nonce = Column(LargeBinary(12), nullable=False)
    access_token_ciphertext = Column(LargeBinary, nullable=False)
    
    refresh_token_nonce = Column(LargeBinary(12), nullable=True)  # May be null if not available
    refresh_token_ciphertext = Column(LargeBinary, nullable=True)
    
    # Token metadata
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    scope = Column(Text, nullable=False)  # OAuth scopes granted
    
    # Status and tracking
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    provider = relationship("Provider", back_populates="google_calendar_credentials")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_provider_credentials', 'provider_id'),
        Index('idx_credentials_active', 'is_active', 'last_used_at'),
        Index('idx_credentials_expires', 'token_expires_at'),
    )


class CallerType(Base):
    """
    Defines different types of callers for intelligent routing.
    """
    __tablename__ = "caller_types"
    
    # Primary identifier
    caller_type_id = Column(String(64), primary_key=True)
    
    # Caller type information
    caller_type_name = Column(String(50), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    priority_level = Column(Integer, nullable=False, default=3)
    default_routing_strategy = Column(String(50), nullable=False, default='round_robin')
    default_overload_policy = Column(String(50), nullable=False, default='queue')
    max_queue_size = Column(Integer, nullable=False, default=50)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    routing_rules = relationship("RoutingRule", back_populates="caller_type")
    call_queues = relationship("CallQueueDefinition", back_populates="caller_type")
    
    # Indexes
    __table_args__ = (
        Index('idx_caller_types_active', 'caller_type_id', postgresql_where=text("is_deleted = 'no' AND is_active = true")),
        Index('idx_caller_types_priority', 'priority_level'),
    )


class RoutingRule(Base):
    """
    Configurable routing rules for different caller types.
    """
    __tablename__ = "routing_rules"
    
    # Primary identifier
    rule_id = Column(String(64), primary_key=True)
    
    # Rule information
    rule_name = Column(String(100), nullable=False)
    caller_type_id = Column(String(64), ForeignKey('caller_types.caller_type_id', ondelete='CASCADE'), nullable=False)
    priority_level = Column(Integer, nullable=False)
    routing_strategy = Column(String(50), nullable=False)
    overload_policy = Column(String(50), nullable=False)
    max_queue_size = Column(Integer, nullable=False)
    target_providers = Column(Text, nullable=True)  # JSON array of provider IDs
    conditions = Column(Text, nullable=True)  # JSON conditions for rule matching
    is_enabled = Column(Boolean, nullable=False, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    caller_type = relationship("CallerType", back_populates="routing_rules")
    calls = relationship("Call", back_populates="routing_rule")
    
    # Indexes
    __table_args__ = (
        Index('idx_routing_rules_active', 'rule_id', postgresql_where=text("is_deleted = 'no' AND is_enabled = true")),
        Index('idx_routing_rules_caller_type', 'caller_type_id', 'priority_level'),
    )


class CallerDetectionLog(Base):
    """
    Logs of caller type detection attempts for analysis and improvement.
    """
    __tablename__ = "caller_detection_logs"
    
    # Primary identifier
    detection_id = Column(String(64), primary_key=True)
    
    # Call information
    call_id = Column(String(64), ForeignKey('calls.call_id', ondelete='CASCADE'), nullable=False)
    caller_phone_token = Column(String(64), nullable=True)
    
    # Detection results
    detected_caller_type = Column(String(50), nullable=True)
    detection_method = Column(String(50), nullable=False)
    confidence_score = Column(Float, nullable=True)
    detection_data = Column(Text, nullable=True)  # JSON data used for detection
    detection_result = Column(Text, nullable=True)  # JSON result data
    processing_time_ms = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    call = relationship("Call", back_populates="detection_logs")
    
    # Indexes
    __table_args__ = (
        Index('idx_caller_detection_logs_call', 'call_id'),
        Index('idx_caller_detection_logs_phone', 'caller_phone_token'),
        Index('idx_caller_detection_logs_type', 'detected_caller_type'),
    )


class ProviderCapacity(Base):
    """
    Tracks provider capacity and availability for call routing.
    """
    __tablename__ = "provider_capacities"
    
    # Primary identifier
    capacity_id = Column(String(64), primary_key=True)
    
    # Provider information
    provider_id = Column(String(64), ForeignKey('providers.provider_id', ondelete='CASCADE'), nullable=False)
    max_concurrent_calls = Column(Integer, nullable=False)
    current_calls = Column(Integer, nullable=False, default=0)
    available_capacity = Column(Integer, nullable=False)
    skills = Column(Text, nullable=True)  # JSON array of skills
    languages = Column(Text, nullable=True)  # JSON array of languages
    specializations = Column(Text, nullable=True)  # JSON array of specializations
    is_available = Column(Boolean, nullable=False, default=True)
    
    # Timestamps
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    provider = relationship("Provider", back_populates="capacity")
    
    # Indexes
    __table_args__ = (
        Index('idx_provider_capacities_provider', 'provider_id'),
        Index('idx_provider_capacities_available', 'is_available', 'available_capacity'),
    )


class CallQueueDefinition(Base):
    """
    Call queue definitions for overload management and priority handling.
    """
    __tablename__ = "call_queues"
    
    # Primary identifier
    queue_id = Column(String(64), primary_key=True)
    
    # Queue information
    queue_name = Column(String(100), nullable=False)
    caller_type_id = Column(String(64), ForeignKey('caller_types.caller_type_id', ondelete='CASCADE'), nullable=False)
    priority_level = Column(Integer, nullable=False)
    max_queue_size = Column(Integer, nullable=False)
    current_size = Column(Integer, nullable=False, default=0)
    average_wait_time = Column(Float, nullable=False, default=0.0)
    queue_config = Column(Text, nullable=True)  # JSON configuration
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    caller_type = relationship("CallerType", back_populates="call_queues")
    queued_calls = relationship("QueuedCall", back_populates="queue")
    
    # Indexes
    __table_args__ = (
        Index('idx_call_queues_active', 'queue_id', postgresql_where=text("is_deleted = 'no' AND is_active = true")),
    )


class QueuedCall(Base):
    """
    Individual calls waiting in queues for provider assignment.
    """
    __tablename__ = "queued_calls"
    
    # Primary identifier
    queued_call_id = Column(String(64), primary_key=True)
    
    # Call information
    call_id = Column(String(64), ForeignKey('calls.call_id', ondelete='CASCADE'), nullable=False)
    queue_id = Column(String(64), ForeignKey('call_queues.queue_id', ondelete='CASCADE'), nullable=False)
    priority_score = Column(Float, nullable=False, default=0.0)
    
    # Queue timing
    queued_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    estimated_wait_time = Column(Float, nullable=True)
    
    # Assignment information
    assigned_provider_id = Column(String(64), ForeignKey('providers.provider_id', ondelete='SET NULL'), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default='queued')  # queued, assigned, completed, expired
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    call = relationship("Call", back_populates="queued_call")
    queue = relationship("CallQueueDefinition", back_populates="queued_calls")
    assigned_provider = relationship("Provider", foreign_keys=[assigned_provider_id])
    
    # Indexes
    __table_args__ = (
        Index('idx_queued_calls_queue', 'queue_id', 'priority_score'),
        Index('idx_queued_calls_status', 'status', 'queued_at'),
        Index('idx_queued_calls_call', 'call_id'),
    )


class Reminder(Base):
    """
    Tracks automated reminder calls for appointments.
    Each reminder represents a scheduled call to remind patients about upcoming appointments.
    """
    __tablename__ = "reminders"
    
    # Primary identifier
    reminder_id = Column(String(64), primary_key=True)
    
    # Appointment relationship
    appointment_id = Column(String(64), ForeignKey('appointments.appointment_id', ondelete='CASCADE'), nullable=False)
    
    # Reminder scheduling
    scheduled_time = Column(DateTime(timezone=True), nullable=False)
    # When the reminder call should be made
    
    reminder_type = Column(String(20), nullable=False, default='appointment_reminder')
    # Type of reminder: 'appointment_reminder', 'follow_up', 'cancellation_reminder'
    
    # Reminder status
    status = Column(String(20), nullable=False, default='scheduled')
    # scheduled, calling, completed, failed, cancelled, no_answer
    
    # Call tracking
    reminder_call_id = Column(String(64), nullable=True)
    # ID of the actual call made for this reminder
    
    # Retry logic
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_time = Column(DateTime(timezone=True), nullable=True)
    
    # Call outcome
    call_duration_seconds = Column(Integer, nullable=True)
    call_outcome = Column(String(50), nullable=True)
    # answered, no_answer, busy, failed, voicemail
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    appointment = relationship("Appointment", back_populates="reminders")
    reminder_logs = relationship("ReminderLog", back_populates="reminder")
    
    # Indexes
    __table_args__ = (
        Index('idx_reminders_scheduled', 'scheduled_time', 'status'),
        Index('idx_reminders_appointment', 'appointment_id'),
        Index('idx_reminders_status', 'status', 'scheduled_time'),
        Index('idx_reminders_retry', 'next_retry_time', 'status'),
    )


class ReminderLog(Base):
    """
    Logs all reminder call attempts and outcomes.
    Provides detailed audit trail for reminder system.
    """
    __tablename__ = "reminder_logs"
    
    # Primary identifier
    log_id = Column(String(64), primary_key=True)
    
    # Reminder relationship
    reminder_id = Column(String(64), ForeignKey('reminders.reminder_id', ondelete='CASCADE'), nullable=False)
    
    # Call attempt information
    attempt_number = Column(Integer, nullable=False)
    # Which attempt this log entry represents (1st, 2nd, 3rd, etc.)
    
    call_started_at = Column(DateTime(timezone=True), nullable=False)
    call_ended_at = Column(DateTime(timezone=True), nullable=True)
    
    # Call outcome details
    call_status = Column(String(20), nullable=False)
    # initiated, ringing, answered, no_answer, busy, failed, completed
    
    call_duration_seconds = Column(Integer, nullable=True)
    call_outcome = Column(String(50), nullable=True)
    # answered, no_answer, busy, failed, voicemail, hangup
    
    # Error information
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Call metadata
    caller_id = Column(String(20), nullable=True)
    # Phone number used for the reminder call
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Soft delete fields
    is_deleted = Column(String(10), default="no", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(64), nullable=True)
    deletion_reason = Column(String(200), nullable=True)
    
    # Relationships
    reminder = relationship("Reminder", back_populates="reminder_logs")
    
    # Indexes
    __table_args__ = (
        Index('idx_reminder_logs_reminder', 'reminder_id', 'attempt_number'),
        Index('idx_reminder_logs_status', 'call_status', 'call_started_at'),
        Index('idx_reminder_logs_outcome', 'call_outcome', 'call_started_at'),
    )