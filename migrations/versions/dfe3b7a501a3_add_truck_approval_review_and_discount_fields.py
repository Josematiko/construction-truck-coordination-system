"""Add truck approval, review moderation, and timed discount fields

Revision ID: dfe3b7a501a3
Revises: c1684eff82af
Create Date: 2026-04-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'dfe3b7a501a3'
down_revision = 'c1684eff82af'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('is_primary_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('material', sa.Column('discount_start', sa.Date(), nullable=True))
    op.add_column('material', sa.Column('discount_end', sa.Date(), nullable=True))
    op.add_column('truck', sa.Column('approval_status', sa.String(length=20), nullable=False, server_default='Pending'))
    op.add_column('rating', sa.Column('is_displayed', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('rating', 'is_displayed')
    op.drop_column('truck', 'approval_status')
    op.drop_column('material', 'discount_end')
    op.drop_column('material', 'discount_start')
    op.drop_column('user', 'is_primary_admin')
