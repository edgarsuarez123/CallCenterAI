"""extend clinic_integration with HEDIS campaign defaults

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-20 00:01:00.000000

Adds 9 columns to clinic_integration for HEDIS campaign operational defaults:
    timezone, calling_hours_start, calling_hours_end,
    campaign_concurrency_limit, voicemail_retry_hours, no_answer_retry_hours,
    error_retry_hours, max_attempts, retell_outbound_number
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clinic_integration",
        sa.Column("timezone", sa.String(100), nullable=False, server_default="America/New_York"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("calling_hours_start", sa.String(5), nullable=False, server_default="09:00"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("calling_hours_end", sa.String(5), nullable=False, server_default="18:00"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("campaign_concurrency_limit", sa.Integer, nullable=False, server_default="3"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("voicemail_retry_hours", sa.Integer, nullable=False, server_default="4"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("no_answer_retry_hours", sa.Integer, nullable=False, server_default="2"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("error_retry_hours", sa.Integer, nullable=False, server_default="24"),
    )
    op.add_column(
        "clinic_integration",
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
    )
    op.add_column(
        "clinic_integration", sa.Column("retell_outbound_number", sa.String, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clinic_integration", "retell_outbound_number")
    op.drop_column("clinic_integration", "max_attempts")
    op.drop_column("clinic_integration", "error_retry_hours")
    op.drop_column("clinic_integration", "no_answer_retry_hours")
    op.drop_column("clinic_integration", "voicemail_retry_hours")
    op.drop_column("clinic_integration", "campaign_concurrency_limit")
    op.drop_column("clinic_integration", "calling_hours_end")
    op.drop_column("clinic_integration", "calling_hours_start")
    op.drop_column("clinic_integration", "timezone")
