"""Remove 'generic' from PostgreSQL gaptype enum (unused by ORM columns)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-24

campaign_contact.gap_type is VARCHAR; this type exists for reference only.
Recreate without `generic` to match Clinic_app/data/enums.py GapType.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    postgresql.ENUM(name="gaptype").drop(conn, checkfirst=True)
    new_gaptype = postgresql.ENUM(
        "preventive_visit",
        "hospital_flu",
        "colorectal",
        "eye_exam",
        "breast_cancer",
        "kidney",
        "afr_cmp",
        "medication_review",
        name="gaptype",
    )
    new_gaptype.create(conn)


def downgrade() -> None:
    conn = op.get_bind()
    postgresql.ENUM(name="gaptype").drop(conn, checkfirst=True)
    old_gaptype = postgresql.ENUM(
        "preventive_visit",
        "hospital_flu",
        "colorectal",
        "eye_exam",
        "breast_cancer",
        "kidney",
        "afr_cmp",
        "medication_review",
        "generic",
        name="gaptype",
    )
    old_gaptype.create(conn)
