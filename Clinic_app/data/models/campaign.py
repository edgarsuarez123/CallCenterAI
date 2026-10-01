# data/models/campaign.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class Campaign(Base):
    """
    Represents a batch of outbound HEDIS outreach calls for a single clinic.

    A campaign groups a set of patients who share a common outreach reason
    (e.g., "Annual wellness visit overdue", "A1C check needed"). Contacts are
    uploaded via CSV and processed by the campaign worker.

    Tenant isolation: every query MUST include clinic_id filter.
    """
    __tablename__ = "campaign"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    clinic_id = Column(
        UUID(as_uuid=True),
        ForeignKey("clinic.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)
    reason = Column(
        Text,
        nullable=False,
        comment="Default outreach reason for this campaign (overridden per contact if CSV has reason column)",
    )
    status = Column(
        String(50),
        nullable=False,
        default="draft",
        index=True,
        comment="CampaignStatus enum: draft|queued|running|paused|completed",
    )
    total_contacts = Column(Integer, nullable=False, default=0)
    completed_contacts = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    contacts = relationship(
        "CampaignContact",
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("idx_campaign_clinic_status", "clinic_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Campaign(id={self.id}, name={self.name!r}, status={self.status})>"
