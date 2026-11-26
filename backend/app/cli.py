"""Command line: ``nchito migrate | web | worker | openapi | contracts | gen-key | worker-alive | restored``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.core.config import get_config

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini")) if (BACKEND_DIR / "alembic.ini").exists() else Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    return cfg


async def seed() -> None:
    from app.core.db import dispose_engine, get_sessionmaker
    from app.themes.service import seed_builtin_themes

    async with get_sessionmaker()() as session:
        await seed_builtin_themes(session)
        await session.commit()
    await dispose_engine()


def migrate() -> None:
    from alembic import command

    command.upgrade(_alembic_config(), "head")
    asyncio.run(seed())


def write_openapi(path: str | None) -> None:
    from app.main import create_app

    spec = create_app(spa_dir=Path("/nonexistent")).openapi()
    text = json.dumps(spec, indent=2, sort_keys=False) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)


def contract_documents() -> dict[str, object]:
    """Every generated contract document, keyed by its path under docs/."""
    from app.core.conditions import ConditionSet
    from app.gateway.tools import tool_schemas
    from app.kit.schema import KitFile
    from app.main import create_app
    from app.themes.schema import ThemeBody

    return {
        "openapi.json": create_app(spa_dir=Path("/nonexistent")).openapi(),
        "schemas/gateway-tools.json": tool_schemas(),
        "schemas/kit.schema.json": KitFile.model_json_schema(),
        "schemas/theme.schema.json": ThemeBody.model_json_schema(),
        "schemas/conditions.schema.json": ConditionSet.model_json_schema(),
    }


def write_contracts(docs_dir: str) -> None:
    root = Path(docs_dir)
    for rel, doc in contract_documents().items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {target}")


async def worker_alive() -> bool:
    """Container healthcheck for the worker: a heartbeat fresher than the stale threshold."""
    from sqlalchemy import func, select

    from app.core.clock import utcnow
    from app.core.db import dispose_engine, get_sessionmaker
    from app.models.platform import WorkerHeartbeat

    async with get_sessionmaker()() as session:
        last = await session.scalar(select(func.max(WorkerHeartbeat.beat_at)))
    await dispose_engine()
    return last is not None and (utcnow() - last).total_seconds() <= get_config().worker_stale_after_seconds


async def restored(backup_taken_at: str | None) -> None:
    """Mark this database as restored from a backup: everything pauses until reconciled (DESIGN.md 18.3)."""
    from datetime import datetime

    from app.apply import restore
    from app.core.db import dispose_engine, get_sessionmaker

    taken = datetime.fromisoformat(backup_taken_at) if backup_taken_at else None
    async with get_sessionmaker()() as session:
        st = await restore.enter(session, backup_taken_at=taken)
        await session.commit()
    await dispose_engine()
    print(f"paused for restore: {len(st.outstanding)} send(s) to reconcile, "
          f"{len(st.held_application_ids)} approval(s) withdrawn")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nchito")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Apply database migrations and seed built-in data")
    web = sub.add_parser("web", help="Run the web server")
    web.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container default
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--reload", action="store_true")
    sub.add_parser("worker", help="Run the queue worker, scheduler tick and heartbeat")
    oa = sub.add_parser("openapi", help="Write the OpenAPI document")
    oa.add_argument("--out", default=None)
    contracts = sub.add_parser("contracts", help="Write docs/openapi.json and docs/schemas/*.json")
    contracts.add_argument("--docs-dir", default=str(BACKEND_DIR.parent / "docs"))
    sub.add_parser("gen-key", help="Print a new ENCRYPTION_KEY")
    sub.add_parser("worker-alive", help="Exit 0 if a worker heartbeat is fresh (container healthcheck)")
    rs = sub.add_parser("restored", help="After restoring a backup: start paused until sends are reconciled")
    rs.add_argument("--backup-taken-at", default=None, help="ISO time the backup was taken")
    args = parser.parse_args(argv)

    logging.basicConfig(level=get_config().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "web":
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, proxy_headers=True,
                    forwarded_allow_ips="*")
    elif args.cmd == "worker":
        from app.worker.main import run_worker

        asyncio.run(run_worker())
    elif args.cmd == "openapi":
        write_openapi(args.out)
    elif args.cmd == "contracts":
        write_contracts(args.docs_dir)
    elif args.cmd == "gen-key":
        from app.core.crypto import generate_key

        print(generate_key())
    elif args.cmd == "restored":
        asyncio.run(restored(args.backup_taken_at))
    elif args.cmd == "worker-alive":
        sys.exit(0 if asyncio.run(worker_alive()) else 1)


if __name__ == "__main__":
    main()
