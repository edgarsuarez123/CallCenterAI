# Clinic_app/data/models/campaign.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base
from Clinic_app.data.enums import CampaignStatus


class Campaign(Base):
    """
    One campaign = one CSV upload batch.
    Stores operational config (calling hours, concurrency, retry hours) per campaign.
    Progress counters are denormalized for dashboard performance — updated atomically
    in the same transaction as each contact status change.
    """
    __tablename__ = "campaign"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(Text, nullable=False)  # e.g., "Q1 2026 HEDIS Outreach"
    status = Column(String(50), nullable=False, default=CampaignStatus.PENDING.value, index=True)

    # Denormalized progress counters — avoids COUNT(*) on every dashboard poll
    total_contacts = Column(Integer, nullable=False, default=0)
    called_count = Column(Integer, nullable=False, default=0)   # Incremented on CALLING transition
    booked_count = Column(Integer, nullable=False, default=0)   # Incremented on BOOKED
    failed_count = Column(Integer, nullable=False, default=0)   # Incremented on EXHAUSTED or DECLINED

    # Operational config — overrides clinic_integration defaults for this campaign
    calling_hours_start = Column(String(5), nullable=False, default="09:00")   # HH:MM clinic local time
    calling_hours_end = Column(String(5), nullable=False, default="18:00")
    campaign_concurrency_limit = Column(Integer, nullable=False, default=3)    # Max simultaneous calls
    voicemail_retry_hours = Column(Integer, nullable=False, default=4)
    no_answer_retry_hours = Column(Integer, nullable=False, default=2)
    error_retry_hours = Column(Integer, nullable=False, default=24)
    max_attempts = Column(Integer, nullable=False, default=3)

    # HEDIS measurement year — used for cross-year dedup at CSV ingestion.
    # Same patient + same gap + same year = duplicate; new year = new obligation.
    measurement_year = Column(Integer, nullable=False, default=2026)

    created_by = Column(UUID(as_uuid=True), ForeignKey("clinic_staff.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Worker queries: "give me ACTIVE campaigns for this clinic"
        Index("idx_campaign_clinic_status", "clinic_id", "status"),
        # Sanity guard — completed + failed cannot exceed total
        CheckConstraint(
            "booked_count + failed_count <= total_contacts",
            name="check_campaign_counts_sane",
        ),
    )

    # Relationships
    clinic = relationship("Clinic", backref="campaigns")
    creator = relationship("ClinicStaff", backref="campaigns")

    def __repr__(self) -> str:
        return f"<Campaign(id={self.id}, clinic_id={self.clinic_id}, name={self.name!r}, status={self.status})>"
