"""Test harness.

Needs PostgreSQL. Start the throwaway one with ``docker compose -f docker-compose.test.yml up -d``
(listens on 127.0.0.1:55442) or point ``TEST_DATABASE_URL`` at any server where the user may
create databases. Each xdist worker gets its own database, migrated once; every test starts
from empty tables plus the seeded built-in themes. No test touches the network beyond that
database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest

ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://nchito:nchito@127.0.0.1:55442/nchito_test")
WORKER = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
DB_NAME = f"nchito_t_{WORKER}"
BASE = ADMIN_URL.rsplit("/", 1)[0]
TEST_DB_URL = f"{BASE}/{DB_NAME}"

# Configure the app before anything imports it (get_config is cached).
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["BASE_URL"] = "http://testserver"
os.environ.pop("ENCRYPTION_KEY", None)
os.environ.pop("APP_NAME", None)

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

KEEP_TABLES = {"alembic_version"}


def _admin_exec(sql: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(sql)


def recreate_database(name: str) -> str:
    _admin_exec(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    _admin_exec(f'CREATE DATABASE "{name}"')
    return f"{BASE}/{name}"


def run_migrations(url: str, revision: str = "head", *, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "app" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if down:
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


@pytest.fixture(scope="session")
def database() -> Iterator[str]:
    url = recreate_database(DB_NAME)
    run_migrations(url)
    yield url
    from app.core.db import get_engine

    get_engine().sync_engine.dispose()
    _admin_exec(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


@pytest.fixture(scope="session")
def table_names(database: str) -> list[str]:
    with psycopg.connect(database) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE 'procrastinate%'"
        ).fetchall()
    return [r[0] for r in rows if r[0] not in KEEP_TABLES]


@pytest.fixture(autouse=True)
async def clean_db(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    if "nodb" in request.keywords:
        yield
        return
    request.getfixturevalue("database")
    tables = request.getfixturevalue("table_names")
    from app.core.db import get_sessionmaker
    from app.themes.service import seed_builtin_themes

    async with get_sessionmaker()() as s:
        await s.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
        await s.execute(text("TRUNCATE procrastinate_jobs, procrastinate_periodic_defers RESTART IDENTITY CASCADE"))
        await seed_builtin_themes(s)
        await s.commit()
    yield


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as s:
        yield s
        await s.rollback()


@pytest.fixture(scope="session")
def app():
    from app.main import create_app

    return create_app(spa_dir=Path("/nonexistent-spa"))


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("10.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


OWNER = {
    "email": "owner@example.com",
    "password": "correct horse battery staple",
    "display_name": "Test Owner",
    "timezone": "Africa/Lusaka",
}


@pytest.fixture
async def owner_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    r = await client.post("/api/setup/owner", json=OWNER)
    assert r.status_code == 201, r.text
    return client


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "nodb: test needs no database")


def new_id() -> uuid.UUID:
    return uuid.uuid4()
