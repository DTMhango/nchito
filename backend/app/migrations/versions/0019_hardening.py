"""hardening: tailoring runs, config rollback link

* ``runkind`` gains ``tailoring`` (run and schedule share the check).
* ``tailoring_request.tailoring_run_id``: the request's own run (history, status, cost).
* ``setting_revision.rollback_of``: the revision a restore brought back.

Revision ID: 0019_hardening
Revises: 0018_blocker_kind
Create Date: 2026-11-27 09:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0019_hardening'
down_revision: str | None = '0018_blocker_kind'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ('sweep', 'rescore', 'expiry_check', 'digest', 'backup', 'retention')
NEW_KINDS = (*OLD_KINDS, 'tailoring')


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _kinds(values: Sequence[str]) -> None:
    for table in ('run', 'schedule'):
        op.drop_constraint(op.f(f'ck_{table}_runkind'), table, type_='check')
        op.create_check_constraint('runkind', table, f"kind IN ({_quoted(values)})")


def upgrade() -> None:
    _kinds(NEW_KINDS)
    op.add_column('tailoring_request', sa.Column('tailoring_run_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_tailoring_request_tailoring_run_id_run'), 'tailoring_request', 'run',
                          ['tailoring_run_id'], ['id'], ondelete='SET NULL')
    op.add_column('setting_revision', sa.Column('rollback_of', postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column('setting_revision', 'rollback_of')
    op.drop_constraint(op.f('fk_tailoring_request_tailoring_run_id_run'), 'tailoring_request', type_='foreignkey')
    op.drop_column('tailoring_request', 'tailoring_run_id')
    op.execute("DELETE FROM run WHERE kind = 'tailoring'")
    _kinds(OLD_KINDS)
