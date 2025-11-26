# Clinic_app/data/models/booking.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Enum as SQLEnum
from Clinic_app.common.database import Base
from Clinic_app.data.enums import BookingStatus


class Booking(Base):
    """
    Authoritative record of appointments.
    
    Capacity enforcement is done at the application level using SELECT FOR UPDATE
    to support providers with capacity > 1 (multiple concurrent bookings per slot).
    """
    __tablename__ = "booking"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("provider.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patient.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_start = Column(DateTime(timezone=True), nullable=False)
    slot_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(SQLEnum(BookingStatus), nullable=False, default=BookingStatus.TENTATIVE)
    hold_token = Column(UUID(as_uuid=True), nullable=True)  # Temporary reservation token (only for tentative)
    hold_expires_at = Column(DateTime(timezone=True), nullable=True)  # Expiration timestamp (only for tentative)
    google_event_id = Column(String, nullable=True)  # Linked GCal event (nullable for graceful degradation)
    source = Column(String, nullable=True)  # Origin: call/reminder/hedis/manual
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # Non-unique index for slot lookups (capacity enforcement at application level)
        Index('idx_booking_slot_lookup', 'provider_id', 'slot_start', 'slot_end', 'status'),
        # Index for reaper efficiency (finding expired tentative holds)
        Index('idx_status_hold_expires', 'status', 'hold_expires_at'),
        # End must be after start
        CheckConstraint('slot_end > slot_start', name='check_booking_slot_end_after_start'),
    )

    # Relationships
    clinic = relationship("Clinic", backref="bookings")
    provider = relationship("Provider", backref="bookings")
    patient = relationship("Patient", backref="bookings")

    def __repr__(self):
        return f"<Booking(id={self.id}, provider_id={self.provider_id}, patient_id={self.patient_id}, status={self.status})>"

