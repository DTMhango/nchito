"""Interview pack: generation state on the pack, versioned sections, practice answers

Revision ID: 0013_interview
Revises: 0012_apply_email
Create Date: 2026-11-26 15:14:10.186319
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0013_interview'
down_revision: str | None = '0012_apply_email'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('interview_practice',
    sa.Column('pack_id', sa.UUID(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=True),
    sa.Column('draft_answer', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('feedback', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('check_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['pack_id'], ['interview_pack.id'], name=op.f('fk_interview_practice_pack_id_interview_pack'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_practice'))
    )
    op.create_index(op.f('ix_interview_practice_pack_id'), 'interview_practice', ['pack_id'], unique=False)
    op.create_table('interview_section_version',
    sa.Column('pack_id', sa.UUID(), nullable=False),
    sa.Column('section', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('request_key', sa.String(length=80), nullable=True),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fact_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('check_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('flagged', sa.Boolean(), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['pack_id'], ['interview_pack.id'], name=op.f('fk_interview_section_version_pack_id_interview_pack'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_section_version')),
    sa.UniqueConstraint('pack_id', 'section', 'request_key', name='interview_section_request'),
    sa.UniqueConstraint('pack_id', 'section', 'version', name='interview_section_version_no')
    )
    op.create_index(op.f('ix_interview_section_version_pack_id'), 'interview_section_version', ['pack_id'], unique=False)
    op.add_column('interview_pack', sa.Column('status', sa.Enum('idle', 'queued', 'running', 'paused', 'done', 'failed', name='interviewpackstatus', native_enum=False, create_constraint=True, length=40), server_default='idle', nullable=False))
    op.add_column('interview_pack', sa.Column('generation', sa.Integer(), server_default='0', nullable=False))
    op.add_column('interview_pack', sa.Column('pending_sections', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('interview_pack', sa.Column('basis', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('interview_pack', sa.Column('notes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.add_column('interview_pack', sa.Column('estimate_micros', sa.BigInteger(), nullable=True))
    op.add_column('interview_pack', sa.Column('cost_micros', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('interview_pack', sa.Column('paused_mark', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('interview_pack', sa.Column('error', sa.Text(), nullable=True))
    op.add_column('interview_pack', sa.Column('offered_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('interview_pack', sa.Column('requested_by', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('interview_pack', 'requested_by')
    op.drop_column('interview_pack', 'offered_at')
    op.drop_column('interview_pack', 'error')
    op.drop_column('interview_pack', 'paused_mark')
    op.drop_column('interview_pack', 'cost_micros')
    op.drop_column('interview_pack', 'estimate_micros')
    op.drop_column('interview_pack', 'notes')
    op.drop_column('interview_pack', 'basis')
    op.drop_column('interview_pack', 'pending_sections')
    op.drop_column('interview_pack', 'generation')
    op.drop_column('interview_pack', 'status')
    op.drop_index(op.f('ix_interview_section_version_pack_id'), table_name='interview_section_version')
    op.drop_table('interview_section_version')
    op.drop_index(op.f('ix_interview_practice_pack_id'), table_name='interview_practice')
    op.drop_table('interview_practice')
