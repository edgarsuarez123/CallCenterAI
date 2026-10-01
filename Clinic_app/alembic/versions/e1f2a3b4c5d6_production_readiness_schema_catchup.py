"""Production-readiness schema catch-up

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-01

Adds columns that exist in the ORM models but were missing from the migration
chain after the retell-branch merge:

campaign:
  - reason             TEXT nullable
  - completed_contacts INTEGER not null default 0

campaign_contact:
  - reason              TEXT nullable
  - outcome             VARCHAR(50) not null default 'pending'
  - retell_call_id      VARCHAR(255) nullable
  - call_duration_seconds INTEGER nullable
  - call_date           TIMESTAMPTZ nullable
  - notes               TEXT nullable

Also fixes a type/nullability mismatch on campaign_contact.priority_order:
  - migration f6a7b8c9d0e1 created it as INTEGER NOT NULL server_default='1'
  - model defines it as SmallInteger nullable
  Action: drop the NOT NULL constraint and server default

Dead-branch cleanup: c7d8e9f0a1b2_add_campaign_tables.py was deleted
(it branched off a1b2c3d4e5f6, same as b2c3d4e5f6a7, and was never part
of the linear migration chain; keeping it caused Alembic to report multiple
heads).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── campaign: add missing columns ──────────────────────────────────────────
    # reason: required by application logic; added nullable so existing rows
    # are unaffected. Application layer enforces non-null on create.
    op.add_column("campaign", sa.Column("reason", sa.Text(), nullable=True))

    # completed_contacts: legacy counter kept for backward-compat with older
    # campaign service path; new code uses called_count/booked_count/failed_count.
    op.add_column(
        "campaign",
        sa.Column(
            "completed_contacts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # ── campaign_contact: add missing columns ──────────────────────────────────
    op.add_column(
        "campaign_contact",
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column(
            "outcome",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("retell_call_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("call_duration_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("call_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaign_contact",
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # ── campaign_contact.priority_order: fix nullability mismatch ──────────────
    # Migration f6a7b8c9d0e1 created it INTEGER NOT NULL default 1.
    # Model defines it SmallInteger nullable (hospital_flu gets 0, others NULL).
    conn.execute(sa.text("ALTER TABLE campaign_contact ALTER COLUMN priority_order DROP NOT NULL"))
    conn.execute(sa.text("ALTER TABLE campaign_contact ALTER COLUMN priority_order DROP DEFAULT"))

    # Add index on campaign_contact.outcome for worker queue queries
    op.create_index(
        "idx_campaign_contact_outcome_catchup",
        "campaign_contact",
        ["campaign_id", "outcome"],
    )


def downgrade() -> None:
    op.drop_index("idx_campaign_contact_outcome_catchup", table_name="campaign_contact")

    # Restore priority_order constraints
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE campaign_contact "
            "ALTER COLUMN priority_order SET NOT NULL, "
            "ALTER COLUMN priority_order SET DEFAULT 1"
        )
    )

    op.drop_column("campaign_contact", "notes")
    op.drop_column("campaign_contact", "call_date")
    op.drop_column("campaign_contact", "call_duration_seconds")
    op.drop_column("campaign_contact", "retell_call_id")
    op.drop_column("campaign_contact", "outcome")
    op.drop_column("campaign_contact", "reason")

    op.drop_column("campaign", "completed_contacts")
    op.drop_column("campaign", "reason")
