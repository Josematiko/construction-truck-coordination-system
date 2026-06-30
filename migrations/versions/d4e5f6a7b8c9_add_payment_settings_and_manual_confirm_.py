"""add payment settings and manual confirmation fields

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-04-15 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'payment_setting' not in tables:
        op.create_table(
            'payment_setting',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('paybill_number', sa.String(length=30), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

    payment_cols = {col['name'] for col in inspector.get_columns('payment')}
    if 'confirmed_by_admin_id' not in payment_cols:
        op.add_column('payment', sa.Column('confirmed_by_admin_id', sa.Integer(), nullable=True))
    if 'confirmed_at' not in payment_cols:
        op.add_column('payment', sa.Column('confirmed_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    payment_cols = {col['name'] for col in inspector.get_columns('payment')}
    if 'confirmed_at' in payment_cols:
        op.drop_column('payment', 'confirmed_at')
    if 'confirmed_by_admin_id' in payment_cols:
        op.drop_column('payment', 'confirmed_by_admin_id')

    if 'payment_setting' in tables:
        op.drop_table('payment_setting')
