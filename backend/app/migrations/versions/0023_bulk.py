"""bulk operations and employer policies

Revision ID: 0023_bulk
Revises: 0022_feedback
Create Date: 2026-11-26 19:09:24.115007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0023_bulk'
down_revision: str | None = '0022_feedback'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('bulk_operation',
    sa.Column('subject', sa.String(length=20), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('selection', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('selected', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('undo_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bulk_operation'))
    )
    op.create_index('ix_bulk_operation_status', 'bulk_operation', ['status'], unique=False)
    op.create_table('employer_policy',
    sa.Column('employer_key', sa.String(length=200), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('cooldown_days', sa.Integer(), nullable=True),
    sa.Column('always_ask_first', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('never_apply', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('never_reason', sa.Text(), nullable=True),
    sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
    sa.Column('watched', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('cooldown_released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cooldown_released_reason', sa.Text(), nullable=True),
    sa.Column('cooldown_released_by', sa.String(length=120), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employer_policy')),
    sa.UniqueConstraint('employer_key', name=op.f('uq_employer_policy_employer_key'))
    )
    op.create_table('bulk_item',
    sa.Column('operation_id', sa.UUID(), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(length=400), nullable=False),
    sa.Column('planned', sa.String(length=20), nullable=False),
    sa.Column('planned_code', sa.String(length=60), nullable=True),
    sa.Column('planned_reason', sa.Text(), nullable=True),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('code', sa.String(length=60), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('undo', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['operation_id'], ['bulk_operation.id'], name=op.f('fk_bulk_item_operation_id_bulk_operation'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bulk_item')),
    sa.UniqueConstraint('operation_id', 'subject_id', name='bulk_item_subject')
    )
    op.create_index('ix_bulk_item_operation', 'bulk_item', ['operation_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_bulk_item_operation', table_name='bulk_item')
    op.drop_table('bulk_item')
    op.drop_table('employer_policy')
    op.drop_index('ix_bulk_operation_status', table_name='bulk_operation')
    op.drop_table('bulk_operation')
