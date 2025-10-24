"""Change users.tg_id to BIGINT

Revision ID: 20251024_change_tg_id_bigint
Revises: None
Create Date: 2025-10-24
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251024_change_tg_id_bigint'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Widen users.tg_id from INTEGER to BIGINT to accommodate large Telegram IDs
    op.alter_column(
        'users',
        'tg_id',
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False
    )


def downgrade():
    # Narrow back to INTEGER (may fail if values exceed 32-bit range)
    op.alter_column(
        'users',
        'tg_id',
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using='tg_id::integer'
    )