"""theme studio: theme revisions (undo/redo), current revision and recorded contrast waiver on theme

Revision ID: 0020_themes
Revises: 0019_hardening
Create Date: 2026-11-26 20:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0020_themes'
down_revision: str | None = '0019_hardening'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('theme', sa.Column('current_revision', sa.Integer(), nullable=True))
    op.add_column('theme', sa.Column('contrast_waiver', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        'theme_revision',
        sa.Column('theme_id', sa.UUID(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('parent', sa.Integer(), nullable=True),
        sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('note', sa.String(length=120), nullable=False),
        sa.Column('actor', sa.String(length=120), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['theme_id'], ['theme.id'], name=op.f('fk_theme_revision_theme_id_theme'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_theme_revision')),
    )
    op.create_index('uq_theme_revision_number', 'theme_revision', ['theme_id', 'number'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_theme_revision_number', table_name='theme_revision')
    op.drop_table('theme_revision')
    op.drop_column('theme', 'contrast_waiver')
    op.drop_column('theme', 'current_revision')
