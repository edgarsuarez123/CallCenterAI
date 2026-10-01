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
    All PHI (name, DOB, phone, email) is encrypted at rest.
    Uses name_dob_hash for efficient lookup without decrypting all records.
    """

    __tablename__ = "patient"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(
        UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_token = Column(BYTEA, nullable=False)  # Encrypted patient name (PHI)
    # dob_token removed — PHI Rule #2: never store DOB in DB; name_dob_hash is sufficient for lookup
    phone_token = Column(BYTEA, nullable=False)  # Encrypted phone number (PHI)
    phone_hash = Column(
        String(64), nullable=True, index=True
    )  # SHA-256 hash for dedup without decryption
    email_token = Column(BYTEA, nullable=True)  # Encrypted email address (PHI, nullable)
    name_dob_hash = Column(
        String(64), nullable=False
    )  # SHA-256 hash of normalized (name|dob) for efficient lookup (NOT PHI)
    language = Column(String(10), nullable=False, default="en")  # en/es for AI voice selection
    insurance_plan = Column(Text, nullable=True)  # Insurance plan information (nullable)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Composite index for efficient "find patient by name+DOB hash within clinic" queries
    __table_args__ = (Index("idx_clinic_name_dob_hash", "clinic_id", "name_dob_hash"),)

    # Relationships
    clinic = relationship("Clinic", backref="patients")
    # bookings relationship will be defined in booking model

    def __repr__(self):
        return f"<Patient(id={self.id}, clinic_id={self.clinic_id})>"
