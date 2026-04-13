# data/models/clinic.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from Clinic_app.common.database import Base


class Clinic(Base):
    """
    Represents a tenant container — one clinic = one deployed instance.
    """
    __tablename__ = "clinic"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    network_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    name = Column(Text, nullable=False)
    tier = Column(String(50), nullable=False)  # basic/pro/enterprise
    status = Column(String(50), nullable=False, default="active", index=True)  # active/suspended
    license_token = Column(Text, nullable=False, unique=True)
    license_expires_at = Column(DateTime(timezone=True), nullable=True)
    business_hours_start = Column(String(5), nullable=False, default="09:00")  # HH:MM format
    business_hours_end = Column(String(5), nullable=False, default="17:00")  # HH:MM format
    max_concurrency = Column(Integer, nullable=False, default=3)
    features = Column(JSONB, nullable=False, default=dict)  # {"reminders": true, "hedis": false}
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<Clinic(id={self.id}, name={self.name}, status={self.status})>"
