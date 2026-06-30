"""add driver dispatch tables

Revision ID: b1f2c3d4e5f6
Revises: dfe3b7a501a3
Create Date: 2026-04-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1f2c3d4e5f6'
down_revision = 'dfe3b7a501a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'driver_dispatch_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=30), nullable=False),
        sa.Column('next_driver_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['next_driver_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )
    op.create_table(
        'driver_assignment_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('driver_id', sa.Integer(), nullable=False),
        sa.Column('truck_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['user.id']),
        sa.ForeignKeyConstraint(['order_id'], ['order.id']),
        sa.ForeignKeyConstraint(['truck_id'], ['truck.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('driver_assignment_log')
    op.drop_table('driver_dispatch_state')
