# Clinic_app/data/models/provider.py
import uuid
from sqlalchemy import Column, String, Integer, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class Provider(Base):
    """
    Defines a doctor or service provider that patients can book with.
    """
    __tablename__ = "provider"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(Text, nullable=False)  # Used in AI voice replies, GCal titles
    external_id = Column(String, nullable=True)  # Stable EHR/CSV reference (optional)
    google_calendar_id = Column(String, nullable=True)  # Linked Google Calendar
    timezone = Column(String(100), nullable=False)  # e.g., "America/New_York"
    booking_duration_mins = Column(Integer, nullable=False, default=30)  # Default appointment length
    active = Column(Boolean, nullable=False, default=True)  # Currently bookable

    # Relationships
    clinic = relationship("Clinic", backref="providers")
    # availability_slots and bookings relationships will be defined in those models

    def __repr__(self):
        return f"<Provider(id={self.id}, display_name={self.display_name}, clinic_id={self.clinic_id})>"

