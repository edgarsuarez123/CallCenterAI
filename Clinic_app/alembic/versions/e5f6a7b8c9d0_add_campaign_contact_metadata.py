"""add campaign_contact metadata columns for HEDIS outbound

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-21 12:00:00.000000

Adds encrypted patient name/DOB and plain provider_name/payer for Retell metadata.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_contact",
        sa.Column("patient_name_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("patient_dob_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("provider_name", sa.String(), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("payer", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaign_contact", "payer")
    op.drop_column("campaign_contact", "provider_name")
    op.drop_column("campaign_contact", "patient_dob_encrypted")
    op.drop_column("campaign_contact", "patient_name_encrypted")
