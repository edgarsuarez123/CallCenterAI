"""Initial models

Revision ID: 3f270d38367a
Revises: 
Create Date: 2025-11-16 21:28:09.524507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision: str = '3f270d38367a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - create all tables, indexes, and constraints."""
    
    # Note: gen_random_uuid() is available in PostgreSQL 13+ without extensions
    # For older PostgreSQL versions, you may need to enable pgcrypto extension:
    # op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto;')
    
    # Create ENUM types for PostgreSQL
    # Note: Using native PostgreSQL ENUMs for better type safety
    booking_status_enum = postgresql.ENUM('tentative', 'confirmed', 'canceled', name='bookingstatus', create_type=True)
    slot_status_enum = postgresql.ENUM('free', 'booked', 'blocked', name='slotstatus', create_type=True)
    slot_source_enum = postgresql.ENUM('csv', 'gcal', name='slotsource', create_type=True)
    booking_action_enum = postgresql.ENUM('hold', 'confirm', 'cancel', 'expire', name='bookingaction', create_type=True)
    
    booking_status_enum.create(op.get_bind(), checkfirst=True)
    slot_status_enum.create(op.get_bind(), checkfirst=True)
    slot_source_enum.create(op.get_bind(), checkfirst=True)
    booking_action_enum.create(op.get_bind(), checkfirst=True)
    
    # Create clinic table
    op.create_table(
        'clinic',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('tier', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('license_token', sa.Text(), nullable=False),
        sa.Column('license_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('business_hours_start', sa.String(length=5), nullable=False, server_default='09:00'),
        sa.Column('business_hours_end', sa.String(length=5), nullable=False, server_default='17:00'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_clinic_id', 'clinic', ['id'], unique=False)
    op.create_index('ix_clinic_network_id', 'clinic', ['network_id'], unique=False)
    op.create_index('ix_clinic_status', 'clinic', ['status'], unique=False)
    op.create_unique_constraint('uq_clinic_license_token', 'clinic', ['license_token'])
    
    # Create license table
    op.create_table(
        'license',
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('tier', sa.String(length=50), nullable=False),
        sa.Column('max_concurrency', sa.Integer(), nullable=False),
        sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
    )
    op.create_unique_constraint('uq_license_token', 'license', ['token'])
    
    # Create clinic_integration table
    op.create_table(
        'clinic_integration',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('retell_agent_id', sa.Text(), nullable=False),
        sa.Column('retell_did', sa.String(), nullable=False),
        sa.Column('google_service_account_json', sa.Text(), nullable=False),
        sa.Column('default_appointment_length_minutes', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('default_capacity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_clinic_integration_id', 'clinic_integration', ['id'], unique=False)
    op.create_index('ix_clinic_integration_clinic_id', 'clinic_integration', ['clinic_id'], unique=False)
    op.create_unique_constraint('uq_clinic_integration_clinic_id', 'clinic_integration', ['clinic_id'])
    
    # Create provider table
    op.create_table(
        'provider',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('google_calendar_id', sa.String(), nullable=True),
        sa.Column('timezone', sa.String(length=100), nullable=False),
        sa.Column('booking_duration_mins', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('capacity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_provider_id', 'provider', ['id'], unique=False)
    op.create_index('ix_provider_clinic_id', 'provider', ['clinic_id'], unique=False)
    op.create_index('idx_provider_clinic_active', 'provider', ['clinic_id', 'active'], unique=False)
    
    # Create patient table
    op.create_table(
        'patient',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name_token', postgresql.BYTEA(), nullable=False),
        sa.Column('dob_token', postgresql.BYTEA(), nullable=False),
        sa.Column('phone_e164', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('insurance_plan', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_patient_id', 'patient', ['id'], unique=False)
    op.create_index('ix_patient_clinic_id', 'patient', ['clinic_id'], unique=False)
    op.create_index('idx_clinic_phone', 'patient', ['clinic_id', 'phone_e164'], unique=False)
    
    # Create availability_slot table
    op.create_table(
        'availability_slot',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slot_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('slot_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source', slot_source_enum, nullable=False),
        sa.Column('status', slot_status_enum, nullable=False, server_default='free'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['provider_id'], ['provider.id'], ondelete='CASCADE'),
        sa.CheckConstraint('slot_end > slot_start', name='check_availability_slot_end_after_start'),
    )
    op.create_index('ix_availability_slot_id', 'availability_slot', ['id'], unique=False)
    op.create_index('ix_availability_slot_clinic_id', 'availability_slot', ['clinic_id'], unique=False)
    op.create_index('ix_availability_slot_provider_id', 'availability_slot', ['provider_id'], unique=False)
    op.create_index('idx_clinic_status_start', 'availability_slot', ['clinic_id', 'status', 'slot_start'], unique=False)
    op.create_unique_constraint('uq_provider_slot_time', 'availability_slot', ['provider_id', 'slot_start', 'slot_end'])
    
    # Create booking table
    op.create_table(
        'booking',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slot_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('slot_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', booking_status_enum, nullable=False, server_default='tentative'),
        sa.Column('hold_token', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('hold_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('google_event_id', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['provider_id'], ['provider.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patient.id'], ondelete='CASCADE'),
        sa.CheckConstraint('slot_end > slot_start', name='check_booking_slot_end_after_start'),
    )
    op.create_index('ix_booking_id', 'booking', ['id'], unique=False)
    op.create_index('ix_booking_clinic_id', 'booking', ['clinic_id'], unique=False)
    op.create_index('ix_booking_provider_id', 'booking', ['provider_id'], unique=False)
    op.create_index('ix_booking_patient_id', 'booking', ['patient_id'], unique=False)
    op.create_index('idx_status_hold_expires', 'booking', ['status', 'hold_expires_at'], unique=False)
    # Non-unique index for slot lookups (capacity enforcement done at application level)
    op.create_index(
        'idx_booking_slot_lookup',
        'booking',
        ['provider_id', 'slot_start', 'slot_end', 'status'],
        unique=False
    )
    
    # Create booking_audit table
    op.create_table(
        'booking_audit',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('booking_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action', booking_action_enum, nullable=False),
        sa.Column('actor', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['booking_id'], ['booking.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_booking_audit_id', 'booking_audit', ['id'], unique=False)
    op.create_index('ix_booking_audit_clinic_id', 'booking_audit', ['clinic_id'], unique=False)
    op.create_index('ix_booking_audit_booking_id', 'booking_audit', ['booking_id'], unique=False)
    op.create_index('idx_booking_audit_booking', 'booking_audit', ['booking_id'], unique=False)
    op.create_index('idx_booking_audit_clinic_timestamp', 'booking_audit', ['clinic_id', 'timestamp'], unique=False)
    
    # Create phone_route table
    op.create_table(
        'phone_route',
        sa.Column('did_e164', sa.String(), primary_key=True),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('container_url', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinic.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_phone_route_clinic_id', 'phone_route', ['clinic_id'], unique=False)
    op.create_index('idx_phone_route_clinic_active', 'phone_route', ['clinic_id', 'active'], unique=False)
    
    # Create call_log table (no foreign keys - PHI-free)
    op.create_table(
        'call_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('clinic_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('call_type', sa.String(), nullable=False),
        sa.Column('related_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('tentative_booking_id', postgresql.UUID(as_uuid=True), nullable=True),  # For hold cleanup on call_ended
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('outcome', sa.String(), nullable=True),
        sa.Column('retell_call_id', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("call_type IN ('inbound', 'outbound_reminder', 'outbound_campaign')", name='check_call_log_call_type'),
    )
    op.create_index('ix_call_log_id', 'call_log', ['id'], unique=False)
    op.create_index('ix_call_log_clinic_id', 'call_log', ['clinic_id'], unique=False)
    op.create_index('ix_call_log_retell_call_id', 'call_log', ['retell_call_id'], unique=False)
    op.create_index('idx_clinic_call_type_timestamp', 'call_log', ['clinic_id', 'call_type', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema - drop all tables and ENUM types."""
    
    # Drop tables in reverse order (respecting foreign key dependencies)
    op.drop_table('call_log')
    op.drop_table('phone_route')
    op.drop_table('booking_audit')
    op.drop_table('booking')
    op.drop_table('availability_slot')
    op.drop_table('patient')
    op.drop_table('provider')
    op.drop_table('clinic_integration')
    op.drop_table('license')
    op.drop_table('clinic')
    
    # Drop ENUM types
    op.execute('DROP TYPE IF EXISTS bookingaction')
    op.execute('DROP TYPE IF EXISTS bookingstatus')
    op.execute('DROP TYPE IF EXISTS slotsource')
    op.execute('DROP TYPE IF EXISTS slotstatus')
