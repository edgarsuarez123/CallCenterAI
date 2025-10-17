"""Add provider_clinics association table and update call status enum

Revision ID: 0006
Revises: bab5a84829b2
Create Date: 2025-01-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '0006'
down_revision = 'bab5a84829b2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create provider_clinics association table
    op.create_table('provider_clinics',
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('clinic_id', sa.String(length=64), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.String(length=10), nullable=False, server_default='yes'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.clinic_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('provider_id', 'clinic_id')
    )
    
    # Add indexes
    op.create_index('idx_provider_clinics_provider', 'provider_clinics', ['provider_id'])
    op.create_index('idx_provider_clinics_clinic', 'provider_clinics', ['clinic_id'])
    
    # Note: CallStatus enum now includes INITIALIZING, INITIATED, ACTIVE
    # No DB changes needed for enum - it's application-level

def downgrade() -> None:
    op.drop_index('idx_provider_clinics_clinic', table_name='provider_clinics')
    op.drop_index('idx_provider_clinics_provider', table_name='provider_clinics')
    op.drop_table('provider_clinics')
