"""Initial database schema

Revision ID: 0001
Revises: 
Create Date: 2025-01-13 17:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create mappings table for tokenization
    op.create_table('mappings',
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('value_nonce', sa.LargeBinary(length=12), nullable=False),
        sa.Column('value_ciphertext', sa.LargeBinary(), nullable=False),
        sa.Column('value_type', sa.String(length=32), nullable=False),
        sa.Column('call_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('token')
    )
    
    # Create clinics table
    op.create_table('clinics',
        sa.Column('clinic_id', sa.String(length=64), nullable=False),
        sa.Column('clinic_name', sa.String(length=200), nullable=False),
        sa.Column('clinic_name_token', sa.String(length=64), nullable=True),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('email_token', sa.String(length=64), nullable=True),
        sa.Column('address_token', sa.String(length=64), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=False),
        sa.Column('default_language', sa.String(length=5), nullable=False),
        sa.Column('supported_languages', sa.String(length=20), nullable=False),
        sa.Column('ehr_system', sa.String(length=20), nullable=False),
        sa.Column('ehr_api_endpoint', sa.String(length=500), nullable=True),
        sa.Column('ehr_credentials_vault_key', sa.String(length=100), nullable=True),
        sa.Column('ehr_enabled', sa.String(length=10), nullable=False),
        sa.Column('fallback_system', sa.String(length=20), nullable=False),
        sa.Column('fallback_credentials_vault_key', sa.String(length=100), nullable=True),
        sa.Column('max_concurrent_calls', sa.Integer(), nullable=False),
        sa.Column('queue_timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('overload_action', sa.String(length=20), nullable=False),
        sa.Column('staff_forward_number', sa.String(length=20), nullable=True),
        sa.Column('reminders_enabled', sa.String(length=10), nullable=False),
        sa.Column('reminder_hours_before', sa.Integer(), nullable=False),
        sa.Column('reminder_retry_minutes', sa.Integer(), nullable=False),
        sa.Column('subscription_tier', sa.String(length=20), nullable=False),
        sa.Column('subscription_status', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_call_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('clinic_id'),
        sa.UniqueConstraint('phone_number')
    )
    
    # Create providers table
    op.create_table('providers',
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('name_token', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=50), nullable=True),
        sa.Column('specialty', sa.String(length=100), nullable=True),
        sa.Column('license_number', sa.String(length=50), nullable=True),
        sa.Column('npi_number', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('is_available', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('provider_id')
    )
    
    # Create patients table
    op.create_table('patients',
        sa.Column('patient_id', sa.String(length=64), nullable=False),
        sa.Column('name_token', sa.String(length=64), nullable=True),
        sa.Column('phone_token', sa.String(length=64), nullable=True),
        sa.Column('email_token', sa.String(length=64), nullable=True),
        sa.Column('dob_token', sa.String(length=64), nullable=True),
        sa.Column('insurance_provider_token', sa.String(length=64), nullable=True),
        sa.Column('insurance_member_id_token', sa.String(length=64), nullable=True),
        sa.Column('insurance_plan_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('patient_id')
    )
    
    # Create calls table
    op.create_table('calls',
        sa.Column('call_sid', sa.String(length=64), nullable=False),
        sa.Column('call_id', sa.String(length=64), nullable=False),
        sa.Column('caller_phone_token', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('patient_id', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('call_sid'),
        sa.UniqueConstraint('call_id'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.patient_id'], ),
        sa.Index('idx_calls_call_id', 'call_id'),
        sa.Index('idx_calls_status', 'status'),
        sa.Index('idx_calls_started_at', 'started_at')
    )
    
    # Create appointments table
    op.create_table('appointments',
        sa.Column('appointment_id', sa.String(length=64), nullable=False),
        sa.Column('patient_id', sa.String(length=64), nullable=False),
        sa.Column('provider_id', sa.String(length=64), nullable=True),
        sa.Column('call_id', sa.String(length=64), nullable=True),
        sa.Column('appointment_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason_token', sa.String(length=64), nullable=True),
        sa.Column('notes_token', sa.String(length=64), nullable=True),
        sa.Column('appointment_type', sa.String(length=50), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('appointment_id'),
        sa.ForeignKeyConstraint(['call_id'], ['calls.call_id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.patient_id'], ),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], )
    )
    
    # Create appointment_slots table
    op.create_table('appointment_slots',
        sa.Column('slot_id', sa.String(length=64), nullable=False),
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('slot_datetime', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('is_booked', sa.String(length=10), nullable=False),
        sa.Column('booked_by_appointment_id', sa.String(length=64), nullable=True),
        sa.Column('held_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('held_by_call_sid', sa.String(length=64), nullable=True),
        sa.Column('clinic_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('slot_id'),
        sa.ForeignKeyConstraint(['booked_by_appointment_id'], ['appointments.appointment_id'], ),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.clinic_id'], ),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ),
        sa.UniqueConstraint('provider_id', 'slot_datetime', name='unique_provider_slot'),
        sa.Index('idx_appointment_slots_clinic_datetime', 'clinic_id', 'slot_datetime'),
        sa.Index('idx_appointment_slots_provider_datetime', 'provider_id', 'slot_datetime'),
        sa.Index('idx_appointment_slots_available', 'clinic_id', 'slot_datetime', 'is_booked')
    )
    
    # Create appointment_blocks table
    op.create_table('appointment_blocks',
        sa.Column('block_id', sa.String(length=64), nullable=False),
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('block_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('slot_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('break_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('max_appointments', sa.Integer(), nullable=True),
        sa.Column('is_available', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('block_id'),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], )
    )
    
    # Create call_notes table
    op.create_table('call_notes',
        sa.Column('notes_id', sa.String(length=64), nullable=False),
        sa.Column('call_id', sa.String(length=64), nullable=False),
        sa.Column('patient_id', sa.String(length=64), nullable=True),
        sa.Column('summary_token', sa.String(length=64), nullable=True),
        sa.Column('key_points_token', sa.String(length=64), nullable=True),
        sa.Column('action_items_token', sa.String(length=64), nullable=True),
        sa.Column('sentiment_score', sa.String(length=20), nullable=True),
        sa.Column('urgency_level', sa.String(length=20), nullable=True),
        sa.Column('call_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('ai_confidence_score', sa.String(length=20), nullable=True),
        sa.Column('symptoms_detected', sa.String(length=500), nullable=True),
        sa.Column('medications_mentioned', sa.String(length=500), nullable=True),
        sa.Column('concerns_raised', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('notes_id'),
        sa.ForeignKeyConstraint(['call_id'], ['calls.call_id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.patient_id'], )
    )
    
    # Create audit_logs table
    op.create_table('audit_logs',
        sa.Column('log_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('table_name', sa.String(length=50), nullable=True),
        sa.Column('record_id', sa.String(length=64), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('details', sa.String(length=1000), nullable=True),
        sa.Column('success', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('log_id'),
        sa.Index('idx_audit_logs_table_record', 'table_name', 'record_id'),
        sa.Index('idx_audit_logs_user_action', 'user_id', 'action_type'),
        sa.Index('idx_audit_logs_created_at', 'created_at')
    )
    
    # Create call_queue table
    op.create_table('call_queue',
        sa.Column('queue_id', sa.String(length=64), nullable=False),
        sa.Column('call_id', sa.String(length=64), nullable=False),
        sa.Column('priority_level', sa.String(length=20), nullable=False),
        sa.Column('queue_status', sa.String(length=20), nullable=False),
        sa.Column('is_emergency', sa.String(length=10), nullable=False),
        sa.Column('emergency_reason', sa.String(length=200), nullable=True),
        sa.Column('transferred_to_human', sa.String(length=10), nullable=False),
        sa.Column('assigned_human_agent', sa.String(length=64), nullable=True),
        sa.Column('ai_processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ai_processing_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('human_transfer_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('queue_id'),
        sa.ForeignKeyConstraint(['call_id'], ['calls.call_id'], )
    )
    
    # Create system_config table
    op.create_table('system_config',
        sa.Column('config_id', sa.String(length=64), nullable=False),
        sa.Column('config_key', sa.String(length=100), nullable=False),
        sa.Column('config_value', sa.String(length=1000), nullable=False),
        sa.Column('config_type', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('is_sensitive', sa.String(length=10), nullable=False),
        sa.Column('requires_restart', sa.String(length=10), nullable=False),
        sa.Column('updated_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('config_id'),
        sa.UniqueConstraint('config_key')
    )
    
    # Create clinic_licenses table
    op.create_table('clinic_licenses',
        sa.Column('license_id', sa.String(length=64), nullable=False),
        sa.Column('clinic_id', sa.String(length=64), nullable=False),
        sa.Column('license_status', sa.String(length=20), nullable=False),
        sa.Column('license_token', sa.String(length=256), nullable=True),
        sa.Column('tier', sa.String(length=20), nullable=False),
        sa.Column('max_calls_per_month', sa.Integer(), nullable=True),
        sa.Column('max_concurrent_calls', sa.Integer(), nullable=False),
        sa.Column('max_call_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('max_providers', sa.Integer(), nullable=True),
        sa.Column('feature_reminders', sa.String(length=10), nullable=False),
        sa.Column('feature_analytics', sa.String(length=10), nullable=False),
        sa.Column('feature_api_access', sa.String(length=10), nullable=False),
        sa.Column('feature_priority_support', sa.String(length=10), nullable=False),
        sa.Column('current_month_calls', sa.Integer(), nullable=False),
        sa.Column('current_month_minutes', sa.Integer(), nullable=False),
        sa.Column('current_concurrent_calls', sa.Integer(), nullable=False),
        sa.Column('usage_percentage', sa.Float(), nullable=False),
        sa.Column('auto_upgrade_threshold', sa.Float(), nullable=False),
        sa.Column('auto_upgrade_offered', sa.String(length=10), nullable=False),
        sa.Column('auto_upgrade_offered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_period_days', sa.Integer(), nullable=False),
        sa.Column('grace_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('billing_cycle_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('billing_cycle_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('monthly_fee_usd', sa.Float(), nullable=False),
        sa.Column('overage_rate_per_call_usd', sa.Float(), nullable=False),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('suspension_reason', sa.String(length=100), nullable=True),
        sa.Column('data_retention_days', sa.Integer(), nullable=False),
        sa.Column('reactivation_count', sa.Integer(), nullable=False),
        sa.Column('last_reactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('license_id'),
        sa.UniqueConstraint('clinic_id'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.clinic_id'], ),
        sa.Index('idx_license_current_usage', 'clinic_id', 'current_month_calls'),
        sa.Index('idx_license_status', 'license_status', 'tier'),
        sa.Index('idx_license_billing_cycle', 'clinic_id', 'billing_cycle_start')
    )
    
    # Create clinic_usage table
    op.create_table('clinic_usage',
        sa.Column('usage_id', sa.String(length=64), nullable=False),
        sa.Column('clinic_id', sa.String(length=64), nullable=False),
        sa.Column('billing_period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('billing_period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_calls', sa.Integer(), nullable=False),
        sa.Column('total_call_minutes', sa.Integer(), nullable=False),
        sa.Column('completed_calls', sa.Integer(), nullable=False),
        sa.Column('failed_calls', sa.Integer(), nullable=False),
        sa.Column('abandoned_calls', sa.Integer(), nullable=False),
        sa.Column('forwarded_calls', sa.Integer(), nullable=False),
        sa.Column('calls_english', sa.Integer(), nullable=False),
        sa.Column('calls_spanish', sa.Integer(), nullable=False),
        sa.Column('total_llm_prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('total_llm_completion_tokens', sa.Integer(), nullable=False),
        sa.Column('total_llm_cost_usd', sa.Float(), nullable=False),
        sa.Column('total_stt_minutes', sa.Integer(), nullable=False),
        sa.Column('total_stt_cost_usd', sa.Float(), nullable=False),
        sa.Column('total_tts_characters', sa.Integer(), nullable=False),
        sa.Column('total_tts_cost_usd', sa.Float(), nullable=False),
        sa.Column('total_twilio_minutes', sa.Integer(), nullable=False),
        sa.Column('total_twilio_cost_usd', sa.Float(), nullable=False),
        sa.Column('reminder_calls_sent', sa.Integer(), nullable=False),
        sa.Column('reminder_calls_answered', sa.Integer(), nullable=False),
        sa.Column('reminder_calls_cost_usd', sa.Float(), nullable=False),
        sa.Column('appointments_scheduled', sa.Integer(), nullable=False),
        sa.Column('appointments_cancelled', sa.Integer(), nullable=False),
        sa.Column('appointments_confirmed', sa.Integer(), nullable=False),
        sa.Column('total_cost_usd', sa.Float(), nullable=False),
        sa.Column('subscription_fee_usd', sa.Float(), nullable=False),
        sa.Column('overage_fee_usd', sa.Float(), nullable=False),
        sa.Column('total_billable_usd', sa.Float(), nullable=False),
        sa.Column('invoice_generated', sa.String(length=10), nullable=False),
        sa.Column('invoice_id', sa.String(length=64), nullable=True),
        sa.Column('payment_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('usage_id'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.clinic_id'], ),
        sa.Index('idx_clinic_usage_period', 'clinic_id', 'billing_period_start'),
        sa.Index('idx_clinic_usage_current', 'clinic_id', 'billing_period_start', 'invoice_generated')
    )
    
    # Create google_calendar_credentials table
    op.create_table('google_calendar_credentials',
        sa.Column('credential_id', sa.String(length=64), nullable=False),
        sa.Column('provider_id', sa.String(length=64), nullable=False),
        sa.Column('access_token_nonce', sa.LargeBinary(length=12), nullable=False),
        sa.Column('access_token_ciphertext', sa.LargeBinary(), nullable=False),
        sa.Column('refresh_token_nonce', sa.LargeBinary(length=12), nullable=True),
        sa.Column('refresh_token_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('credential_id'),
        sa.UniqueConstraint('provider_id'),
        sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], )
    )


def downgrade() -> None:
    # Drop tables in reverse order to handle foreign key constraints
    op.drop_table('google_calendar_credentials')
    op.drop_table('clinic_usage')
    op.drop_table('clinic_licenses')
    op.drop_table('system_config')
    op.drop_table('call_queue')
    op.drop_table('audit_logs')
    op.drop_table('call_notes')
    op.drop_table('appointment_blocks')
    op.drop_table('appointment_slots')
    op.drop_table('appointments')
    op.drop_table('calls')
    op.drop_table('patients')
    op.drop_table('providers')
    op.drop_table('clinics')
    op.drop_table('mappings')
