"""MVP: update GapType enum, add ContactStatus values, add contact columns

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-23 00:00:00.000000

Changes:
  1. Replace the 'gaptype' PG ENUM with finalized Plan 013 values:
       preventive_visit, hospital_flu, colorectal, eye_exam, breast_cancer,
       kidney, afr_cmp, medication_review, generic
     (campaign_contact.gap_type is String — no column ALTER needed; PG type
      kept in sync for reference / future typed columns)

  2. Add new values to the 'contactstatus' PG ENUM:
       order_agreed, order_declined, not_yet_eligible, expired, human_requested
     (ADD VALUE IF NOT EXISTS — safe to re-run)

  3. Add columns to campaign_contact:
       release_date    DATE     nullable  — hospital_flu discharge date
       priority_order  INTEGER  not null default 1  — 0 = hospital_flu (always first)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Replace gaptype PG ENUM ────────────────────────────────────────────
    # campaign_contact.gap_type uses VARCHAR — no ALTER COLUMN needed.
    # Drop old type and recreate with finalized values.
    postgresql.ENUM(name='gaptype').drop(conn, checkfirst=True)
    new_gaptype = postgresql.ENUM(
        'preventive_visit',
        'hospital_flu',
        'colorectal',
        'eye_exam',
        'breast_cancer',
        'kidney',
        'afr_cmp',
        'medication_review',
        'generic',
        name='gaptype',
    )
    new_gaptype.create(conn)

    # ── 2. Add new ContactStatus values ──────────────────────────────────────
    new_contact_statuses = [
        'order_agreed',
        'order_declined',
        'not_yet_eligible',
        'expired',
        'human_requested',
    ]
    for value in new_contact_statuses:
        conn.execute(
            sa.text(f"ALTER TYPE contactstatus ADD VALUE IF NOT EXISTS '{value}'")
        )

    # ── 3. Add columns to campaign_contact ───────────────────────────────────
    op.add_column(
        'campaign_contact',
        sa.Column('release_date', sa.Date, nullable=True),
    )
    op.add_column(
        'campaign_contact',
        sa.Column(
            'priority_order',
            sa.Integer,
            nullable=False,
            server_default='1',
        ),
    )


def downgrade() -> None:
    # Remove added columns
    op.drop_column('campaign_contact', 'priority_order')
    op.drop_column('campaign_contact', 'release_date')

    # Note: PostgreSQL does not support removing values from an ENUM type.
    # To restore old contactstatus values, a full type replacement would be needed.
    # For safety, downgrade only removes columns; enum rollback requires manual intervention.

    # Restore original gaptype PG ENUM
    postgresql.ENUM(name='gaptype').drop(op.get_bind(), checkfirst=True)
    old_gaptype = postgresql.ENUM(
        'colorectal_cancer_screening',
        'breast_cancer_screening',
        'cervical_cancer_screening',
        'diabetes_hba1c',
        'diabetes_eye_exam',
        'diabetes_nephropathy',
        'hypertension_control',
        'depression_screening',
        'well_child_visit',
        'adolescent_well_care',
        'adult_bmi_assessment',
        'medication_adherence_diabetes',
        'medication_adherence_hypertension',
        'other',
        name='gaptype',
    )
    old_gaptype.create(op.get_bind())
