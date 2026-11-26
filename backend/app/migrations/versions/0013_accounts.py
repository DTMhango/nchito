"""Portal accounts: the owner's notes (never a password)

Revision ID: 0013_accounts
Revises: 0012_apply_email
Create Date: 2026-11-26 22:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0013_accounts'
down_revision: str | None = '0012_apply_email'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('portal_account', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('portal_account', 'notes')
