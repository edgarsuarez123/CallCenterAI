# Clinic_app/data/models/phone_route.py
from sqlalchemy import Column, String, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class PhoneRoute(Base):
    """
    Maps inbound phone numbers (DIDs) to clinics.
    Supports a single global ACS webhook and routes inbound calls to the correct clinic container.
    """
    __tablename__ = "phone_route"

    did_e164 = Column(String, primary_key=True)  # E.164 format phone number (e.g., +15551234567)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True)
    container_url = Column(Text, nullable=False)  # Internal container address for gateway reverse-proxy
    active = Column(Boolean, nullable=False, default=True)  # Route status

    # Relationship
    clinic = relationship("Clinic", backref="phone_routes")

    def __repr__(self):
        return f"<PhoneRoute(did_e164={self.did_e164}, clinic_id={self.clinic_id}, active={self.active})>"

