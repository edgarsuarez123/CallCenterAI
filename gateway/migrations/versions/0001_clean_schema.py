"""Clean database schema from scratch

Revision ID: 0001_clean
Revises: 
Create Date: 2025-10-26 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_clean_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create all tables with clinic_id from the start"""
    
    # Create clinics table first (no dependencies)
    op.create_table('clinics',
        sa.Column('clinic_id', sa.String(64), primary_key=True),
        sa.Column('clinic_name', sa.String(255), nullable=False),
        sa.Column('clinic_name_token', sa.String(64)),
        sa.Column('phone_number', sa.String(20)),
        sa.Column('email_token', sa.String(64)),
        sa.Column('address_token', sa.String(64)),
        sa.Column('timezone', sa.String(50), default='UTC'),
        sa.Column('default_language', sa.String(10), default='en'),
        sa.Column('supported_languages', sa.JSON),
        sa.Column('ehr_system', sa.String(100)),
        sa.Column('ehr_api_endpoint', sa.String(500)),
        sa.Column('ehr_credentials_vault_key', sa.String(100)),
        sa.Column('ehr_enabled', sa.Boolean, default=False),
        sa.Column('fallback_system', sa.String(100)),
        sa.Column('fallback_credentials_vault_key', sa.String(100)),
        sa.Column('max_concurrent_calls', sa.Integer, default=10),
        sa.Column('queue_timeout_seconds', sa.Integer, default=300),
        sa.Column('overload_action', sa.String(50), default='queue'),
        sa.Column('staff_forward_number', sa.String(20)),
        sa.Column('reminders_enabled', sa.Boolean, default=True),
        sa.Column('reminder_hours_before', sa.Integer, default=24),
        sa.Column('reminder_retry_minutes', sa.Integer, default=60),
        sa.Column('subscription_tier', sa.String(50), default='basic'),
        sa.Column('subscription_status', sa.String(50), default='active'),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_call_at', sa.DateTime(timezone=True)),
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.String(255)),
        sa.Column('deletion_reason', sa.Text)
    )
    
    # Create caller_types table
    op.create_table('caller_types',
        sa.Column('caller_type_id', sa.Integer, primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create routing_rules table
    op.create_table('routing_rules',
        sa.Column('routing_rule_id', sa.Integer, primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('conditions', sa.JSON),
        sa.Column('actions', sa.JSON),
        sa.Column('priority', sa.Integer, default=0),
        sa.Column('is_enabled', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create call_queues table
    op.create_table('call_queues',
        sa.Column('queue_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('current_size', sa.Integer, default=0),
        sa.Column('max_size', sa.Integer),
        sa.Column('average_wait_time', sa.Integer, default=0),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create providers table
    op.create_table('providers',
        sa.Column('provider_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255)),
        sa.Column('phone', sa.String(20)),
        sa.Column('specialty', sa.String(100)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.String(255)),
        sa.Column('deletion_reason', sa.Text)
    )
    
    # Create patients table
    op.create_table('patients',
        sa.Column('patient_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('phone', sa.String(20)),
        sa.Column('email', sa.String(255)),
        sa.Column('date_of_birth', sa.Date),
        sa.Column('address', sa.Text),
        sa.Column('emergency_contact', sa.String(255)),
        sa.Column('medical_notes', sa.Text),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.String(255)),
        sa.Column('deletion_reason', sa.Text)
    )
    
    # Create appointment_blocks table
    op.create_table('appointment_blocks',
        sa.Column('block_id', sa.Integer, primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='CASCADE'), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_available', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create appointments table
    op.create_table('appointments',
        sa.Column('appointment_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('patient_id', sa.String(64), sa.ForeignKey('patients.patient_id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='CASCADE'), nullable=False),
        sa.Column('appointment_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer, default=30),
        sa.Column('status', sa.String(50), default='scheduled'),
        sa.Column('notes', sa.Text),
        sa.Column('google_event_id', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.String(255)),
        sa.Column('deletion_reason', sa.Text)
    )
    
    # Create calls table
    op.create_table('calls',
        sa.Column('call_sid', sa.String(64), primary_key=True),
        sa.Column('call_id', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('caller_phone_token', sa.String(64)),
        sa.Column('status', sa.String(20), default='initiated', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('detected_caller_type', sa.String(100)),
        sa.Column('caller_type_confidence', sa.Float),
        sa.Column('routing_rule_id', sa.Integer, sa.ForeignKey('routing_rules.routing_rule_id', ondelete='SET NULL')),
        sa.Column('assigned_provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='SET NULL')),
        sa.Column('queue_id', sa.String(64), sa.ForeignKey('call_queues.queue_id', ondelete='SET NULL')),
        sa.Column('routing_metadata', sa.JSON),
        sa.Column('patient_id', sa.String(64), sa.ForeignKey('patients.patient_id', ondelete='SET NULL')),
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.String(255)),
        sa.Column('deletion_reason', sa.Text)
    )
    
    # Create call_notes table
    op.create_table('call_notes',
        sa.Column('note_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('call_id', sa.String(64), sa.ForeignKey('calls.call_id', ondelete='CASCADE'), nullable=False),
        sa.Column('note_text', sa.Text, nullable=False),
        sa.Column('note_type', sa.String(50), default='general'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', sa.String(255)),
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('deleted_by', sa.String(255)),
        sa.Column('deletion_reason', sa.Text)
    )
    
    # Create mappings table
    op.create_table('mappings',
        sa.Column('mapping_id', sa.Integer, primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_type', sa.String(100), nullable=False),
        sa.Column('source_value', sa.String(255), nullable=False),
        sa.Column('target_type', sa.String(100), nullable=False),
        sa.Column('target_value', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create appointment_slots table
    op.create_table('appointment_slots',
        sa.Column('slot_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='CASCADE'), nullable=False),
        sa.Column('slot_datetime', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer, nullable=False),
        sa.Column('is_booked', sa.String(20), default='available'),
        sa.Column('booked_by_appointment_id', sa.String(64)),
        sa.Column('held_until', sa.DateTime(timezone=True)),
        sa.Column('held_by_call_sid', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create provider_clinics association table
    op.create_table('provider_clinics',
        sa.Column('provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('is_active', sa.String(10), default='yes', nullable=False)
    )
    
    # Create google_calendar_credentials table
    op.create_table('google_calendar_credentials',
        sa.Column('credential_id', sa.String(64), primary_key=True),
        sa.Column('provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('access_token_nonce', sa.LargeBinary(12), nullable=False),
        sa.Column('access_token_ciphertext', sa.LargeBinary, nullable=False),
        sa.Column('refresh_token_nonce', sa.LargeBinary(12), nullable=True),
        sa.Column('refresh_token_ciphertext', sa.LargeBinary, nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scope', sa.Text, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )
    
    # Create caller_detection_logs table
    op.create_table('caller_detection_logs',
        sa.Column('detection_id', sa.String(64), primary_key=True),
        sa.Column('call_id', sa.String(64), sa.ForeignKey('calls.call_id', ondelete='CASCADE'), nullable=False),
        sa.Column('caller_phone_token', sa.String(64), nullable=True),
        sa.Column('detected_caller_type', sa.String(50), nullable=True),
        sa.Column('detection_method', sa.String(50), nullable=False),
        sa.Column('confidence_score', sa.Float, nullable=True),
        sa.Column('detection_data', sa.Text, nullable=True),
        sa.Column('detection_result', sa.Text, nullable=True),
        sa.Column('processing_time_ms', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('is_deleted', sa.String(10), default='no', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True)
    )
    
    # Create provider_capacities table
    op.create_table('provider_capacities',
        sa.Column('capacity_id', sa.String(64), primary_key=True),
        sa.Column('provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='CASCADE'), nullable=False),
        sa.Column('max_concurrent_calls', sa.Integer, nullable=False),
        sa.Column('current_calls', sa.Integer, nullable=False, default=0),
        sa.Column('available_capacity', sa.Integer, nullable=False),
        sa.Column('skills', sa.Text, nullable=True),
        sa.Column('languages', sa.Text, nullable=True),
        sa.Column('specializations', sa.Text, nullable=True),
        sa.Column('is_available', sa.Boolean, nullable=False, default=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('is_deleted', sa.String(10), default='no', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True)
    )
    
    # Create queued_calls table
    op.create_table('queued_calls',
        sa.Column('queued_call_id', sa.String(64), primary_key=True),
        sa.Column('call_id', sa.String(64), sa.ForeignKey('calls.call_id', ondelete='CASCADE'), nullable=False),
        sa.Column('queue_id', sa.String(64), sa.ForeignKey('call_queues.queue_id', ondelete='CASCADE'), nullable=False),
        sa.Column('priority_score', sa.Float, nullable=False, default=0.0),
        sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('estimated_wait_time', sa.Float, nullable=True),
        sa.Column('assigned_provider_id', sa.String(64), sa.ForeignKey('providers.provider_id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='queued'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('is_deleted', sa.String(10), default='no', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True)
    )
    
    # Create system_config table
    op.create_table('system_config',
        sa.Column('config_id', sa.String(64), primary_key=True),
        sa.Column('config_key', sa.String(100), nullable=False, unique=True),
        sa.Column('config_value', sa.String(1000), nullable=False),
        sa.Column('config_type', sa.String(20), default='string', nullable=False),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('is_sensitive', sa.String(10), default='no', nullable=False),
        sa.Column('requires_restart', sa.String(10), default='no', nullable=False),
        sa.Column('updated_by', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )
    
    # Create call_queue table (different from call_queues)
    op.create_table('call_queue',
        sa.Column('queue_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('current_size', sa.Integer, default=0),
        sa.Column('max_size', sa.Integer),
        sa.Column('average_wait_time', sa.Integer, default=0),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )
    
    # Create clinic_usage table
    op.create_table('clinic_usage',
        sa.Column('usage_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('billing_period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('billing_period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('calls_completed', sa.Integer, default=0),
        sa.Column('minutes_used', sa.Integer, default=0),
        sa.Column('tokens_used', sa.Integer, default=0),
        sa.Column('cost_usd', sa.Float, default=0.0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )
    
    # Create clinic_licenses table
    op.create_table('clinic_licenses',
        sa.Column('license_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('license_status', sa.String(20), default='active', nullable=False),
        sa.Column('license_token', sa.String(255), nullable=True),
        sa.Column('tier', sa.String(50), nullable=False),
        sa.Column('max_calls_per_month', sa.Integer, nullable=True),
        sa.Column('max_concurrent_calls', sa.Integer, nullable=True),
        sa.Column('max_call_duration_minutes', sa.Integer, nullable=True),
        sa.Column('max_providers', sa.Integer, nullable=True),
        sa.Column('feature_reminders', sa.Boolean, default=True),
        sa.Column('feature_analytics', sa.Boolean, default=True),
        sa.Column('feature_api_access', sa.Boolean, default=True),
        sa.Column('feature_priority_support', sa.Boolean, default=False),
        sa.Column('current_month_calls', sa.Integer, default=0),
        sa.Column('current_month_minutes', sa.Integer, default=0),
        sa.Column('current_concurrent_calls', sa.Integer, default=0),
        sa.Column('usage_percentage', sa.Float, default=0.0),
        sa.Column('auto_upgrade_threshold', sa.Float, default=80.0),
        sa.Column('auto_upgrade_offered', sa.Boolean, default=False),
        sa.Column('auto_upgrade_offered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_period_days', sa.Integer, default=7),
        sa.Column('grace_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('billing_cycle_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('billing_cycle_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('monthly_fee_usd', sa.Numeric(10, 2), nullable=True),
        sa.Column('overage_rate_per_call_usd', sa.Numeric(10, 4), nullable=True),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('suspension_reason', sa.String(255), nullable=True),
        sa.Column('data_retention_days', sa.Integer, default=2555),  # 7 years
        sa.Column('reactivation_count', sa.Integer, default=0),
        sa.Column('last_reactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )
    
    # Create reminders table
    op.create_table('reminders',
        sa.Column('reminder_id', sa.String(64), primary_key=True),
        sa.Column('appointment_id', sa.String(64), sa.ForeignKey('appointments.appointment_id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reminder_type', sa.String(20), nullable=False, default='appointment_reminder'),
        sa.Column('status', sa.String(20), nullable=False, default='scheduled'),
        sa.Column('reminder_call_id', sa.String(64), nullable=True),
        sa.Column('retry_count', sa.Integer, nullable=False, default=0),
        sa.Column('max_retries', sa.Integer, nullable=False, default=3),
        sa.Column('next_retry_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('call_duration_seconds', sa.Integer, nullable=True),
        sa.Column('call_outcome', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_deleted', sa.String(10), default='no', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True)
    )
    
    # Create reminder_logs table
    op.create_table('reminder_logs',
        sa.Column('log_id', sa.String(64), primary_key=True),
        sa.Column('reminder_id', sa.String(64), sa.ForeignKey('reminders.reminder_id', ondelete='CASCADE'), nullable=False),
        sa.Column('attempt_number', sa.Integer, nullable=False),
        sa.Column('call_attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('call_outcome', sa.String(50), nullable=True),
        sa.Column('call_duration_seconds', sa.Integer, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )
    
    # Create audit_logs table
    op.create_table('audit_logs',
        sa.Column('log_id', sa.String(64), primary_key=True),
        sa.Column('clinic_id', sa.String(64), sa.ForeignKey('clinics.clinic_id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', sa.String(255)),
        sa.Column('old_values', sa.JSON),
        sa.Column('new_values', sa.JSON),
        sa.Column('user_id', sa.String(255)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create indexes
    op.create_index('idx_calls_clinic_id', 'calls', ['clinic_id'])
    op.create_index('idx_calls_status', 'calls', ['status'])
    op.create_index('idx_calls_started_at', 'calls', ['started_at'])
    op.create_index('idx_patients_clinic_id', 'patients', ['clinic_id'])
    op.create_index('idx_patients_phone', 'patients', ['phone'])
    op.create_index('idx_appointments_clinic_id', 'appointments', ['clinic_id'])
    op.create_index('idx_appointments_date', 'appointments', ['appointment_date'])
    op.create_index('idx_providers_clinic_id', 'providers', ['clinic_id'])
    op.create_index('idx_call_notes_clinic_id', 'call_notes', ['clinic_id'])
    op.create_index('idx_mappings_clinic_id', 'mappings', ['clinic_id'])
    op.create_index('idx_audit_logs_clinic_id', 'audit_logs', ['clinic_id'])
    op.create_index('idx_audit_logs_created_at', 'audit_logs', ['created_at'])
    
    # Insert default clinic
    op.execute("""
        INSERT INTO clinics (clinic_id, clinic_name, phone_number, timezone, is_active)
        VALUES ('default-clinic', 'Default Clinic', '+1234567890', 'UTC', true)
    """)
    
    # Insert emergency configuration
    op.execute("""
        INSERT INTO system_config (config_id, config_key, config_value, config_type, category, description, is_sensitive, requires_restart)
        VALUES 
        ('emergency_transfer_number', 'emergency_transfer_number', '+1234567890', 'string', 'emergency', 'Primary emergency transfer number', 'no', 'no'),
        ('emergency_fallback_number', 'emergency_fallback_number', '911', 'string', 'emergency', 'Fallback emergency number', 'no', 'no'),
        ('insurance_department_number', 'insurance_department_number', '+1234567891', 'string', 'transfers', 'Insurance department transfer number', 'no', 'no'),
        ('billing_department_number', 'billing_department_number', '+1234567892', 'string', 'transfers', 'Billing department transfer number', 'no', 'no')
    """)


def downgrade():
    """Drop all tables"""
    op.drop_table('audit_logs')
    op.drop_table('mappings')
    op.drop_table('call_notes')
    op.drop_table('calls')
    op.drop_table('appointments')
    op.drop_table('appointment_blocks')
    op.drop_table('patients')
    op.drop_table('providers')
    op.drop_table('call_queues')
    op.drop_table('routing_rules')
    op.drop_table('caller_types')
    op.drop_table('clinics')
