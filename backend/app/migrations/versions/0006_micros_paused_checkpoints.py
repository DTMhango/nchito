"""AI spend in integer micros; paused runs; per-source sweep checkpoints

Costs were stored in whole minor units (cents), rounded up per call. They are now integer micros
(millionths of the major unit): existing amounts are multiplied by 10_000, so history keeps its
value. The ledger's append-only trigger is suspended only for that conversion.

Revision ID: 0006_micros
Revises: 0005_match
Create Date: 2026-11-26 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0006_micros'
down_revision: str | None = '0005_match'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MICROS_PER_MINOR = 10_000
COST_COLUMNS = (("run", "cost"), ("assessment", "cost"), ("extraction_cache", "cost"), ("ledger_entry", "amount"))
OLD_STATUSES = ("queued", "running", "succeeded", "failed", "partial", "cancelled", "skipped")


def _status_check(statuses: Sequence[str]) -> None:
    op.drop_constraint("runstatus", "run", type_="check")
    values = ", ".join(f"'{s}'" for s in statuses)
    op.create_check_constraint("runstatus", "run", f"status IN ({values})")


def _convert(direction: str) -> None:
    op.execute("ALTER TABLE ledger_entry DISABLE TRIGGER USER")
    for table, stem in COST_COLUMNS:
        if direction == "up":
            op.alter_column(table, f"{stem}_minor", new_column_name=f"{stem}_micros")
            op.execute(f"UPDATE {table} SET {stem}_micros = {stem}_micros * {MICROS_PER_MINOR}")
        else:
            op.execute(f"UPDATE {table} SET {stem}_micros = CEIL({stem}_micros::numeric / {MICROS_PER_MINOR})")
            op.alter_column(table, f"{stem}_micros", new_column_name=f"{stem}_minor")
    op.execute("ALTER TABLE ledger_entry ENABLE TRIGGER USER")


def upgrade() -> None:
    _convert("up")
    _status_check((*OLD_STATUSES, "paused"))
    op.add_column("campaign", sa.Column("source_checkpoints", postgresql.JSONB(astext_type=sa.Text()),
                                        nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("campaign", "source_checkpoints")
    op.execute("UPDATE run SET status = 'partial' WHERE status = 'paused'")
    _status_check(OLD_STATUSES)
    _convert("down")
