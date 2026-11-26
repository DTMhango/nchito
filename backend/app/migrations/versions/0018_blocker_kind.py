"""pending actions: a gateway blocker's ``detail.kind`` is its exact blocker kind (was ``"blocker"``)

Revision ID: 0018_blocker_kind
Revises: 0017_search_api
Create Date: 2026-11-26 12:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0018_blocker_kind'
down_revision: str | None = '0017_search_api'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE pending_action SET detail = jsonb_set(detail, '{kind}', detail->'blocker') "
               "WHERE detail->>'kind' = 'blocker' AND detail ? 'blocker'")


def downgrade() -> None:
    pass  # the exact kind is a superset of the old marker; nothing to undo
