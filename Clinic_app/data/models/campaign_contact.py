# data/models/campaign_contact.py
import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Date,
    Integer,
    SmallInteger,
    Text,
    LargeBinary,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class CampaignContact(Base):
    """
    One row per patient in a campaign. Tracks call outcome per contact.

    PHI fields:
      - patient_name_encrypted: AES-256-GCM encrypted bytes (via encrypt_phi)
      - phone_encrypted: AES-256-GCM encrypted bytes
      - phone_hash: SHA-256 of normalized E.164 phone (for dedup without decryption)

    All plaintext PHI exists only in memory during active request processing
    and is never persisted, logged, or returned in API responses except as
    masked values (phone last 4 digits, patient first name only).

    Tenant isolation: every query MUST include clinic_id filter.
    """

    __tablename__ = "campaign_contact"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized for efficient row-level tenant isolation
    clinic_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # PHI — always encrypted at rest
    patient_name_encrypted = Column(LargeBinary, nullable=False)
    phone_encrypted = Column(LargeBinary, nullable=False)

    # SHA-256 of normalized E.164 phone — used for dedup without decryption
    phone_hash = Column(String(64), nullable=False)

    # HEDIS-specific metadata
    provider_name = Column(Text, nullable=True)
    payer = Column(Text, nullable=True)
    gap_type = Column(String(50), nullable=True, index=True)
    preferred_language = Column(String(10), nullable=True, default="en")

    # Per-contact outreach reason (may override campaign default)
    reason = Column(Text, nullable=True)

    # Full lifecycle status (ContactStatus enum) — used by advanced campaign_service
    status = Column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="ContactStatus enum: pending|calling|booked|declined|voicemail|no_answer|error|exhausted|...",
    )

    # Scheduling
    priority_order = Column(SmallInteger, nullable=True)
    next_attempt_after = Column(DateTime(timezone=True), nullable=True)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    release_date = Column(Date, nullable=True)

    # EHR booking reference
    ehr_appointment_id = Column(String(100), nullable=True)

    # Call outcome tracking (simple service compat — maps to ContactOutcome)
    outcome = Column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="ContactOutcome enum: pending|calling|accepted|declined|voicemail|no_answer|failed",
    )
    retell_call_id = Column(
        String(255), nullable=True, comment="Retell call ID for correlation to call logs"
    )
    call_duration_seconds = Column(Integer, nullable=True)
    call_date = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)

    # One-sentence summary from call (if available)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    campaign = relationship("Campaign", back_populates="contacts")

    __table_args__ = (
        Index("idx_campaign_contact_clinic_campaign", "clinic_id", "campaign_id"),
        Index("idx_campaign_contact_outcome", "campaign_id", "outcome"),
        # Dedup index: one phone number per clinic across all campaigns
        Index("idx_campaign_contact_phone_hash", "clinic_id", "phone_hash"),
    )

    def __repr__(self) -> str:
        return f"<CampaignContact(id={self.id}, status={self.status}, outcome={self.outcome})>"
