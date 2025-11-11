"""Add unique partial index for appointments to prevent double-booking

Revision ID: 0011_appt_unique_idx
Revises: 0010_add_prefix_indexes
Create Date: 2025-01-20 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0011_appt_unique_idx'
down_revision = '0010_add_prefix_indexes'
branch_labels = None
depends_on = None


def upgrade():
    """Add unique partial index to prevent double-booking at database level."""
    # Add unique partial index on appointments to prevent double-booking
    # This is the final safety net that prevents two appointments for the same
    # provider at the same time, even if slot system is bypassed
    # Note: appointments table uses appointment_date, not start_time/end_time
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_booked 
        ON appointments(provider_id, appointment_date, duration_minutes) 
        WHERE status IN ('booked', 'scheduled', 'confirmed');
    """)
    
    # Add performance index for faster slot queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_appointments_provider_date 
        ON appointments(provider_id, appointment_date) 
        WHERE status IN ('booked', 'scheduled', 'confirmed');
    """)


def downgrade():
    """Remove unique partial index."""
    op.execute("DROP INDEX IF EXISTS idx_appointments_unique_booked;")
    op.execute("DROP INDEX IF EXISTS idx_appointments_provider_date;")

