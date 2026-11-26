"""follow-ups: outbound messages, follow-up due list, wind-down

Revision ID: 0019_followups
Revises: 0018_blocker_kind
Create Date: 2026-11-26 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019_followups'
down_revision: str | None = '0018_blocker_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'outbound_message', *_base(),
        sa.Column('application_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('thread_id', sa.UUID(), nullable=True),
        sa.Column('thread_ref', sa.String(length=300), nullable=True),
        sa.Column('to', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('cc', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('known_recipients', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('confirmed_recipients', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('subject', sa.Text(), nullable=False),
        sa.Column('paragraphs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('check_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('checked_hash', sa.String(length=64), nullable=True),
        sa.Column('packet_id', sa.UUID(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=True),
        sa.Column('automatic', sa.Boolean(), nullable=False),
        sa.Column('origin', sa.String(length=20), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('cost_micros', sa.BigInteger(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['application.id'],
                                name=op.f('fk_outbound_message_application_id_application'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['thread_id'], ['mail_thread.id'],
                                name=op.f('fk_outbound_message_thread_id_mail_thread'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['packet_id'], ['application_packet.id'],
                                name=op.f('fk_outbound_message_packet_id_application_packet'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_outbound_message')),
    )
    op.create_index('ix_outbound_message_app', 'outbound_message', ['application_id', 'created_at'], unique=False)
    op.create_table(
        'followup_due', *_base(),
        sa.Column('application_id', sa.UUID(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('stage', sa.String(length=40), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('message_id', sa.UUID(), nullable=True),
        sa.Column('pending_action_id', sa.UUID(), nullable=True),
        sa.Column('decided_by', sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(['application_id'], ['application.id'],
                                name=op.f('fk_followup_due_application_id_application'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['outbound_message.id'],
                                name=op.f('fk_followup_due_message_id_outbound_message'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['pending_action_id'], ['pending_action.id'],
                                name=op.f('fk_followup_due_pending_action_id_pending_action'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_followup_due')),
        sa.UniqueConstraint('application_id', 'sequence', name='followup_due_sequence'),
    )
    op.create_index('ix_followup_due_status', 'followup_due', ['status', 'due_at'], unique=False)
    op.create_table(
        'wind_down', *_base(),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('started_by', sa.String(length=120), nullable=False),
        sa.Column('accepted_application_id', sa.UUID(), nullable=True),
        sa.Column('was_paused', sa.Boolean(), nullable=False),
        sa.Column('pause_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('choices', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reopened_by', sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(['accepted_application_id'], ['application.id'],
                                name=op.f('fk_wind_down_accepted_application_id_application'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_wind_down')),
    )


def downgrade() -> None:
    op.drop_table('wind_down')
    op.drop_index('ix_followup_due_status', table_name='followup_due')
    op.drop_table('followup_due')
    op.drop_index('ix_outbound_message_app', table_name='outbound_message')
    op.drop_table('outbound_message')
