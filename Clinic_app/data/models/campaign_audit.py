# Clinic_app/data/models/campaign_audit.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, BYTEA
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class CampaignAudit(Base):
    """
    Immutable call-level record. One row per call attempt, written by the
    call_analyzed webhook handler after each call ends.

    PHI handling:
    - patient_name_encrypted: AES-256-GCM, populated from Retell call_analyzed metadata.
      Only stored here for dashboard display ("Maria García — BOOKED"). Nullable in case
      the webhook fires without metadata.
    - call_summary_encrypted: One-sentence Claude API summary of the call outcome.
      The raw Retell transcript is NEVER stored — discarded after summary generation.
    - No patient phone here — correlate via campaign_contact_id if needed.
    """
    __tablename__ = "campaign_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_contact_id = Column(UUID(as_uuid=True), ForeignKey("campaign_contact.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)

    retell_call_id = Column(String, nullable=False, index=True)  # For webhook correlation

    outcome = Column(String(50), nullable=False)               # ContactStatus value: BOOKED | DECLINED | VOICEMAIL | NO_ANSWER | ERROR

    # PHI — encrypted at rest
    patient_name_encrypted = Column(BYTEA, nullable=True)      # AES-256-GCM — for dashboard display only
    call_summary_encrypted = Column(BYTEA, nullable=True)      # One-sentence Claude summary, AES-256-GCM

    ehr_appointment_id = Column(String, nullable=True)         # NextGen appointment ID if outcome == BOOKED
    attempt_number = Column(Integer, nullable=False)           # 1, 2, or 3

    called_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # Dashboard detail view: all audit rows for a campaign, ordered by time
        Index("idx_audit_clinic_campaign", "clinic_id", "campaign_id", "called_at"),
    )

    # Relationships
    contact = relationship("CampaignContact", backref="audit_records")
    campaign = relationship("Campaign", backref="audit_records")
    clinic = relationship("Clinic", backref="campaign_audits")

    def __repr__(self) -> str:
        return f"<CampaignAudit(id={self.id}, contact_id={self.campaign_contact_id}, outcome={self.outcome}, attempt={self.attempt_number})>"
