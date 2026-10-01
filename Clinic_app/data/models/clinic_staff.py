# Clinic_app/data/models/clinic_staff.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from Clinic_app.common.database import Base


class ClinicStaff(Base):
    """
    Staff member linked to a clinic via Google OAuth.
    One staff member can belong to multiple clinics (multiple rows, same google_sub).
    Identity is Google's responsibility — we manage clinic membership only.
    """

    __tablename__ = "clinic_staff"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    clinic_id = Column(
        UUID(as_uuid=True), ForeignKey("clinic.id", ondelete="CASCADE"), nullable=False, index=True
    )
    google_sub = Column(
        String(255), nullable=False
    )  # Google OAuth 'sub' claim — stable identifier, not email
    email = Column(String(255), nullable=False)  # For display only — not used as auth key
    role = Column(String(50), nullable=False, default="viewer")  # "admin" | "viewer"
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("clinic_id", "google_sub", name="uq_clinic_staff_clinic_sub"),
        Index(
            "idx_staff_google_sub", "google_sub"
        ),  # Fast lookup on OAuth callback across all clinics
    )

    # Relationships
    clinic = relationship("Clinic", backref="staff")

    def __repr__(self) -> str:
        return f"<ClinicStaff(id={self.id}, clinic_id={self.clinic_id}, role={self.role})>"
