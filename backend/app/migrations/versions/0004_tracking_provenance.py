"""tracking: provenance columns, pending action snooze and follow_up type

Revision ID: 0004_tracking
Revises: 0003_intake
Create Date: 2026-11-26 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004_tracking'
down_revision: str | None = '0003_intake'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = ('approve', 'sign_in', 'create_account', 'captcha', 'unknown_question', 'assessment', 'declaration',
             'confirm_submission', 'review_import', 'conflict_choice', 'answer_review_due')
NEW_TYPES = (*OLD_TYPES, 'follow_up')
CHECK = 'pendingactiontype'


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.add_column('application', sa.Column('origin', sa.String(length=20), server_default='system', nullable=False))
    op.add_column('application', sa.Column('owner_attested', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('application', sa.Column('reference', sa.String(length=200), nullable=True))
    op.add_column('application', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('application', sa.Column('legacy_fit', sa.Integer(), nullable=True))
    op.add_column('application', sa.Column('import_key', sa.String(length=200), nullable=True))
    op.add_column('application', sa.Column('import_meta', postgresql.JSONB(astext_type=sa.Text()),
                                           server_default='{}', nullable=False))
    op.create_unique_constraint(op.f('uq_application_import_key'), 'application', ['import_key'])
    op.add_column('job', sa.Column('origin', sa.String(length=20), server_default='system', nullable=False))
    op.add_column('pending_action', sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f('ck_pending_action_pendingactiontype'), 'pending_action', type_='check')
    op.create_check_constraint(CHECK, 'pending_action', f"type IN ({_quoted(NEW_TYPES)})")


def downgrade() -> None:
    op.execute("DELETE FROM pending_action WHERE type = 'follow_up'")
    op.drop_constraint(op.f('ck_pending_action_pendingactiontype'), 'pending_action', type_='check')
    op.create_check_constraint(CHECK, 'pending_action', f"type IN ({_quoted(OLD_TYPES)})")
    op.drop_column('pending_action', 'snoozed_until')
    op.drop_column('job', 'origin')
    op.drop_constraint(op.f('uq_application_import_key'), 'application', type_='unique')
    for col in ('import_meta', 'import_key', 'legacy_fit', 'notes', 'reference', 'owner_attested', 'origin'):
        op.drop_column('application', col)
