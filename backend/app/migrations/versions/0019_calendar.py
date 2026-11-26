"""calendar: interview events, the feed token, a Google Calendar connection provider

Revision ID: 0019_calendar
Revises: 0018_blocker_kind
Create Date: 2026-11-27 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019_calendar'
down_revision: str | None = '0018_blocker_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ('anthropic', 'openai_compatible', 'gmail', 'imap_smtp', 'gdrive', 'msgraph', 'onedrive', 'telegram',
       'webhook', 's3', 'search_api')
NEW = (*OLD, 'gcalendar')
CHECK = 'connectionprovider'


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        'calendar_feed',
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('token_enc', sa.Text(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_calendar_feed')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_calendar_feed_token_hash')),
    )
    op.create_table(
        'interview_event',
        sa.Column('application_id', sa.UUID(), nullable=False),
        sa.Column('round_number', sa.Integer(), server_default='1', nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timezone', sa.String(length=64), nullable=True),
        sa.Column('location', sa.String(length=300), nullable=True),
        sa.Column('meeting_link', sa.String(length=2000), nullable=True),
        sa.Column('interviewers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('candidates', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('source_ref', sa.String(length=300), nullable=True),
        sa.Column('ics_uid', sa.String(length=300), nullable=True),
        sa.Column('replaces_id', sa.UUID(), nullable=True),
        sa.Column('google_event_id', sa.String(length=80), nullable=True),
        sa.Column('google_synced_hash', sa.String(length=64), nullable=True),
        sa.Column('google_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('google_error', sa.String(length=300), nullable=True),
        sa.Column('debrief_asked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('outcome', sa.String(length=20), nullable=True),
        sa.Column('outcome_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['application.id'],
                                name=op.f('fk_interview_event_application_id_application'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['replaces_id'], ['interview_event.id'],
                                name=op.f('fk_interview_event_replaces_id_interview_event'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_event')),
    )
    op.create_index(op.f('ix_interview_event_application_id'), 'interview_event', ['application_id'], unique=False)
    op.create_index('ix_interview_event_start', 'interview_event', ['starts_at'], unique=False)
    op.create_index('ix_interview_event_uid', 'interview_event', ['application_id', 'ics_uid'], unique=False)
    op.drop_constraint(op.f('ck_connection_connectionprovider'), 'connection', type_='check')
    op.create_check_constraint(CHECK, 'connection', f"provider IN ({_quoted(NEW)})")


def downgrade() -> None:
    op.execute("DELETE FROM connection WHERE provider = 'gcalendar'")
    op.drop_constraint(op.f('ck_connection_connectionprovider'), 'connection', type_='check')
    op.create_check_constraint(CHECK, 'connection', f"provider IN ({_quoted(OLD)})")
    op.drop_index('ix_interview_event_uid', table_name='interview_event')
    op.drop_index('ix_interview_event_start', table_name='interview_event')
    op.drop_index(op.f('ix_interview_event_application_id'), table_name='interview_event')
    op.drop_table('interview_event')
    op.drop_table('calendar_feed')
