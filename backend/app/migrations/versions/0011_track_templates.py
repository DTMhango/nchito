"""Per-track document templates (null falls back to the documents settings)

Revision ID: 0011_track_templates
Revises: 0010_email
Create Date: 2026-11-26 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0011_track_templates'
down_revision: str | None = '0010_email'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('track', sa.Column('cv_template', sa.String(length=60), nullable=True))
    op.add_column('track', sa.Column('letter_template', sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column('track', 'letter_template')
    op.drop_column('track', 'cv_template')
