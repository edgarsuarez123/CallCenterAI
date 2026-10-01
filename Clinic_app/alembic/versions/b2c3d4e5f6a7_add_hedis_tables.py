"""add hedis tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-20 00:00:00.000000

Adds 5 new tables for HEDIS outreach campaign support:
    - clinic_staff     (Google OAuth staff membership per clinic)
    - campaign         (CSV upload batch container)
    - campaign_contact (one row per patient per campaign)
    - campaign_audit   (immutable call-level record per attempt)
    - clinic_ehr_config (NextGen Playwright credentials + appt type mapping)

Also creates 3 PostgreSQL ENUM types: campaignstatus, contactstatus, gaptype
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── PostgreSQL ENUM types ─────────────────────────────────────────────────
    campaignstatus = postgresql.ENUM(
        "pending",
        "active",
        "paused",
        "completed",
        "canceled",
        name="campaignstatus",
    )
    campaignstatus.create(op.get_bind())

    contactstatus = postgresql.ENUM(
        "pending",
        "calling",
        "booked",
        "declined",
        "voicemail",
        "no_answer",
        "error",
        "exhausted",
        name="contactstatus",
    )
    contactstatus.create(op.get_bind())

    gaptype = postgresql.ENUM(
        "colorectal_cancer_screening",
        "breast_cancer_screening",
        "cervical_cancer_screening",
        "diabetes_hba1c",
        "diabetes_eye_exam",
        "diabetes_nephropathy",
        "hypertension_control",
        "depression_screening",
        "well_child_visit",
        "adolescent_well_care",
        "adult_bmi_assessment",
        "medication_adherence_diabetes",
        "medication_adherence_hypertension",
        "other",
        name="gaptype",
    )
    gaptype.create(op.get_bind())

    # ── clinic_staff ──────────────────────────────────────────────────────────
    op.create_table(
        "clinic_staff",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("google_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("clinic_id", "google_sub", name="uq_clinic_staff_clinic_sub"),
    )
    op.create_index("ix_clinic_staff_id", "clinic_staff", ["id"])
    op.create_index("ix_clinic_staff_clinic_id", "clinic_staff", ["clinic_id"])
    op.create_index("idx_staff_google_sub", "clinic_staff", ["google_sub"])

    # ── campaign ──────────────────────────────────────────────────────────────
    op.create_table(
        "campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("total_contacts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("called_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("booked_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("calling_hours_start", sa.String(5), nullable=False, server_default="09:00"),
        sa.Column("calling_hours_end", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("campaign_concurrency_limit", sa.Integer, nullable=False, server_default="3"),
        sa.Column("voicemail_retry_hours", sa.Integer, nullable=False, server_default="4"),
        sa.Column("no_answer_retry_hours", sa.Integer, nullable=False, server_default="2"),
        sa.Column("error_retry_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic_staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "booked_count + failed_count <= total_contacts",
            name="check_campaign_counts_sane",
        ),
    )
    op.create_index("ix_campaign_id", "campaign", ["id"])
    op.create_index("ix_campaign_clinic_id", "campaign", ["clinic_id"])
    op.create_index("ix_campaign_status", "campaign", ["status"])
    op.create_index("idx_campaign_clinic_status", "campaign", ["clinic_id", "status"])

    # ── campaign_contact ──────────────────────────────────────────────────────
    op.create_table(
        "campaign_contact",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone_encrypted", postgresql.BYTEA, nullable=False),
        sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column("gap_type", sa.String(100), nullable=False),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ehr_appointment_id", sa.String, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_campaign_contact_id", "campaign_contact", ["id"])
    op.create_index("ix_campaign_contact_campaign_id", "campaign_contact", ["campaign_id"])
    op.create_index("ix_campaign_contact_clinic_id", "campaign_contact", ["clinic_id"])
    op.create_index("ix_campaign_contact_status", "campaign_contact", ["status"])
    op.create_index(
        "idx_contact_worker_queue",
        "campaign_contact",
        ["clinic_id", "campaign_id", "status", "next_attempt_after"],
    )
    op.create_index("idx_contact_phone_hash", "campaign_contact", ["clinic_id", "phone_hash"])

    # ── campaign_audit ────────────────────────────────────────────────────────
    op.create_table(
        "campaign_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_contact.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("retell_call_id", sa.String, nullable=False),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("patient_name_encrypted", postgresql.BYTEA, nullable=True),
        sa.Column("call_summary_encrypted", postgresql.BYTEA, nullable=True),
        sa.Column("ehr_appointment_id", sa.String, nullable=True),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_campaign_audit_id", "campaign_audit", ["id"])
    op.create_index("ix_campaign_audit_contact_id", "campaign_audit", ["campaign_contact_id"])
    op.create_index("ix_campaign_audit_campaign_id", "campaign_audit", ["campaign_id"])
    op.create_index("ix_campaign_audit_clinic_id", "campaign_audit", ["clinic_id"])
    op.create_index("ix_campaign_audit_retell_call_id", "campaign_audit", ["retell_call_id"])
    op.create_index(
        "idx_audit_clinic_campaign",
        "campaign_audit",
        ["clinic_id", "campaign_id", "called_at"],
    )

    # ── clinic_ehr_config ─────────────────────────────────────────────────────
    op.create_table(
        "clinic_ehr_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clinic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clinic.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("nextgen_url", sa.Text, nullable=False),
        sa.Column("nextgen_username_encrypted", postgresql.BYTEA, nullable=False),
        sa.Column("nextgen_password_encrypted", postgresql.BYTEA, nullable=False),
        sa.Column("appt_type_mapping", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("connection_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_clinic_ehr_config_id", "clinic_ehr_config", ["id"])
    op.create_index("ix_clinic_ehr_config_clinic_id", "clinic_ehr_config", ["clinic_id"])


def downgrade() -> None:
    # Drop tables in reverse FK dependency order
    op.drop_table("clinic_ehr_config")
    op.drop_table("campaign_audit")
    op.drop_table("campaign_contact")
    op.drop_table("campaign")
    op.drop_table("clinic_staff")

    # Drop ENUM types
    postgresql.ENUM(name="gaptype").drop(op.get_bind())
    postgresql.ENUM(name="contactstatus").drop(op.get_bind())
    postgresql.ENUM(name="campaignstatus").drop(op.get_bind())
