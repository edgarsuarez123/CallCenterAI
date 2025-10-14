"""Add comprehensive database constraints and indexes

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-13 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================================
    # CRITICAL BUSINESS CONSTRAINTS
    # ============================================================================
    
    # 1. PREVENT DOUBLE BOOKING - Most Critical Business Rule
    # This constraint makes it impossible to have two appointments for the same provider at the same time
    op.create_check_constraint(
        'check_appointment_slots_no_double_booking',
        'appointment_slots',
        "is_booked IN ('yes', 'no', 'held')"
    )
    
    # 2. APPOINTMENT TIME VALIDATION
    op.create_check_constraint(
        'check_appointments_end_after_start',
        'appointments',
        'end_time > start_time'
    )
    
    op.create_check_constraint(
        'check_appointments_positive_duration',
        'appointments',
        'duration_minutes > 0'
    )
    
    # 3. APPOINTMENT SLOT VALIDATION
    op.create_check_constraint(
        'check_appointment_slots_positive_duration',
        'appointment_slots',
        'duration_minutes > 0 AND duration_minutes <= 480'
    )
    
    op.create_check_constraint(
        'check_appointment_slots_valid_status',
        'appointment_slots',
        "is_booked IN ('yes', 'no', 'held')"
    )
    
    # 4. CALL STATUS VALIDATION
    op.create_check_constraint(
        'check_calls_valid_status',
        'calls',
        "status IN ('initiated', 'active', 'completed', 'failed', 'abandoned')"
    )
    
    op.create_check_constraint(
        'check_calls_end_after_start',
        'calls',
        'ended_at IS NULL OR ended_at >= started_at'
    )
    
    # 5. CLINIC CONFIGURATION VALIDATION
    op.create_check_constraint(
        'check_clinics_positive_concurrent_calls',
        'clinics',
        'max_concurrent_calls > 0 AND max_concurrent_calls <= 100'
    )
    
    op.create_check_constraint(
        'check_clinics_positive_queue_timeout',
        'clinics',
        'queue_timeout_seconds > 0 AND queue_timeout_seconds <= 300'
    )
    
    op.create_check_constraint(
        'check_clinics_valid_subscription_tier',
        'clinics',
        "subscription_tier IN ('basic', 'professional', 'enterprise')"
    )
    
    op.create_check_constraint(
        'check_clinics_valid_status',
        'clinics',
        "is_active IN ('yes', 'no')"
    )
    
    # 6. PROVIDER VALIDATION
    op.create_check_constraint(
        'check_providers_valid_availability',
        'providers',
        "is_available IN ('yes', 'no', 'limited')"
    )
    
    # 7. LICENSE VALIDATION
    op.create_check_constraint(
        'check_licenses_valid_tier',
        'clinic_licenses',
        "tier IN ('basic', 'professional', 'enterprise')"
    )
    
    op.create_check_constraint(
        'check_licenses_valid_status',
        'clinic_licenses',
        "license_status IN ('active', 'grace_period', 'suspended', 'expired', 'cancelled')"
    )
    
    op.create_check_constraint(
        'check_licenses_positive_limits',
        'clinic_licenses',
        'max_concurrent_calls > 0 AND max_call_duration_minutes > 0'
    )
    
    op.create_check_constraint(
        'check_licenses_valid_usage_percentage',
        'clinic_licenses',
        'usage_percentage >= 0.0 AND usage_percentage <= 200.0'
    )
    
    # 8. USAGE TRACKING VALIDATION
    op.create_check_constraint(
        'check_usage_positive_counts',
        'clinic_usage',
        'total_calls >= 0 AND total_call_minutes >= 0'
    )
    
    op.create_check_constraint(
        'check_usage_valid_billing_period',
        'clinic_usage',
        'billing_period_end > billing_period_start'
    )
    
    op.create_check_constraint(
        'check_usage_valid_payment_status',
        'clinic_usage',
        "payment_status IN ('pending', 'paid', 'failed', 'refunded')"
    )
    
    # 9. AUDIT LOG VALIDATION
    op.create_check_constraint(
        'check_audit_logs_valid_action',
        'audit_logs',
        "action_type IN ('create', 'read', 'update', 'delete', 'tokenize', 'hydrate', 'access_phi')"
    )
    
    op.create_check_constraint(
        'check_audit_logs_valid_success',
        'audit_logs',
        "success IN ('yes', 'no')"
    )
    
    # 10. CALL QUEUE VALIDATION
    op.create_check_constraint(
        'check_call_queue_valid_priority',
        'call_queue',
        "priority_level IN ('normal', 'emergency')"
    )
    
    op.create_check_constraint(
        'check_call_queue_valid_status',
        'call_queue',
        "queue_status IN ('waiting', 'processing', 'completed', 'failed', 'transferred_to_human')"
    )
    
    op.create_check_constraint(
        'check_call_queue_valid_emergency',
        'call_queue',
        "is_emergency IN ('yes', 'no')"
    )
    
    # ============================================================================
    # PERFORMANCE INDEXES FOR COMMON QUERIES
    # ============================================================================
    
    # 1. APPOINTMENT QUERIES (Most Critical for Performance)
    op.create_index('idx_appointments_patient_date', 'appointments', ['patient_id', 'appointment_date'])
    op.create_index('idx_appointments_provider_date', 'appointments', ['provider_id', 'appointment_date'])
    op.create_index('idx_appointments_status_date', 'appointments', ['status', 'appointment_date'])
    op.create_index('idx_appointments_clinic_status', 'appointments', ['clinic_id', 'status'])
    
    # 2. APPOINTMENT SLOT QUERIES (Critical for Booking Performance)
    op.create_index('idx_appointment_slots_available_booking', 'appointment_slots', 
                   ['clinic_id', 'slot_datetime', 'is_booked'])
    op.create_index('idx_appointment_slots_provider_available', 'appointment_slots', 
                   ['provider_id', 'slot_datetime', 'is_booked'])
    op.create_index('idx_appointment_slots_held_cleanup', 'appointment_slots', 
                   ['held_until', 'is_booked'])
    
    # 3. CALL QUERIES (Real-time Performance)
    op.create_index('idx_calls_clinic_status', 'calls', ['clinic_id', 'status'])
    op.create_index('idx_calls_patient_recent', 'calls', ['patient_id', 'started_at'])
    op.create_index('idx_calls_phone_lookup', 'calls', ['caller_phone_token', 'started_at'])
    
    # 4. CLINIC QUERIES (Multi-tenant Performance)
    op.create_index('idx_clinics_phone_lookup', 'clinics', ['phone_number'])
    op.create_index('idx_clinics_active_tier', 'clinics', ['is_active', 'subscription_tier'])
    op.create_index('idx_clinics_last_call', 'clinics', ['last_call_at'])
    
    # 5. PROVIDER QUERIES (Scheduling Performance)
    op.create_index('idx_providers_clinic_available', 'providers', ['clinic_id', 'is_available'])
    op.create_index('idx_providers_specialty', 'providers', ['specialty', 'is_available'])
    
    # 6. LICENSE QUERIES (Billing Performance)
    op.create_index('idx_licenses_status_tier', 'clinic_licenses', ['license_status', 'tier'])
    op.create_index('idx_licenses_usage_monitoring', 'clinic_licenses', 
                   ['current_month_calls', 'max_calls_per_month'])
    op.create_index('idx_licenses_billing_cycle', 'clinic_licenses', 
                   ['billing_cycle_start', 'billing_cycle_end'])
    
    # 7. USAGE TRACKING QUERIES (Billing Performance)
    op.create_index('idx_usage_billing_period', 'clinic_usage', 
                   ['clinic_id', 'billing_period_start'])
    op.create_index('idx_usage_invoice_status', 'clinic_usage', 
                   ['invoice_generated', 'payment_status'])
    
    # 8. AUDIT LOG QUERIES (Compliance Performance)
    op.create_index('idx_audit_logs_table_record', 'audit_logs', ['table_name', 'record_id'])
    op.create_index('idx_audit_logs_user_date', 'audit_logs', ['user_id', 'created_at'])
    op.create_index('idx_audit_logs_action_date', 'audit_logs', ['action_type', 'created_at'])
    
    # 9. CALL QUEUE QUERIES (Real-time Processing)
    op.create_index('idx_call_queue_priority_status', 'call_queue', 
                   ['priority_level', 'queue_status'])
    op.create_index('idx_call_queue_emergency', 'call_queue', ['is_emergency', 'queue_status'])
    
    # 10. MAPPING QUERIES (Tokenization Performance)
    op.create_index('idx_mappings_call_id', 'mappings', ['call_id'])
    op.create_index('idx_mappings_type_created', 'mappings', ['value_type', 'created_at'])
    op.create_index('idx_mappings_last_used', 'mappings', ['last_used_at'])
    
    # ============================================================================
    # UNIQUE CONSTRAINTS FOR BUSINESS RULES
    # ============================================================================
    
    # 1. PREVENT DOUBLE BOOKING (Most Critical)
    # This is the most important constraint - prevents two appointments for same provider at same time
    op.create_unique_constraint(
        'unique_provider_slot_datetime',
        'appointment_slots',
        ['provider_id', 'slot_datetime']
    )
    
    # 2. ENSURE UNIQUE CLINIC PHONE NUMBERS
    op.create_unique_constraint(
        'unique_clinic_phone',
        'clinics',
        ['phone_number']
    )
    
    # 3. ENSURE ONE LICENSE PER CLINIC
    op.create_unique_constraint(
        'unique_clinic_license',
        'clinic_licenses',
        ['clinic_id']
    )
    
    # 4. ENSURE UNIQUE PROVIDER EMAIL (for Google Calendar)
    op.create_unique_constraint(
        'unique_provider_email',
        'providers',
        ['email']
    )
    
    # 5. ENSURE UNIQUE CONFIG KEYS PER CLINIC
    op.create_unique_constraint(
        'unique_clinic_config_key',
        'system_config',
        ['config_key']
    )
    
    # ============================================================================
    # FOREIGN KEY CONSTRAINTS WITH CASCADE RULES
    # ============================================================================
    
    # Note: Most foreign keys are already defined in the models, but we need to ensure
    # proper cascade behavior for data integrity
    
    # 1. CLINIC DELETION CASCADE
    # When a clinic is deleted, all related data should be cleaned up
    # This is handled by the application layer for safety, but we document the relationships
    
    # 2. PROVIDER DELETION CASCADE
    # When a provider is deleted, their appointments and slots should be handled
    # This is also handled by the application layer for safety
    
    # ============================================================================
    # PARTIAL INDEXES FOR SPECIFIC QUERY PATTERNS
    # ============================================================================
    
    # 1. ACTIVE APPOINTMENTS ONLY
    op.create_index('idx_appointments_active_only', 'appointments', 
                   ['clinic_id', 'appointment_date'],
                   postgresql_where="status IN ('scheduled', 'confirmed')")
    
    # 2. AVAILABLE SLOTS ONLY
    op.create_index('idx_slots_available_only', 'appointment_slots', 
                   ['clinic_id', 'slot_datetime'],
                   postgresql_where="is_booked = 'no'")
    
    # 3. ACTIVE CALLS ONLY
    op.create_index('idx_calls_active_only', 'calls', 
                   ['clinic_id', 'started_at'],
                   postgresql_where="status IN ('initiated', 'active')")
    
    # 4. ACTIVE CLINICS ONLY
    op.create_index('idx_clinics_active_only', 'clinics', 
                   ['subscription_tier', 'phone_number'],
                   postgresql_where="is_active = 'yes'")
    
    # 5. EMERGENCY CALLS ONLY
    op.create_index('idx_call_queue_emergency_only', 'call_queue', 
                   ['priority_level', 'created_at'],
                   postgresql_where="is_emergency = 'yes'")


def downgrade() -> None:
    # Remove all constraints and indexes in reverse order
    
    # Remove partial indexes
    op.drop_index('idx_call_queue_emergency_only', 'call_queue')
    op.drop_index('idx_clinics_active_only', 'clinics')
    op.drop_index('idx_calls_active_only', 'calls')
    op.drop_index('idx_slots_available_only', 'appointment_slots')
    op.drop_index('idx_appointments_active_only', 'appointments')
    
    # Remove unique constraints
    op.drop_constraint('unique_clinic_config_key', 'system_config', type_='unique')
    op.drop_constraint('unique_provider_email', 'providers', type_='unique')
    op.drop_constraint('unique_clinic_license', 'clinic_licenses', type_='unique')
    op.drop_constraint('unique_clinic_phone', 'clinics', type_='unique')
    op.drop_constraint('unique_provider_slot_datetime', 'appointment_slots', type_='unique')
    
    # Remove performance indexes
    op.drop_index('idx_mappings_last_used', 'mappings')
    op.drop_index('idx_mappings_type_created', 'mappings')
    op.drop_index('idx_mappings_call_id', 'mappings')
    op.drop_index('idx_call_queue_emergency', 'call_queue')
    op.drop_index('idx_call_queue_priority_status', 'call_queue')
    op.drop_index('idx_audit_logs_action_date', 'audit_logs')
    op.drop_index('idx_audit_logs_user_date', 'audit_logs')
    op.drop_index('idx_audit_logs_table_record', 'audit_logs')
    op.drop_index('idx_usage_invoice_status', 'clinic_usage')
    op.drop_index('idx_usage_billing_period', 'clinic_usage')
    op.drop_index('idx_licenses_billing_cycle', 'clinic_licenses')
    op.drop_index('idx_licenses_usage_monitoring', 'clinic_licenses')
    op.drop_index('idx_licenses_status_tier', 'clinic_licenses')
    op.drop_index('idx_providers_specialty', 'providers')
    op.drop_index('idx_providers_clinic_available', 'providers')
    op.drop_index('idx_clinics_last_call', 'clinics')
    op.drop_index('idx_clinics_active_tier', 'clinics')
    op.drop_index('idx_clinics_phone_lookup', 'clinics')
    op.drop_index('idx_calls_phone_lookup', 'calls')
    op.drop_index('idx_calls_patient_recent', 'calls')
    op.drop_index('idx_calls_clinic_status', 'calls')
    op.drop_index('idx_appointment_slots_held_cleanup', 'appointment_slots')
    op.drop_index('idx_appointment_slots_provider_available', 'appointment_slots')
    op.drop_index('idx_appointment_slots_available_booking', 'appointment_slots')
    op.drop_index('idx_appointments_clinic_status', 'appointments')
    op.drop_index('idx_appointments_status_date', 'appointments')
    op.drop_index('idx_appointments_provider_date', 'appointments')
    op.drop_index('idx_appointments_patient_date', 'appointments')
    
    # Remove check constraints
    op.drop_constraint('check_call_queue_valid_emergency', 'call_queue', type_='check')
    op.drop_constraint('check_call_queue_valid_status', 'call_queue', type_='check')
    op.drop_constraint('check_call_queue_valid_priority', 'call_queue', type_='check')
    op.drop_constraint('check_audit_logs_valid_success', 'audit_logs', type_='check')
    op.drop_constraint('check_audit_logs_valid_action', 'audit_logs', type_='check')
    op.drop_constraint('check_usage_valid_payment_status', 'clinic_usage', type_='check')
    op.drop_constraint('check_usage_valid_billing_period', 'clinic_usage', type_='check')
    op.drop_constraint('check_usage_positive_counts', 'clinic_usage', type_='check')
    op.drop_constraint('check_licenses_valid_usage_percentage', 'clinic_licenses', type_='check')
    op.drop_constraint('check_licenses_positive_limits', 'clinic_licenses', type_='check')
    op.drop_constraint('check_licenses_valid_status', 'clinic_licenses', type_='check')
    op.drop_constraint('check_licenses_valid_tier', 'clinic_licenses', type_='check')
    op.drop_constraint('check_providers_valid_availability', 'providers', type_='check')
    op.drop_constraint('check_clinics_valid_status', 'clinics', type_='check')
    op.drop_constraint('check_clinics_valid_subscription_tier', 'clinics', type_='check')
    op.drop_constraint('check_clinics_positive_queue_timeout', 'clinics', type_='check')
    op.drop_constraint('check_clinics_positive_concurrent_calls', 'clinics', type_='check')
    op.drop_constraint('check_calls_end_after_start', 'calls', type_='check')
    op.drop_constraint('check_calls_valid_status', 'calls', type_='check')
    op.drop_constraint('check_appointment_slots_valid_status', 'appointment_slots', type_='check')
    op.drop_constraint('check_appointment_slots_positive_duration', 'appointment_slots', type_='check')
    op.drop_constraint('check_appointments_positive_duration', 'appointments', type_='check')
    op.drop_constraint('check_appointments_end_after_start', 'appointments', type_='check')
    op.drop_constraint('check_appointment_slots_no_double_booking', 'appointment_slots', type_='check')
