"""mock interview sessions and turns; interview round kind and focus

Revision ID: 0019_mock_interview
Revises: 0018_blocker_kind
Create Date: 2026-11-26 19:08:10.046951

Wave 4 stream mock-interview. The coordinator re-chains ``down_revision``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019_mock_interview'
down_revision: str | None = '0018_blocker_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('interview_mock_session',
    sa.Column('pack_id', sa.UUID(), nullable=False),
    sa.Column('round_id', sa.UUID(), nullable=True),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('length', sa.Integer(), nullable=False),
    sa.Column('use_pack_questions', sa.Boolean(), nullable=False),
    sa.Column('feedback_each', sa.Boolean(), nullable=False),
    sa.Column('timer_seconds', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('pending', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('question_index', sa.Integer(), nullable=False),
    sa.Column('probes', sa.Integer(), nullable=False),
    sa.Column('estimate_micros', sa.BigInteger(), nullable=True),
    sa.Column('budget_micros', sa.BigInteger(), nullable=True),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('feedback', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['pack_id'], ['interview_pack.id'], name=op.f('fk_interview_mock_session_pack_id_interview_pack'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['round_id'], ['interview_round.id'], name=op.f('fk_interview_mock_session_round_id_interview_round'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_mock_session'))
    )
    op.create_index(op.f('ix_interview_mock_session_pack_id'), 'interview_mock_session', ['pack_id'], unique=False)
    op.create_index(op.f('ix_interview_mock_session_round_id'), 'interview_mock_session', ['round_id'], unique=False)
    op.create_table('interview_mock_turn',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('step_key', sa.String(length=40), nullable=False),
    sa.Column('role', sa.String(length=12), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('question_index', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=True),
    sa.Column('feedback', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('claims', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fact_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_mock_session.id'], name=op.f('fk_interview_mock_turn_session_id_interview_mock_session'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_mock_turn')),
    sa.UniqueConstraint('session_id', 'seq', name='interview_mock_turn_seq'),
    sa.UniqueConstraint('session_id', 'step_key', name='interview_mock_turn_step')
    )
    op.create_index(op.f('ix_interview_mock_turn_session_id'), 'interview_mock_turn', ['session_id'], unique=False)
    op.add_column('interview_round', sa.Column('kind', sa.String(length=20), nullable=True))
    op.add_column('interview_round', sa.Column('focus', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('interview_round', 'focus')
    op.drop_column('interview_round', 'kind')
    op.drop_index(op.f('ix_interview_mock_turn_session_id'), table_name='interview_mock_turn')
    op.drop_table('interview_mock_turn')
    op.drop_index(op.f('ix_interview_mock_session_round_id'), table_name='interview_mock_session')
    op.drop_index(op.f('ix_interview_mock_session_pack_id'), table_name='interview_mock_session')
    op.drop_table('interview_mock_session')
