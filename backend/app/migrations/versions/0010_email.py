"""Mail threads: information_request classification, sender and last message time

Revision ID: 0010_email
Revises: 0009_apply
Create Date: 2026-11-26 15:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010_email'
down_revision: str | None = '0009_apply'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "mailclassification"
OLD = ("confirmation", "rejection", "interview", "other")
NEW = ("confirmation", "rejection", "interview", "information_request", "other")


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.add_column('mail_thread', sa.Column('sender', sa.String(length=320), nullable=True))
    op.add_column('mail_thread', sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f('ck_mail_thread_mailclassification'), 'mail_thread', type_='check')
    op.create_check_constraint(CHECK, 'mail_thread', f"classification IN ({_quoted(NEW)})")


def downgrade() -> None:
    op.execute("UPDATE mail_thread SET classification = 'other' WHERE classification = 'information_request'")
    op.drop_constraint(op.f('ck_mail_thread_mailclassification'), 'mail_thread', type_='check')
    op.create_check_constraint(CHECK, 'mail_thread', f"classification IN ({_quoted(OLD)})")
    op.drop_column('mail_thread', 'last_message_at')
    op.drop_column('mail_thread', 'sender')
