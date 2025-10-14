"""Add caller type detection and routing rules

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add caller type detection and routing rules tables for intelligent call routing.
    
    New tables:
    - caller_types: Defines different types of callers (patient, physician, pharmacy, etc.)
    - routing_rules: Configurable routing rules for different caller types
    - caller_detection_logs: Logs of caller type detection attempts
    - provider_capacities: Tracks provider capacity and availability
    """
    
    # Create caller_types table
    op.create_table('caller_types',
        sa.Column('caller_type_id', sa.String(64), primary_key=True),
        sa.Column('caller_type_name', sa.String(50), nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('priority_level', sa.Integer, nullable=False, default=3),
        sa.Column('default_routing_strategy', sa.String(50), nullable=False, default='round_robin'),
        sa.Column('default_overload_policy', sa.String(50), nullable=False, default='queue'),
        sa.Column('max_queue_size', sa.Integer, nullable=False, default=50),
        sa.Column('is_active', sa.Boolean, nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        
        # Soft delete fields
        sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True)
    )
    
    # Create routing_rules table
    op.create_table('routing_rules',
        sa.Column('rule_id', sa.String(64), primary_key=True),
        sa.Column('rule_name', sa.String(100), nullable=False),
        sa.Column('caller_type_id', sa.String(64), nullable=False),
        sa.Column('priority_level', sa.Integer, nullable=False),
        sa.Column('routing_strategy', sa.String(50), nullable=False),
        sa.Column('overload_policy', sa.String(50), nullable=False),
        sa.Column('max_queue_size', sa.Integer, nullable=False),
        sa.Column('target_providers', sa.Text, nullable=True),  # JSON array of provider IDs
        sa.Column('conditions', sa.Text, nullable=True),  # JSON conditions for rule matching
        sa.Column('is_enabled', sa.Boolean, nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        
        # Soft delete fields
        sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True),
        
        # Foreign key
        sa.ForeignKeyConstraint(['caller_type_id'], ['caller_types.caller_type_id'], ondelete='CASCADE')
    )
    
    # Create caller_detection_logs table
    op.create_table('caller_detection_logs',
        sa.Column('detection_id', sa.String(64), primary_key=True),
        sa.Column('call_id', sa.String(64), nullable=False),
        sa.Column('caller_phone_token', sa.String(64), nullable=True),
        sa.Column('detected_caller_type', sa.String(50), nullable=True),
        sa.Column('detection_method', sa.String(50), nullable=False),
        sa.Column('confidence_score', sa.Float, nullable=True),
        sa.Column('detection_data', sa.Text, nullable=True),  # JSON data used for detection
        sa.Column('detection_result', sa.Text, nullable=True),  # JSON result data
        sa.Column('processing_time_ms', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        
        # Soft delete fields
        sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True),
        
        # Foreign key
        sa.ForeignKeyConstraint(['call_id'], ['calls.call_id'], ondelete='CASCADE')
    )
    
    # Create provider_capacities table
    op.create_table('provider_capacities',
        sa.Column('capacity_id', sa.String(64), primary_key=True),
        sa.Column('provider_id', sa.String(64), nullable=False),
        sa.Column('max_concurrent_calls', sa.Integer, nullable=False),
        sa.Column('current_calls', sa.Integer, nullable=False, default=0),
        sa.Column('available_capacity', sa.Integer, nullable=False),
        sa.Column('skills', sa.Text, nullable=True),  # JSON array of skills
        sa.Column('languages', sa.Text, nullable=True),  # JSON array of languages
        sa.Column('specializations', sa.Text, nullable=True),  # JSON array of specializations
        sa.Column('is_available', sa.Boolean, nullable=False, default=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        
        # Soft delete fields
        sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True),
        
        # Foreign key
        sa.ForeignKeyConstraint(['provider_id'], ['providers.provider_id'], ondelete='CASCADE')
    )
    
    # Create call_queues table
    op.create_table('call_queues',
        sa.Column('queue_id', sa.String(64), primary_key=True),
        sa.Column('queue_name', sa.String(100), nullable=False),
        sa.Column('caller_type_id', sa.String(64), nullable=False),
        sa.Column('priority_level', sa.Integer, nullable=False),
        sa.Column('max_queue_size', sa.Integer, nullable=False),
        sa.Column('current_size', sa.Integer, nullable=False, default=0),
        sa.Column('average_wait_time', sa.Float, nullable=False, default=0.0),
        sa.Column('queue_config', sa.Text, nullable=True),  # JSON configuration
        sa.Column('is_active', sa.Boolean, nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        
        # Soft delete fields
        sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True),
        
        # Foreign key
        sa.ForeignKeyConstraint(['caller_type_id'], ['caller_types.caller_type_id'], ondelete='CASCADE')
    )
    
    # Create queued_calls table
    op.create_table('queued_calls',
        sa.Column('queued_call_id', sa.String(64), primary_key=True),
        sa.Column('call_id', sa.String(64), nullable=False),
        sa.Column('queue_id', sa.String(64), nullable=False),
        sa.Column('priority_score', sa.Float, nullable=False, default=0.0),
        sa.Column('queued_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('estimated_wait_time', sa.Float, nullable=True),
        sa.Column('assigned_provider_id', sa.String(64), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='queued'),  # queued, assigned, completed, expired
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        
        # Soft delete fields
        sa.Column('is_deleted', sa.String(10), nullable=False, server_default='no'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.String(64), nullable=True),
        sa.Column('deletion_reason', sa.String(200), nullable=True),
        
        # Foreign keys
        sa.ForeignKeyConstraint(['call_id'], ['calls.call_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['queue_id'], ['call_queues.queue_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_provider_id'], ['providers.provider_id'], ondelete='SET NULL')
    )
    
    # Add caller type fields to calls table
    op.add_column('calls', sa.Column('detected_caller_type', sa.String(50), nullable=True))
    op.add_column('calls', sa.Column('caller_type_confidence', sa.Float, nullable=True))
    op.add_column('calls', sa.Column('routing_rule_id', sa.String(64), nullable=True))
    op.add_column('calls', sa.Column('assigned_provider_id', sa.String(64), nullable=True))
    op.add_column('calls', sa.Column('queue_id', sa.String(64), nullable=True))
    op.add_column('calls', sa.Column('routing_metadata', sa.Text, nullable=True))  # JSON routing data
    
    # Add foreign key constraints for calls table
    op.create_foreign_key('fk_calls_routing_rule', 'calls', 'routing_rules', ['routing_rule_id'], ['rule_id'], ondelete='SET NULL')
    op.create_foreign_key('fk_calls_assigned_provider', 'calls', 'providers', ['assigned_provider_id'], ['provider_id'], ondelete='SET NULL')
    op.create_foreign_key('fk_calls_queue', 'calls', 'call_queues', ['queue_id'], ['queue_id'], ondelete='SET NULL')
    
    # Add check constraints
    op.create_check_constraint('check_caller_types_is_deleted', 'caller_types', "is_deleted IN ('yes', 'no')")
    op.create_check_constraint('check_routing_rules_is_deleted', 'routing_rules', "is_deleted IN ('yes', 'no')")
    op.create_check_constraint('check_caller_detection_logs_is_deleted', 'caller_detection_logs', "is_deleted IN ('yes', 'no')")
    op.create_check_constraint('check_provider_capacities_is_deleted', 'provider_capacities', "is_deleted IN ('yes', 'no')")
    op.create_check_constraint('check_call_queues_is_deleted', 'call_queues', "is_deleted IN ('yes', 'no')")
    op.create_check_constraint('check_queued_calls_is_deleted', 'queued_calls', "is_deleted IN ('yes', 'no')")
    
    # Add check constraints for priority levels
    op.create_check_constraint('check_caller_types_priority', 'caller_types', 'priority_level >= 1 AND priority_level <= 5')
    op.create_check_constraint('check_routing_rules_priority', 'routing_rules', 'priority_level >= 1 AND priority_level <= 5')
    op.create_check_constraint('check_call_queues_priority', 'call_queues', 'priority_level >= 1 AND priority_level <= 5')
    
    # Add check constraints for capacity values
    op.create_check_constraint('check_provider_capacities_max_calls', 'provider_capacities', 'max_concurrent_calls > 0')
    op.create_check_constraint('check_provider_capacities_current_calls', 'provider_capacities', 'current_calls >= 0')
    op.create_check_constraint('check_provider_capacities_available', 'provider_capacities', 'available_capacity >= 0')
    
    # Add check constraints for queue sizes
    op.create_check_constraint('check_caller_types_max_queue', 'caller_types', 'max_queue_size >= 0')
    op.create_check_constraint('check_routing_rules_max_queue', 'routing_rules', 'max_queue_size >= 0')
    op.create_check_constraint('check_call_queues_max_size', 'call_queues', 'max_queue_size >= 0')
    op.create_check_constraint('check_call_queues_current_size', 'call_queues', 'current_size >= 0')
    
    # Add check constraints for queued calls status
    op.create_check_constraint('check_queued_calls_status', 'queued_calls', "status IN ('queued', 'assigned', 'completed', 'expired')")
    
    # Add indexes for performance
    op.create_index('idx_caller_types_active', 'caller_types', ['caller_type_id'], 
                   postgresql_where=sa.text("is_deleted = 'no' AND is_active = true"))
    
    op.create_index('idx_routing_rules_active', 'routing_rules', ['rule_id'], 
                   postgresql_where=sa.text("is_deleted = 'no' AND is_enabled = true"))
    
    op.create_index('idx_routing_rules_caller_type', 'routing_rules', ['caller_type_id', 'priority_level'])
    
    op.create_index('idx_caller_detection_logs_call', 'caller_detection_logs', ['call_id'])
    op.create_index('idx_caller_detection_logs_phone', 'caller_detection_logs', ['caller_phone_token'])
    op.create_index('idx_caller_detection_logs_type', 'caller_detection_logs', ['detected_caller_type'])
    
    op.create_index('idx_provider_capacities_provider', 'provider_capacities', ['provider_id'])
    op.create_index('idx_provider_capacities_available', 'provider_capacities', ['is_available', 'available_capacity'])
    
    op.create_index('idx_call_queues_active', 'call_queues', ['queue_id'], 
                   postgresql_where=sa.text("is_deleted = 'no' AND is_active = true"))
    
    op.create_index('idx_queued_calls_queue', 'queued_calls', ['queue_id', 'priority_score'])
    op.create_index('idx_queued_calls_status', 'queued_calls', ['status', 'queued_at'])
    op.create_index('idx_queued_calls_call', 'queued_calls', ['call_id'])
    
    # Add indexes for calls table new fields
    op.create_index('idx_calls_caller_type', 'calls', ['detected_caller_type'])
    op.create_index('idx_calls_assigned_provider', 'calls', ['assigned_provider_id'])
    op.create_index('idx_calls_queue', 'calls', ['queue_id'])
    op.create_index('idx_calls_routing_rule', 'calls', ['routing_rule_id'])
    
    # Insert default caller types
    op.execute("""
        INSERT INTO caller_types (caller_type_id, caller_type_name, description, priority_level, default_routing_strategy, default_overload_policy, max_queue_size) VALUES
        ('CALLER_EMERGENCY', 'emergency', 'Emergency calls requiring immediate attention', 1, 'priority_based', 'escalate', 0),
        ('CALLER_PHYSICIAN', 'physician', 'Calls from physicians and medical professionals', 2, 'skill_based', 'queue', 10),
        ('CALLER_PATIENT', 'patient', 'Patient calls for appointments and inquiries', 3, 'round_robin', 'queue', 50),
        ('CALLER_PHARMACY', 'pharmacy', 'Calls from pharmacies and medication-related inquiries', 3, 'skill_based', 'queue', 20),
        ('CALLER_INSURANCE', 'insurance', 'Insurance-related calls and verification', 3, 'least_loaded', 'queue', 30),
        ('CALLER_UNKNOWN', 'unknown', 'Unknown or unidentified callers', 4, 'round_robin', 'queue', 100)
    """)
    
    # Insert default routing rules
    op.execute("""
        INSERT INTO routing_rules (rule_id, rule_name, caller_type_id, priority_level, routing_strategy, overload_policy, max_queue_size, target_providers) VALUES
        ('RULE_EMERGENCY', 'Emergency Call Routing', 'CALLER_EMERGENCY', 1, 'priority_based', 'escalate', 0, '["emergency_provider"]'),
        ('RULE_PHYSICIAN', 'Physician Call Routing', 'CALLER_PHYSICIAN', 2, 'skill_based', 'queue', 10, '["physician_provider"]'),
        ('RULE_PATIENT', 'Patient Call Routing', 'CALLER_PATIENT', 3, 'round_robin', 'queue', 50, '["patient_provider"]'),
        ('RULE_PHARMACY', 'Pharmacy Call Routing', 'CALLER_PHARMACY', 3, 'skill_based', 'queue', 20, '["pharmacy_provider"]'),
        ('RULE_INSURANCE', 'Insurance Call Routing', 'CALLER_INSURANCE', 3, 'least_loaded', 'queue', 30, '["insurance_provider"]'),
        ('RULE_DEFAULT', 'Default Call Routing', 'CALLER_UNKNOWN', 4, 'round_robin', 'queue', 100, '["general_provider"]')
    """)
    
    # Insert default call queues
    op.execute("""
        INSERT INTO call_queues (queue_id, queue_name, caller_type_id, priority_level, max_queue_size, queue_config) VALUES
        ('QUEUE_EMERGENCY', 'Emergency Queue', 'CALLER_EMERGENCY', 1, 0, '{"timeout_minutes": 0, "escalation_enabled": true}'),
        ('QUEUE_PHYSICIAN', 'Physician Queue', 'CALLER_PHYSICIAN', 2, 10, '{"timeout_minutes": 5, "escalation_enabled": true}'),
        ('QUEUE_PATIENT', 'Patient Queue', 'CALLER_PATIENT', 3, 50, '{"timeout_minutes": 15, "escalation_enabled": false}'),
        ('QUEUE_PHARMACY', 'Pharmacy Queue', 'CALLER_PHARMACY', 3, 20, '{"timeout_minutes": 10, "escalation_enabled": false}'),
        ('QUEUE_INSURANCE', 'Insurance Queue', 'CALLER_INSURANCE', 3, 30, '{"timeout_minutes": 10, "escalation_enabled": false}'),
        ('QUEUE_DEFAULT', 'Default Queue', 'CALLER_UNKNOWN', 4, 100, '{"timeout_minutes": 20, "escalation_enabled": false}')
    """)


def downgrade():
    """
    Remove caller type detection and routing rules tables.
    """
    
    # Drop indexes first
    op.drop_index('idx_calls_routing_rule')
    op.drop_index('idx_calls_queue')
    op.drop_index('idx_calls_assigned_provider')
    op.drop_index('idx_calls_caller_type')
    
    op.drop_index('idx_queued_calls_call')
    op.drop_index('idx_queued_calls_status')
    op.drop_index('idx_queued_calls_queue')
    
    op.drop_index('idx_call_queues_active')
    
    op.drop_index('idx_provider_capacities_available')
    op.drop_index('idx_provider_capacities_provider')
    
    op.drop_index('idx_caller_detection_logs_type')
    op.drop_index('idx_caller_detection_logs_phone')
    op.drop_index('idx_caller_detection_logs_call')
    
    op.drop_index('idx_routing_rules_caller_type')
    op.drop_index('idx_routing_rules_active')
    
    op.drop_index('idx_caller_types_active')
    
    # Drop check constraints
    op.drop_constraint('check_queued_calls_status', 'queued_calls', type_='check')
    op.drop_constraint('check_call_queues_current_size', 'call_queues', type_='check')
    op.drop_constraint('check_call_queues_max_size', 'call_queues', type_='check')
    op.drop_constraint('check_routing_rules_max_queue', 'routing_rules', type_='check')
    op.drop_constraint('check_caller_types_max_queue', 'caller_types', type_='check')
    op.drop_constraint('check_provider_capacities_available', 'provider_capacities', type_='check')
    op.drop_constraint('check_provider_capacities_current_calls', 'provider_capacities', type_='check')
    op.drop_constraint('check_provider_capacities_max_calls', 'provider_capacities', type_='check')
    op.drop_constraint('check_call_queues_priority', 'call_queues', type_='check')
    op.drop_constraint('check_routing_rules_priority', 'routing_rules', type_='check')
    op.drop_constraint('check_caller_types_priority', 'caller_types', type_='check')
    op.drop_constraint('check_queued_calls_is_deleted', 'queued_calls', type_='check')
    op.drop_constraint('check_call_queues_is_deleted', 'call_queues', type_='check')
    op.drop_constraint('check_provider_capacities_is_deleted', 'provider_capacities', type_='check')
    op.drop_constraint('check_caller_detection_logs_is_deleted', 'caller_detection_logs', type_='check')
    op.drop_constraint('check_routing_rules_is_deleted', 'routing_rules', type_='check')
    op.drop_constraint('check_caller_types_is_deleted', 'caller_types', type_='check')
    
    # Drop foreign key constraints from calls table
    op.drop_constraint('fk_calls_queue', 'calls', type_='foreignkey')
    op.drop_constraint('fk_calls_assigned_provider', 'calls', type_='foreignkey')
    op.drop_constraint('fk_calls_routing_rule', 'calls', type_='foreignkey')
    
    # Drop columns from calls table
    op.drop_column('calls', 'routing_metadata')
    op.drop_column('calls', 'queue_id')
    op.drop_column('calls', 'assigned_provider_id')
    op.drop_column('calls', 'routing_rule_id')
    op.drop_column('calls', 'caller_type_confidence')
    op.drop_column('calls', 'detected_caller_type')
    
    # Drop tables
    op.drop_table('queued_calls')
    op.drop_table('call_queues')
    op.drop_table('provider_capacities')
    op.drop_table('caller_detection_logs')
    op.drop_table('routing_rules')
    op.drop_table('caller_types')
