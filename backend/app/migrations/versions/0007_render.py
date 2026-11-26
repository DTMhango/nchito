"""Rendered application documents

Revision ID: 0007_render
Revises: 0006_micros
Create Date: 2026-11-26 15:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0007_render'
down_revision: str | None = '0006_micros'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'application_document',
        sa.Column('application_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('fmt', sa.String(length=10), nullable=False),
        sa.Column('template_key', sa.String(length=60), nullable=False),
        sa.Column('spec_hash', sa.String(length=64), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('file_key', sa.String(length=300), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['application.id'],
                                name=op.f('fk_application_document_application_id_application'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_application_document')),
        sa.UniqueConstraint('application_id', 'kind', 'fmt', 'input_hash', name='application_kind_fmt_input'),
    )
    op.create_index(op.f('ix_application_document_application_id'), 'application_document', ['application_id'],
                    unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_application_document_application_id'), table_name='application_document')
    op.drop_table('application_document')
