"""Add soft delete fields for HIPAA compliance

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add soft delete fields to models that contain PHI or are critical for HIPAA compliance.
    
    Models that need soft delete:
    - patients: Contains PHI (name, phone, email, DOB, insurance)
    - calls: Contains PHI (caller phone, call content)
    - appointments: Contains PHI (patient info, appointment details)
    - call_notes: Contains PHI (call summaries, patient notes)
    - mappings: Contains encrypted PHI tokens
    - audit_logs: Contains audit trail of PHI access
    - clinic_usage: Contains usage metrics (may contain PHI patterns)
    
    Models that DON'T need soft delete:
    - providers: Non-PHI business data
    - clinics: Non-PHI business data
    - appointment_slots: Non-PHI scheduling data
    - appointment_blocks: Non-PHI scheduling data
    - call_queue: Non-PHI routing data
    - system_config: Non-PHI configuration data
    - clinic_licenses: Non-PHI business data
    - google_calendar_credentials: Encrypted OAuth tokens (not PHI)
    """
    
    # Add soft delete fields to patients table
    op.add_column('patients', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('patients', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('patients', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('patients', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add soft delete fields to calls table
    op.add_column('calls', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('calls', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('calls', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('calls', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add soft delete fields to appointments table
    op.add_column('appointments', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('appointments', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('appointments', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('appointments', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add soft delete fields to call_notes table
    op.add_column('call_notes', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('call_notes', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('call_notes', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('call_notes', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add soft delete fields to mappings table
    op.add_column('mappings', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('mappings', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mappings', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('mappings', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add soft delete fields to audit_logs table
    op.add_column('audit_logs', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('audit_logs', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('audit_logs', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('audit_logs', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add soft delete fields to clinic_usage table
    op.add_column('clinic_usage', sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'))
    op.add_column('clinic_usage', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clinic_usage', sa.Column('deleted_by', sa.String(64), nullable=True))
    op.add_column('clinic_usage', sa.Column('deletion_reason', sa.String(200), nullable=True))
    
    # Add check constraints for is_deleted field
    op.create_check_constraint(
        'check_patients_is_deleted',
        'patients',
        "is_deleted IN ('yes', 'no')"
    )
    
    op.create_check_constraint(
        'check_calls_is_deleted',
        'calls',
        "is_deleted IN ('yes', 'no')"
    )
    
    op.create_check_constraint(
        'check_appointments_is_deleted',
        'appointments',
        "is_deleted IN ('yes', 'no')"
    )
    
    op.create_check_constraint(
        'check_call_notes_is_deleted',
        'call_notes',
        "is_deleted IN ('yes', 'no')"
    )
    
    op.create_check_constraint(
        'check_mappings_is_deleted',
        'mappings',
        "is_deleted IN ('yes', 'no')"
    )
    
    op.create_check_constraint(
        'check_audit_logs_is_deleted',
        'audit_logs',
        "is_deleted IN ('yes', 'no')"
    )
    
    op.create_check_constraint(
        'check_clinic_usage_is_deleted',
        'clinic_usage',
        "is_deleted IN ('yes', 'no')"
    )
    
    # Add indexes for soft delete queries
    op.create_index('idx_patients_active_only', 'patients', ['patient_id'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    op.create_index('idx_calls_active_only', 'calls', ['call_id'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    op.create_index('idx_appointments_active_only', 'appointments', ['appointment_id'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    op.create_index('idx_call_notes_active_only', 'call_notes', ['notes_id'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    op.create_index('idx_mappings_active_only', 'mappings', ['token'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    op.create_index('idx_audit_logs_active_only', 'audit_logs', ['log_id'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    op.create_index('idx_clinic_usage_active_only', 'clinic_usage', ['usage_id'], 
                   postgresql_where=sa.text("is_deleted = 'no'"))
    
    # Add indexes for deletion tracking
    op.create_index('idx_patients_deleted_at', 'patients', ['deleted_at'])
    op.create_index('idx_calls_deleted_at', 'calls', ['deleted_at'])
    op.create_index('idx_appointments_deleted_at', 'appointments', ['deleted_at'])
    op.create_index('idx_call_notes_deleted_at', 'call_notes', ['deleted_at'])
    op.create_index('idx_mappings_deleted_at', 'mappings', ['deleted_at'])
    op.create_index('idx_audit_logs_deleted_at', 'audit_logs', ['deleted_at'])
    op.create_index('idx_clinic_usage_deleted_at', 'clinic_usage', ['deleted_at'])
    
    # Add indexes for deletion by user
    op.create_index('idx_patients_deleted_by', 'patients', ['deleted_by'])
    op.create_index('idx_calls_deleted_by', 'calls', ['deleted_by'])
    op.create_index('idx_appointments_deleted_by', 'appointments', ['deleted_by'])
    op.create_index('idx_call_notes_deleted_by', 'call_notes', ['deleted_by'])
    op.create_index('idx_mappings_deleted_by', 'mappings', ['deleted_by'])
    op.create_index('idx_audit_logs_deleted_by', 'audit_logs', ['deleted_by'])
    op.create_index('idx_clinic_usage_deleted_by', 'clinic_usage', ['deleted_by'])


def downgrade():
    """
    Remove soft delete fields and related constraints/indexes.
    """
    
    # Drop indexes first
    op.drop_index('idx_clinic_usage_deleted_by')
    op.drop_index('idx_audit_logs_deleted_by')
    op.drop_index('idx_mappings_deleted_by')
    op.drop_index('idx_call_notes_deleted_by')
    op.drop_index('idx_appointments_deleted_by')
    op.drop_index('idx_calls_deleted_by')
    op.drop_index('idx_patients_deleted_by')
    
    op.drop_index('idx_clinic_usage_deleted_at')
    op.drop_index('idx_audit_logs_deleted_at')
    op.drop_index('idx_mappings_deleted_at')
    op.drop_index('idx_call_notes_deleted_at')
    op.drop_index('idx_appointments_deleted_at')
    op.drop_index('idx_calls_deleted_at')
    op.drop_index('idx_patients_deleted_at')
    
    op.drop_index('idx_clinic_usage_active_only')
    op.drop_index('idx_audit_logs_active_only')
    op.drop_index('idx_mappings_active_only')
    op.drop_index('idx_call_notes_active_only')
    op.drop_index('idx_appointments_active_only')
    op.drop_index('idx_calls_active_only')
    op.drop_index('idx_patients_active_only')
    
    # Drop check constraints
    op.drop_constraint('check_clinic_usage_is_deleted', 'clinic_usage', type_='check')
    op.drop_constraint('check_audit_logs_is_deleted', 'audit_logs', type_='check')
    op.drop_constraint('check_mappings_is_deleted', 'mappings', type_='check')
    op.drop_constraint('check_call_notes_is_deleted', 'call_notes', type_='check')
    op.drop_constraint('check_appointments_is_deleted', 'appointments', type_='check')
    op.drop_constraint('check_calls_is_deleted', 'calls', type_='check')
    op.drop_constraint('check_patients_is_deleted', 'patients', type_='check')
    
    # Drop columns
    op.drop_column('clinic_usage', 'deletion_reason')
    op.drop_column('clinic_usage', 'deleted_by')
    op.drop_column('clinic_usage', 'deleted_at')
    op.drop_column('clinic_usage', 'is_deleted')
    
    op.drop_column('audit_logs', 'deletion_reason')
    op.drop_column('audit_logs', 'deleted_by')
    op.drop_column('audit_logs', 'deleted_at')
    op.drop_column('audit_logs', 'is_deleted')
    
    op.drop_column('mappings', 'deletion_reason')
    op.drop_column('mappings', 'deleted_by')
    op.drop_column('mappings', 'deleted_at')
    op.drop_column('mappings', 'is_deleted')
    
    op.drop_column('call_notes', 'deletion_reason')
    op.drop_column('call_notes', 'deleted_by')
    op.drop_column('call_notes', 'deleted_at')
    op.drop_column('call_notes', 'is_deleted')
    
    op.drop_column('appointments', 'deletion_reason')
    op.drop_column('appointments', 'deleted_by')
    op.drop_column('appointments', 'deleted_at')
    op.drop_column('appointments', 'is_deleted')
    
    op.drop_column('calls', 'deletion_reason')
    op.drop_column('calls', 'deleted_by')
    op.drop_column('calls', 'deleted_at')
    op.drop_column('calls', 'is_deleted')
    
    op.drop_column('patients', 'deletion_reason')
    op.drop_column('patients', 'deleted_by')
    op.drop_column('patients', 'deleted_at')
    op.drop_column('patients', 'is_deleted')
