"""merge license table into clinic

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-03-31

The License table duplicates Clinic fields (tier, token) with no referential
constraint between them, creating a data-integrity risk.  This migration
absorbs the two License-only columns (max_concurrency, features) into the
clinic table, copies existing data, and drops the license table.

After this migration the Clinic row is the single source of truth for
tenant identity, subscription tier, concurrency limits, and feature flags.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to clinic (server defaults for any existing rows without a license)
    op.add_column(
        "clinic",
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "clinic",
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default="{}"),
    )

    # Copy data from license to clinic for rows that have a license
    op.execute(
        text(
            "UPDATE clinic SET max_concurrency = l.max_concurrency, features = l.features "
            "FROM license l WHERE l.clinic_id = clinic.id"
        )
    )

    # Drop the license table (FK constraint drops automatically with the table)
    op.drop_table("license")


def downgrade() -> None:
    # Recreate license table
    op.create_table(
        "license",
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("tier", sa.String(50), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "features", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Copy data back from clinic to license (best-effort; token uses license_token)
    op.execute(
        text(
            "INSERT INTO license (clinic_id, token, tier, max_concurrency, features) "
            "SELECT id, license_token, tier, max_concurrency, features FROM clinic"
        )
    )

    # Drop the absorbed columns from clinic
    op.drop_column("clinic", "features")
    op.drop_column("clinic", "max_concurrency")
