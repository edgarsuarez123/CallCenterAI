# Clinic_app/data/models/clinic_ehr_config.py
import uuid
from datetime import datetime
from sqlalchemy import Column, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, BYTEA, JSONB
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class ClinicEHRConfig(Base):
    """
    NextGen EHR connection config for Playwright automation.
    One record per clinic (enforced by unique constraint on clinic_id).

    Credentials are AES-256-GCM encrypted — never stored plaintext.

    appt_type_mapping: JSONB dict mapping GapType enum values to clinic-specific
    NextGen appointment type codes. E.g.:
        {"colorectal_cancer_screening": "PREV", "diabetes_hba1c": "DM_A1C"}
    JSONB chosen because codes are arbitrary per-clinic and change rarely —
    no schema migration needed when a clinic updates their codes.
    """

    __tablename__ = "clinic_ehr_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinic.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    nextgen_url = Column(Text, nullable=False)  # URL Playwright navigates to
    nextgen_username_encrypted = Column(BYTEA, nullable=False)  # AES-256-GCM
    nextgen_password_encrypted = Column(BYTEA, nullable=False)  # AES-256-GCM

    appt_type_mapping = Column(
        JSONB, nullable=False, default=dict
    )  # GapType.value → NextGen appt type code

    connection_verified_at = Column(
        DateTime(timezone=True), nullable=True
    )  # Timestamp of last successful credential test

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    clinic = relationship("Clinic", backref="ehr_config")

    def __repr__(self) -> str:
        return f"<ClinicEHRConfig(clinic_id={self.clinic_id}, verified_at={self.connection_verified_at})>"
