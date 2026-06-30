"""add mpesa fields to payment

Revision ID: c2d3e4f5a6b7
Revises: b1f2c3d4e5f6
Create Date: 2026-04-15 13:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1f2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payment', sa.Column('provider_reference', sa.String(length=120), nullable=True))
    op.add_column('payment', sa.Column('status_message', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('payment', 'status_message')
    op.drop_column('payment', 'provider_reference')
