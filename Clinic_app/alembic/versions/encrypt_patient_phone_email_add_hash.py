"""encrypt patient phone email add hash

Revision ID: a1b2c3d4e5f6
Revises: 3f270d38367a
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3f270d38367a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Encrypt patient phone and email, add name_dob_hash for efficient lookup."""
    
    # Drop old phone-based index
    op.drop_index('idx_clinic_phone', table_name='patient')
    
    # Add new encrypted columns (nullable first, since we'll drop old columns)
    # For Phase 1: no existing data, so we can safely add as nullable then alter to NOT NULL
    op.add_column('patient', sa.Column('phone_token', postgresql.BYTEA(), nullable=True))
    op.add_column('patient', sa.Column('email_token', postgresql.BYTEA(), nullable=True))
    op.add_column('patient', sa.Column('name_dob_hash', sa.String(length=64), nullable=True))
    
    # Note: For Phase 1, no existing data to migrate. If there were data, we would:
    # 1. Query all patients
    # 2. Decrypt name_token and dob_token
    # 3. Compute name_dob_hash
    # 4. Encrypt phone_e164 and email
    # 5. Update each row with encrypted values and hash
    
    # Drop old unencrypted columns
    op.drop_column('patient', 'phone_e164')
    op.drop_column('patient', 'email')
    
    # Alter new columns to NOT NULL (safe since no data exists in Phase 1)
    op.alter_column('patient', 'phone_token', nullable=False)
    op.alter_column('patient', 'name_dob_hash', nullable=False)
    
    # Create new hash-based index for efficient lookup
    op.create_index('idx_clinic_name_dob_hash', 'patient', ['clinic_id', 'name_dob_hash'], unique=False)


def downgrade() -> None:
    """Revert to unencrypted phone and email, remove hash column."""
    
    # Drop new hash-based index
    op.drop_index('idx_clinic_name_dob_hash', table_name='patient')
    
    # Add back old unencrypted columns (nullable first)
    op.add_column('patient', sa.Column('phone_e164', sa.String(), nullable=True))
    op.add_column('patient', sa.Column('email', sa.String(), nullable=True))
    
    # Note: For downgrade, we would need to decrypt phone_token and email_token
    # For Phase 1, no data exists, so we can just drop the encrypted columns
    
    # Drop encrypted columns
    op.drop_column('patient', 'phone_token')
    op.drop_column('patient', 'email_token')
    op.drop_column('patient', 'name_dob_hash')
    
    # Alter phone_e164 to NOT NULL (safe since no data exists in Phase 1)
    op.alter_column('patient', 'phone_e164', nullable=False)
    
    # Recreate old phone-based index
    op.create_index('idx_clinic_phone', 'patient', ['clinic_id', 'phone_e164'], unique=False)

