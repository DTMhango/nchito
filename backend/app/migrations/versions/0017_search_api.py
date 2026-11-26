"""connections: a "search API" provider (the web search source's key)

Revision ID: 0017_search_api
Revises: 0016_gateway
Create Date: 2026-11-27 01:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0017_search_api'
down_revision: str | None = '0016_gateway'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ('anthropic', 'openai_compatible', 'gmail', 'imap_smtp', 'gdrive', 'msgraph', 'onedrive', 'telegram',
       'webhook', 's3')
NEW = (*OLD, 'search_api')
CHECK = 'connectionprovider'


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.drop_constraint(op.f('ck_connection_connectionprovider'), 'connection', type_='check')
    op.create_check_constraint(CHECK, 'connection', f"provider IN ({_quoted(NEW)})")


def downgrade() -> None:
    op.execute("DELETE FROM connection WHERE provider = 'search_api'")
    op.drop_constraint(op.f('ck_connection_connectionprovider'), 'connection', type_='check')
    op.create_check_constraint(CHECK, 'connection', f"provider IN ({_quoted(OLD)})")
