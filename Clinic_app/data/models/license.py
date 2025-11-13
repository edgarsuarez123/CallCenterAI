# data/models/license.py
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class License(Base):
    """
    Defines the runtime authorization, concurrency, and feature toggles.
    1:1 relationship with Clinic.
    """
    __tablename__ = "license"

    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), primary_key=True)
    token = Column(String, nullable=False, unique=True)
    status = Column(String(50), nullable=False, default="active")  # active/suspended/expired
    tier = Column(String(50), nullable=False)
    max_concurrency = Column(Integer, nullable=False)
    features = Column(JSONB, nullable=False, default={})  # {"reminders": true, "hedis": false}
    issued_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    clinic = relationship("Clinic", backref="license")

    def __repr__(self):
        return f"<License(clinic_id={self.clinic_id}, status={self.status}, tier={self.tier})>"

