# Clinic_app/data/models/campaign_contact.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Date, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, BYTEA
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base
from Clinic_app.data.enums import ContactStatus


class CampaignContact(Base):
    """
    One row per patient per campaign. The campaign worker reads this table to determine
    who to call next (FIFO, respecting next_attempt_after).

    PHI: encrypted phone, name, and DOB at rest. Name/DOB are decrypted only when placing
    an outbound call or for authorized dashboard flows. Provider name and payer are plain text.
    The dual-column pattern (phone_encrypted + phone_hash) mirrors the patient table:
    - phone_encrypted: passed to Retell to place the call
    - phone_hash: used for dedup on CSV import without decrypting all rows
    """
    __tablename__ = "campaign_contact"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)  # Denormalized for tenant isolation

    # PHI — phone + optional name for Retell metadata at dial time
    # DOB is never stored (PHI Rule #2) — Retell agent does not require DOB for identity
    phone_encrypted = Column(BYTEA, nullable=False)          # AES-256-GCM encrypted E.164 phone number
    phone_hash = Column(String(64), nullable=False)          # HMAC-SHA256 hash for dedup without decryption
    patient_name_encrypted = Column(BYTEA, nullable=True)    # AES-256-GCM — decrypt only at dial

    provider_name = Column(String, nullable=True)              # From CSV — Retell metadata
    payer = Column(String, nullable=True)                      # Insurance plan name — Retell metadata

    gap_type = Column(String(100), nullable=False)           # GapType enum value — drives agent script + appt type
    preferred_language = Column(String(10), nullable=False, default="en")  # "en" | "es"

    status = Column(String(50), nullable=False, default=ContactStatus.PENDING.value, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)        # 0–3
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    next_attempt_after = Column(DateTime(timezone=True), nullable=True)  # NULL = ready now

    ehr_appointment_id = Column(String, nullable=True)       # NextGen appointment ID on BOOKED

    # hospital_flu scheduling fields
    release_date = Column(Date, nullable=True)               # Discharge date from CSV; deadline = release_date + 7 days
    priority_order = Column(Integer, nullable=False, default=1)  # 0 = hospital_flu (called first); 1 = all others

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Primary worker query: PENDING contacts ready to call now, FIFO by created_at
        Index("idx_contact_worker_queue", "clinic_id", "campaign_id", "status", "next_attempt_after"),
        # Dedup check on CSV import
        Index("idx_contact_phone_hash", "clinic_id", "phone_hash"),
    )

    # Relationships
    campaign = relationship("Campaign", backref="contacts")
    clinic = relationship("Clinic", backref="campaign_contacts")

    def __repr__(self) -> str:
        return f"<CampaignContact(id={self.id}, campaign_id={self.campaign_id}, status={self.status}, attempts={self.attempt_count})>"
