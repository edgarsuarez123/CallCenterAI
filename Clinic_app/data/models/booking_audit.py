# Clinic_app/data/models/booking_audit.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID, ENUM as PG_ENUM
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base
from Clinic_app.data.enums import BookingAction


class BookingActionEnum(TypeDecorator):
    """Type decorator to ensure BookingAction enum values are used (not names)."""

    impl = PG_ENUM
    cache_ok = True

    def __init__(self):
        super().__init__(
            "hold", "confirm", "cancel", "expire", name="bookingaction", create_type=False
        )

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, BookingAction):
            return value.value  # Use enum value, not name
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return BookingAction(value)


class BookingAudit(Base):
    """
    Tracks every change to booking status.
    Immutable event history for debugging and HIPAA compliance.
    """

    __tablename__ = "booking_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(
        UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True
    )
    booking_id = Column(
        UUID(as_uuid=True),
        ForeignKey("booking.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action = Column(BookingActionEnum(), nullable=False)  # hold/confirm/cancel/expire
    actor = Column(String, nullable=False)  # System or user identifier
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Indexes
    __table_args__ = (
        Index("idx_booking_audit_booking", "booking_id"),  # All changes to a booking
        Index(
            "idx_booking_audit_clinic_timestamp", "clinic_id", "timestamp"
        ),  # Tenant-scoped time queries
    )

    # Relationships
    clinic = relationship("Clinic", backref="booking_audits")
    booking = relationship("Booking", backref="audit_entries")

    def __repr__(self):
        return f"<BookingAudit(id={self.id}, booking_id={self.booking_id}, action={self.action}, timestamp={self.timestamp})>"
