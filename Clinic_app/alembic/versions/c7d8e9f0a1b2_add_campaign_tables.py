"""Add campaign and campaign_contact tables

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-30 00:00:00.000000

Adds the outbound HEDIS campaign system:
- campaign: groups a batch of outreach calls
- campaign_contact: one row per patient with encrypted PHI and outcome tracking
- CampaignStatus and ContactOutcome string enums (stored as VARCHAR)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── campaign ──────────────────────────────────────────────────────────
    op.create_table(
        "campaign",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("total_contacts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_contacts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_campaign_clinic_id", "campaign", ["clinic_id"])
    op.create_index("idx_campaign_status", "campaign", ["status"])
    op.create_index(
        "idx_campaign_clinic_status", "campaign", ["clinic_id", "status"]
    )

    # ── campaign_contact ──────────────────────────────────────────────────
    op.create_table(
        "campaign_contact",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clinic_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_name_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("phone_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "outcome",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("retell_call_id", sa.String(255), nullable=True),
        sa.Column("call_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("call_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_campaign_contact_campaign_id", "campaign_contact", ["campaign_id"]
    )
    op.create_index(
        "idx_campaign_contact_clinic_campaign",
        "campaign_contact",
        ["clinic_id", "campaign_id"],
    )
    op.create_index(
        "idx_campaign_contact_outcome",
        "campaign_contact",
        ["campaign_id", "outcome"],
    )
    op.create_index(
        "idx_campaign_contact_phone_hash",
        "campaign_contact",
        ["clinic_id", "phone_hash"],
    )


def downgrade() -> None:
    op.drop_table("campaign_contact")
    op.drop_table("campaign")
