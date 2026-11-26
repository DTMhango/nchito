"""Dispatch attempts: in-flight marker, evidence and reconciliation bookkeeping (DESIGN.md 8.5, 18.3)

Revision ID: 0009_apply
Revises: 0008_tailoring
Create Date: 2026-11-26 15:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0009_apply'
down_revision: str | None = '0008_tailoring'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('dispatch_attempt', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('dispatch_attempt', sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('dispatch_attempt', sa.Column('reconcile_attempts', sa.Integer(), server_default='0',
                                                nullable=False))
    op.add_column('dispatch_attempt', sa.Column('last_reconciled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('dispatch_attempt', 'last_reconciled_at')
    op.drop_column('dispatch_attempt', 'reconcile_attempts')
    op.drop_column('dispatch_attempt', 'evidence')
    op.drop_column('dispatch_attempt', 'started_at')
