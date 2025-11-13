# Clinic_app/data/models/booking_audit.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Enum as SQLEnum
from Clinic_app.common.database import Base
from Clinic_app.data.enums import BookingAction


class BookingAudit(Base):
    """
    Tracks every change to booking status.
    Immutable event history for debugging and HIPAA compliance.
    """
    __tablename__ = "booking_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("booking.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(SQLEnum(BookingAction), nullable=False)  # hold/confirm/cancel/expire
    actor = Column(String, nullable=False)  # System or user identifier
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index('idx_booking_audit_booking', 'booking_id'),  # All changes to a booking
        Index('idx_booking_audit_clinic_timestamp', 'clinic_id', 'timestamp'),  # Tenant-scoped time queries
    )

    # Relationships
    clinic = relationship("Clinic", backref="booking_audits")
    booking = relationship("Booking", backref="audit_entries")

    def __repr__(self):
        return f"<BookingAudit(id={self.id}, booking_id={self.booking_id}, action={self.action}, timestamp={self.timestamp})>"

