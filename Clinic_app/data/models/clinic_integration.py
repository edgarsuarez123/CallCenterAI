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
    """
    __tablename__ = "clinic_integration"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    retell_agent_id = Column(Text, nullable=False)  # Retell AI agent ID for this clinic
    retell_did = Column(String, nullable=False)  # E.164 format phone number (DID)
    google_service_account_json = Column(Text, nullable=False)  # Encrypted Google service account JSON
    default_appointment_length_minutes = Column(Integer, nullable=False, default=15)
    default_capacity = Column(Integer, nullable=False, default=1)  # Used as default when creating providers
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    clinic = relationship("Clinic", backref="integration")

    def __repr__(self):
        return f"<ClinicIntegration(clinic_id={self.clinic_id}, retell_agent_id={self.retell_agent_id})>"

