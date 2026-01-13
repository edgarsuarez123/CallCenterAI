# Clinic_app/data/models/availability_slot.py
import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint, CheckConstraint, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID, ENUM as PG_ENUM
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base
from Clinic_app.data.enums import SlotStatus, SlotSource


class SlotStatusEnum(TypeDecorator):
    """Type decorator to ensure SlotStatus enum values are used (not names)."""
    impl = PG_ENUM
    cache_ok = True
    
    def __init__(self):
        super().__init__('free', 'booked', 'blocked', name='slotstatus', create_type=False)
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, SlotStatus):
            return value.value  # Use enum value, not name
        return value
    
    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return SlotStatus(value)


class SlotSourceEnum(TypeDecorator):
    """Type decorator to ensure SlotSource enum values are used (not names)."""
    impl = PG_ENUM
    cache_ok = True
    
    def __init__(self):
        super().__init__('csv', 'gcal', name='slotsource', create_type=False)
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, SlotSource):
            return value.value  # Use enum value, not name
        return value
    
    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return SlotSource(value)


class AvailabilitySlot(Base):
    """
    Tracks open and filled time blocks for scheduling.
    Provides canonical list of bookable slots, with provenance for sync integrity.
    """
    __tablename__ = "availability_slot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("provider.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_start = Column(DateTime(timezone=True), nullable=False)
    slot_end = Column(DateTime(timezone=True), nullable=False)
    source = Column(SlotSourceEnum(), nullable=False)  # csv/gcal
    status = Column(SlotStatusEnum(), nullable=False, default=SlotStatus.FREE.value)  # free/booked/blocked
    last_sync_at = Column(DateTime(timezone=True), nullable=True)  # Last refresh time

    # Unique constraint: prevents duplicate slots for same provider/time
    __table_args__ = (
        UniqueConstraint('provider_id', 'slot_start', 'slot_end', name='uq_provider_slot_time'),
        Index('idx_clinic_status_start', 'clinic_id', 'status', 'slot_start'),  # For efficient "find free slots" queries
        CheckConstraint('slot_end > slot_start', name='check_availability_slot_end_after_start'),
    )

    # Relationships
    clinic = relationship("Clinic", backref="availability_slots")
    provider = relationship("Provider", backref="availability_slots")

    def __repr__(self):
        return f"<AvailabilitySlot(id={self.id}, provider_id={self.provider_id}, status={self.status}, slot_start={self.slot_start})>"

