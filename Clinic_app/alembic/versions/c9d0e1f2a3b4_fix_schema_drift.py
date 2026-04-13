"""fix schema drift: add clinic business_hours, call_log tentative_booking_id, drop patient_dob_encrypted

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-03-31

Resolves model-migration drift:
  - clinic.business_hours_start / business_hours_end: present in Clinic model,
    missing from DB — blocks all Clinic queries.
  - call_log.tentative_booking_id: present in CallLog model, used by Retell
    webhook hold-cleanup logic, missing from DB.
  - campaign_contact.patient_dob_encrypted: added by migration e5f6a7b8c9d0
    but deliberately removed from CampaignContact model (PHI Rule #2:
    never store patient DOB in the database).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # clinic: add business_hours columns (model default 09:00–17:00)
    op.add_column(
        "clinic",
        sa.Column("business_hours_start", sa.String(5), nullable=False, server_default="09:00"),
    )
    op.add_column(
        "clinic",
        sa.Column("business_hours_end", sa.String(5), nullable=False, server_default="17:00"),
    )

    # call_log: add tentative_booking_id for hold cleanup on call_ended
    op.add_column(
        "call_log",
        sa.Column("tentative_booking_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # campaign_contact: drop dead DOB column — PHI Rule #2
    op.drop_column("campaign_contact", "patient_dob_encrypted")


def downgrade() -> None:
    # Restore patient_dob_encrypted (nullable; data is lost)
    op.add_column(
        "campaign_contact",
        sa.Column("patient_dob_encrypted", sa.LargeBinary(), nullable=True),
    )

    op.drop_column("call_log", "tentative_booking_id")
    op.drop_column("clinic", "business_hours_end")
    op.drop_column("clinic", "business_hours_start")
