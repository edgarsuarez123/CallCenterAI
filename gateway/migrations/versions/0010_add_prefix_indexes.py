"""Add prefix indexes for patient and provider searches

Revision ID: 0010_add_prefix_indexes
Revises: 0009_clean_schema
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0010_add_prefix_indexes'
down_revision = '0009_clean_schema'
branch_labels = None
depends_on = None


def upgrade():
    """Add B-tree indexes for prefix searches."""
    # Add B-tree indexes for prefix searches
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_patient_name_prefix 
        ON patients(name_token text_pattern_ops);
    """)
    
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_provider_name_prefix 
        ON providers(name text_pattern_ops);
    """)
    
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_clinic_name_prefix 
        ON clinics(clinic_name text_pattern_ops);
    """)
    
    # Add composite indexes for common queries
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_patient_clinic_active 
        ON patients(clinic_id, is_deleted) WHERE is_deleted = 'no';
    """)
    
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_provider_clinic_available 
        ON providers(clinic_id, is_available, is_deleted) WHERE is_deleted = 'no';
    """)


def downgrade():
    """Remove prefix indexes."""
    op.execute("DROP INDEX IF EXISTS idx_patient_name_prefix;")
    op.execute("DROP INDEX IF EXISTS idx_provider_name_prefix;")
    op.execute("DROP INDEX IF EXISTS idx_clinic_name_prefix;")
    op.execute("DROP INDEX IF EXISTS idx_patient_clinic_active;")
    op.execute("DROP INDEX IF EXISTS idx_provider_clinic_available;")
