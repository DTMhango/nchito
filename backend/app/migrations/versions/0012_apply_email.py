"""The owner's application address per job: an override and the address the owner confirmed

Revision ID: 0012_apply_email
Revises: 0011_track_templates
Create Date: 2026-11-26 21:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0012_apply_email'
down_revision: str | None = '0011_track_templates'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('job', sa.Column('apply_email_owner', sa.String(length=320), nullable=True))
    op.add_column('job', sa.Column('apply_email_confirmed', sa.String(length=320), nullable=True))
    op.add_column('job', sa.Column('apply_email_confirmed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('job', sa.Column('apply_email_confirmed_by', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('job', 'apply_email_confirmed_by')
    op.drop_column('job', 'apply_email_confirmed_at')
    op.drop_column('job', 'apply_email_confirmed')
    op.drop_column('job', 'apply_email_owner')
