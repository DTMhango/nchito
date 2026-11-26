"""Posting change tracking: job versions, detected changes, watch bookkeeping

Revision ID: 0013_browser_changes
Revises: 0012_apply_email
Create Date: 2026-11-27 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0013_browser_changes'
down_revision: str | None = '0012_apply_email'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)]


def upgrade() -> None:
    op.create_table(
        'job_version', *_base(),
        sa.Column('job_id', sa.UUID(), nullable=False), sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('snapshot_digest', sa.String(length=64), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_job_version_job_id_job'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_version')),
        sa.UniqueConstraint('job_id', 'snapshot_digest', name='job_snapshot'))
    op.create_index(op.f('ix_job_version_job_id'), 'job_version', ['job_id'])
    op.create_table(
        'job_change', *_base(),
        sa.Column('job_id', sa.UUID(), nullable=False), sa.Column('from_hash', sa.String(length=64), nullable=True),
        sa.Column('to_hash', sa.String(length=64), nullable=True),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('kinds', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('material', sa.Boolean(), nullable=False), sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.String(length=120), nullable=True),
        sa.Column('effects', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_job_change_job_id_job'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_change')))
    op.create_index(op.f('ix_job_change_job_id'), 'job_change', ['job_id'])
    op.create_table(
        'job_watch', *_base(),
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_result', sa.String(length=20), nullable=False), sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_job_watch_job_id_job'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_watch')),
        sa.UniqueConstraint('job_id', name=op.f('uq_job_watch_job_id')))


def downgrade() -> None:
    op.drop_table('job_watch')
    op.drop_index(op.f('ix_job_change_job_id'), table_name='job_change')
    op.drop_table('job_change')
    op.drop_index(op.f('ix_job_version_job_id'), table_name='job_version')
    op.drop_table('job_version')
