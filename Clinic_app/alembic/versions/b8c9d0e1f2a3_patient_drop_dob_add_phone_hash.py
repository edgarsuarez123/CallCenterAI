"""patient: drop dob_token, add phone_hash

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-03-25

PHI Rule #2: Never store patient DOB in the database.
PHI Rule #8: Phone numbers must have both an encrypted column AND a SHA-256 hash column.

Changes:
  - patient.dob_token  → DROPPED (DOB must not be persisted; name_dob_hash is sufficient for lookup)
  - patient.phone_hash → ADDED   (SHA-256 hash of phone for dedup, mirrors CampaignContact pattern)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop dob_token — PHI Rule #2 violation
    op.drop_column("patient", "dob_token")

    # Add phone_hash for efficient dedup without decryption — PHI Rule #8
    op.add_column(
        "patient",
        sa.Column("phone_hash", sa.String(64), nullable=True)
    )
    op.create_index("idx_patient_clinic_phone_hash", "patient", ["clinic_id", "phone_hash"])


def downgrade() -> None:
    op.drop_index("idx_patient_clinic_phone_hash", table_name="patient")
    op.drop_column("patient", "phone_hash")

    # Restore dob_token as nullable (we cannot recover the original data)
    op.add_column(
        "patient",
        sa.Column("dob_token", sa.LargeBinary(), nullable=True)
    )
