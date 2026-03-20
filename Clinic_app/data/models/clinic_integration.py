# Clinic_app/data/models/clinic_integration.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class ClinicIntegration(Base):
    """
    Stores clinic-specific integration configuration.
    One integration record per clinic (Retell agent, phone number, Google Calendar access).
    Also stores HEDIS campaign operational defaults — overridable per campaign.
    """
    __tablename__ = "clinic_integration"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    retell_agent_id = Column(Text, nullable=False)  # Retell AI agent ID for this clinic
    retell_did = Column(String, nullable=False)  # E.164 inbound DID
    google_service_account_json = Column(Text, nullable=False)  # Encrypted Google service account JSON
    default_appointment_length_minutes = Column(Integer, nullable=False, default=15)
    default_capacity = Column(Integer, nullable=False, default=1)  # Used as default when creating providers

    # ── HEDIS campaign operational defaults ───────────────────────────────────
    # These are clinic-wide defaults; individual campaigns can override each value.
    timezone = Column(String(100), nullable=False, default="America/New_York")  # IANA tz for calling hours enforcement
    calling_hours_start = Column(String(5), nullable=False, default="09:00")    # HH:MM
    calling_hours_end = Column(String(5), nullable=False, default="18:00")
    campaign_concurrency_limit = Column(Integer, nullable=False, default=3)     # Max simultaneous outbound calls
    voicemail_retry_hours = Column(Integer, nullable=False, default=4)
    no_answer_retry_hours = Column(Integer, nullable=False, default=2)
    error_retry_hours = Column(Integer, nullable=False, default=24)
    max_attempts = Column(Integer, nullable=False, default=3)
    retell_outbound_number = Column(String, nullable=True)  # E.164 DID for outbound campaign calls (separate from inbound retell_did)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    clinic = relationship("Clinic", backref="integration")

    def __repr__(self):
        return f"<ClinicIntegration(clinic_id={self.clinic_id}, retell_agent_id={self.retell_agent_id})>"

