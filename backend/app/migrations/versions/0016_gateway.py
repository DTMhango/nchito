"""gateway: pending action types for runner blockers with no type of their own

Revision ID: 0016_gateway
Revises: 0015_browser_changes
Create Date: 2026-11-26 23:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0016_gateway'
down_revision: str | None = '0015_browser_changes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = ('approve', 'sign_in', 'create_account', 'captcha', 'unknown_question', 'assessment', 'declaration',
             'confirm_submission', 'review_import', 'conflict_choice', 'answer_review_due', 'follow_up')
ADDED = ('unsupported_form', 'redirect_off_domain', 'page_instruction')
NEW_TYPES = (*OLD_TYPES, *ADDED)
CHECK = 'pendingactiontype'


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint(op.f('ck_pending_action_pendingactiontype'), 'pending_action', type_='check')
    op.create_check_constraint(CHECK, 'pending_action', f"type IN ({_quoted(NEW_TYPES)})")


def downgrade() -> None:
    op.execute(f"DELETE FROM pending_action WHERE type IN ({_quoted(ADDED)})")
    op.drop_constraint(op.f('ck_pending_action_pendingactiontype'), 'pending_action', type_='check')
    op.create_check_constraint(CHECK, 'pending_action', f"type IN ({_quoted(OLD_TYPES)})")
