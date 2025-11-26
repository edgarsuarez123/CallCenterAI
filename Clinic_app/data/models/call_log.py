# Clinic_app/data/models/call_log.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from Clinic_app.common.database import Base


class CallLog(Base):
    """
    PHI-free call metrics for usage tracking and reporting.
    No foreign keys to preserve data even if clinic is deleted.
    """
    __tablename__ = "call_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # No FK - PHI-free, clinic may be deleted
    call_type = Column(String, nullable=False)  # 'inbound', 'outbound_reminder', 'outbound_campaign'
    related_id = Column(UUID(as_uuid=True), nullable=True)  # Can reference booking.id or campaign_contact.id
    tentative_booking_id = Column(UUID(as_uuid=True), nullable=True)  # For hold cleanup on call_ended
    duration_seconds = Column(Integer, nullable=True)  # Calculated from webhook events
    outcome = Column(String, nullable=True)  # 'answered', 'no_answer', 'busy', 'failed', 'voicemail'
    retell_call_id = Column(String, nullable=True, index=True)  # Retell's call identifier for webhook correlation
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "call_type IN ('inbound', 'outbound_reminder', 'outbound_campaign')",
            name='check_call_log_call_type'
        ),
        Index('idx_clinic_call_type_timestamp', 'clinic_id', 'call_type', 'created_at'),  # For usage reporting
    )

    def __repr__(self):
        return f"<CallLog(id={self.id}, clinic_id={self.clinic_id}, call_type={self.call_type}, retell_call_id={self.retell_call_id})>"

