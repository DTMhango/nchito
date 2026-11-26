"""Tailoring requests and versioned document specs with their checks

Revision ID: 0007_tailoring
Revises: 0006_micros
Create Date: 2026-11-26 11:01:35.163971
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0007_tailoring'
down_revision: str | None = '0006_micros'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('tailoring_request',
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('request_key', sa.String(length=64), nullable=False),
    sa.Column('from_version', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'running', 'paused', 'done', 'failed', name='tailoringstatus', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('result_version', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('paused_mark', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('requested_by', sa.String(length=120), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['application.id'], name=op.f('fk_tailoring_request_application_id_application'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['run.id'], name=op.f('fk_tailoring_request_run_id_run'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tailoring_request')),
    sa.UniqueConstraint('application_id', 'request_key', name='application_request_key')
    )
    op.create_index('ix_tailoring_request_status', 'tailoring_request', ['status'], unique=False)
    op.create_table('application_spec_version',
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=True),
    sa.Column('parent_version', sa.Integer(), nullable=True),
    sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('check_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('checked_hash', sa.String(length=64), nullable=True),
    sa.Column('checked_facts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('prompt_version', sa.String(length=40), nullable=True),
    sa.Column('cost_micros', sa.BigInteger(), nullable=False),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['application.id'], name=op.f('fk_application_spec_version_application_id_application'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['request_id'], ['tailoring_request.id'], name=op.f('fk_application_spec_version_request_id_tailoring_request'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_spec_version')),
    sa.UniqueConstraint('application_id', 'version', name='application_spec_version_number'),
    sa.UniqueConstraint('request_id', name=op.f('uq_application_spec_version_request_id'))
    )



def downgrade() -> None:
    op.drop_table('application_spec_version')
    op.drop_index('ix_tailoring_request_status', table_name='tailoring_request')
    op.drop_table('tailoring_request')

