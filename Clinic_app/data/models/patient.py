# Clinic_app/data/models/patient.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, BYTEA
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class Patient(Base):
    """
    Stores tokenized patient identifiers and contact info.
    PHI (name, DOB) is encrypted at rest.
    """
    __tablename__ = "patient"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    name_token = Column(BYTEA, nullable=False)  # Encrypted patient name (PHI)
    dob_token = Column(BYTEA, nullable=False)  # Encrypted date of birth (PHI)
    phone_e164 = Column(String, nullable=False)  # Contact number for calls and reminders
    email = Column(String, nullable=True)  # Email address for future notifications
    language = Column(String(10), nullable=False, default="en")  # en/es for AI voice selection
    insurance_plan = Column(Text, nullable=True)  # Insurance plan information (nullable)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Composite index for efficient "find patient by phone within clinic" queries
    __table_args__ = (
        Index('idx_clinic_phone', 'clinic_id', 'phone_e164'),
    )

    # Relationships
    clinic = relationship("Clinic", backref="patients")
    # bookings relationship will be defined in booking model

    def __repr__(self):
        return f"<Patient(id={self.id}, clinic_id={self.clinic_id}, phone_e164={self.phone_e164})>"

