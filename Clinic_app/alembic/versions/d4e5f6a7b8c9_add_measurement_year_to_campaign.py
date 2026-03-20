"""add measurement_year to campaign

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-20 00:02:00.000000

Adds measurement_year to campaign for HEDIS cross-year dedup.
Dedup rule: clinic_id + phone_hash + gap_type + measurement_year must be
unique among non-terminal contacts (not EXHAUSTED or DECLINED).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaign',
        sa.Column('measurement_year', sa.Integer(), nullable=False, server_default='2026'))

    # Index to accelerate dedup JOIN query:
    #   SELECT cc.id FROM campaign_contact cc
    #   JOIN campaign c ON cc.campaign_id = c.id
    #   WHERE cc.clinic_id = :cid AND cc.phone_hash = :hash
    #     AND cc.gap_type = :gap AND c.measurement_year = :year
    #     AND cc.status NOT IN ('exhausted', 'declined')
    op.create_index('idx_campaign_year', 'campaign', ['clinic_id', 'measurement_year'])


def downgrade() -> None:
    op.drop_index('idx_campaign_year', table_name='campaign')
    op.drop_column('campaign', 'measurement_year')
