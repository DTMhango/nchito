"""The first migration applies on a clean database, matches the models, and reverses cleanly."""

from __future__ import annotations

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.core.migrations import include_object
from app.models.base import Base
from tests.conftest import WORKER, _admin_exec, recreate_database, run_migrations

pytestmark = pytest.mark.nodb


def _tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        return {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}


def test_upgrade_downgrade_upgrade_on_clean_db():
    name = f"nchito_mig_{WORKER}"
    url = recreate_database(name)
    try:
        run_migrations(url)
        tables = _tables(url)
        assert set(Base.metadata.tables) <= tables
        assert "procrastinate_jobs" in tables

        engine = create_engine("postgresql+psycopg://" + url.split("://", 1)[1])
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True})
            diff = compare_metadata(ctx, Base.metadata)
        engine.dispose()
        assert diff == [], diff

        run_migrations(url, "base", down=True)
        assert _tables(url) == {"alembic_version"}
        run_migrations(url)
        assert set(Base.metadata.tables) <= _tables(url)
    finally:
        _admin_exec(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
