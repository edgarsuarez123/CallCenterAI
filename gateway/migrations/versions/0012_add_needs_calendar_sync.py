"""Add needs_calendar_sync flag to appointments

Revision ID: 0012_add_needs_calendar_sync
Revises: 0011_add_appointment_unique_index
Create Date: 2025-01-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0012_add_needs_calendar_sync'
down_revision = '0011_appt_unique_idx'
branch_labels = None
depends_on = None


def upgrade():
    """Add needs_calendar_sync column to appointments table."""
    # Add needs_calendar_sync column with default False
    op.add_column('appointments', 
        sa.Column('needs_calendar_sync', sa.Boolean(), nullable=False, server_default='false')
    )
    
    # Add index for faster queries of appointments needing sync
    op.create_index(
        'idx_appointments_needs_sync',
        'appointments',
        ['needs_calendar_sync'],
        unique=False,
        postgresql_where=sa.text("needs_calendar_sync = true")
    )


def downgrade():
    """Remove needs_calendar_sync column from appointments table."""
    op.drop_index('idx_appointments_needs_sync', table_name='appointments')
    op.drop_column('appointments', 'needs_calendar_sync')

