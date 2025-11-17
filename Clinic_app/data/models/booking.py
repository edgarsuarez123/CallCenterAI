# Clinic_app/data/models/booking.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index, CheckConstraint
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Enum as SQLEnum
from Clinic_app.common.database import Base
from Clinic_app.data.enums import BookingStatus


class Booking(Base):
    """
    Authoritative record of appointments.
    Prevents double-booking through partial unique constraint.
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

    # Partial unique index: prevents double-booking for tentative/confirmed bookings
    # Canceled bookings don't count, so slots can be reused
    __table_args__ = (
        Index(
            'idx_booking_unique_slot',
            'provider_id',
            'slot_start',
            'slot_end',
            unique=True,
            postgresql_where=text("status IN ('tentative', 'confirmed')")
        ),
        Index('idx_status_hold_expires', 'status', 'hold_expires_at'),  # For reaper efficiency
        CheckConstraint('slot_end > slot_start', name='check_booking_slot_end_after_start'),
    )

    # Relationships
    clinic = relationship("Clinic", backref="bookings")
    provider = relationship("Provider", backref="bookings")
    patient = relationship("Patient", backref="bookings")

    def __repr__(self):
        return f"<Booking(id={self.id}, provider_id={self.provider_id}, patient_id={self.patient_id}, status={self.status})>"

