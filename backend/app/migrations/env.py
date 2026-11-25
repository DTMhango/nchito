"""Alembic environment. Migrations run over sync psycopg (multi-statement SQL is needed for
the queue schema); the application itself uses asyncpg."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers every table)
from app.core.config import get_config
from app.core.migrations import include_object, render_item
from app.models.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    override = config.get_main_option("sqlalchemy.url")
    url = override or get_config().database_url
    return "postgresql+psycopg://" + url.split("://", 1)[1]


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_item=render_item,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_item=render_item,
                          compare_type=True, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
