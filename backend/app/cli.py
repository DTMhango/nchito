"""Command line: ``nchito migrate | web | worker | openapi | contracts | gen-key | worker-alive | restored |
demo-job``."""

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


def backup_now() -> int:
    """Write one encrypted backup to the backup folder (no remote copy). Prints its path."""
    from app.ops import backup

    info = asyncio.run(backup.create_backup())
    print(f"backup written: {info.path} ({info.size_bytes} bytes, {info.files} files)")
    return 0


def restore(path: str, *, database_url: str | None, files_dir: str | None, pause: bool, inspect: bool,
            yes: bool) -> int:
    """Restore a backup. Without --yes it only shows what the backup holds and what would be replaced.

    A restore always ends paused for restore (``app.apply.restore.enter``): in-flight sends become
    uncertain and are reconciled, approvals of unsent roles are withdrawn. ``--no-pause`` is for
    rehearsals into a scratch database only.
    """
    from app.ops import restore as restore_mod

    target_db = database_url or get_config().libpq_url
    target_files = Path(files_dir) if files_dir else get_config().files_dir
    manifest = restore_mod.describe(Path(path))
    print(f"backup made {manifest['created_at']} (schema {manifest.get('alembic_revision')}, "
          f"{manifest.get('vault_files')} files)")
    if inspect:
        return 0
    if not yes:
        print(f"This REPLACES the data in {target_db.rsplit('@', 1)[-1]} and moves {target_files} aside. "
              "Run again with --yes to proceed.")
        return 2
    result = asyncio.run(restore_mod.restore_backup(Path(path), database_url=target_db, files_dir=target_files,
                                                    pause=pause))
    print(f"restored: {result.tables_checked} tables verified, {result.files_restored} files."
          + (f" Previous files kept in {result.files_moved_to}." if result.files_moved_to else ""))
    if result.paused:
        try:
            asyncio.run(restored(str(manifest["created_at"]), database_url=target_db))
        except Exception as exc:  # an older schema: the plain pause stays in place
            print(f"automation is paused, but the restore reconciliation could not start ({type(exc).__name__}). "
                  "Run `nchito migrate`, then `nchito restored --backup-taken-at "
                  f"{manifest['created_at']}` before resuming.")
            return 3
    if result.app_revision:
        print(f"Run `nchito migrate` if this release is newer than schema {result.app_revision}.")
    return 0


async def restored(backup_taken_at: str | None, *, database_url: str | None = None) -> None:
    """Mark this database as restored from a backup: everything pauses until reconciled (DESIGN.md 18.3)."""
    from datetime import datetime

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.apply import restore as apply_restore

    url = database_url or get_config().libpq_url
    engine = create_async_engine("postgresql+asyncpg://" + url.split("://", 1)[1])
    taken = datetime.fromisoformat(backup_taken_at) if backup_taken_at else None
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            st = await apply_restore.enter(session, backup_taken_at=taken)
            await session.commit()
    finally:
        await engine.dispose()
    print(f"paused for restore: {len(st.outstanding)} send(s) to reconcile, "
          f"{len(st.held_application_ids)} approval(s) withdrawn. The instance is PAUSED: check the "
          "reconciliation list, then resume.")


async def demo_job() -> int:
    """Insert one fictional role, scored with no model call, shortlisted for the Studio (refused in production)."""
    from app.core.db import dispose_engine, get_sessionmaker
    from app.ops import demo

    try:
        demo.refuse_in_production()
    except demo.DemoRefused as exc:
        print(f"refused: {exc}")
        return 2
    try:
        async with get_sessionmaker()() as session:
            made = await demo.create(session)
            await session.commit()
    finally:
        await dispose_engine()
    scores = ", ".join(f"{k}: {v}" for k, v in made.scores.items()) or "no campaign to score against"
    print(f"demo job {made.job_id} (application {made.application_id}); scores: {scores}. "
          f"Open /jobs/{made.job_id} or /studio?application={made.application_id}.")
    return 0


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
    sub.add_parser("backup", help="Write an encrypted backup to the backup folder now")
    rs = sub.add_parser("restore", help="Restore an encrypted backup (database and files)")
    rs.add_argument("file", help="Path of a .backup file")
    rs.add_argument("--database-url", default=None, help="libpq URL of the target database (default: DATABASE_URL)")
    rs.add_argument("--files-dir", default=None, help="Folder to restore files into (default: FILES_DIR)")
    rs.add_argument("--no-pause", action="store_true", help="Do not pause automation after the restore")
    rs.add_argument("--inspect", action="store_true", help="Only print what the backup holds")
    rs.add_argument("--yes", action="store_true", help="Confirm that existing data may be replaced")
    sub.add_parser("worker-alive", help="Exit 0 if a worker heartbeat is fresh (container healthcheck)")
    rd = sub.add_parser("restored", help="Mark a restored database paused for restore (restore does this itself)")
    rd.add_argument("--backup-taken-at", default=None, help="ISO time the backup was taken")
    sub.add_parser("demo-job", help="Insert one fictional role for manual testing (refused in production)")
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
    elif args.cmd == "backup":
        sys.exit(backup_now())
    elif args.cmd == "restore":
        sys.exit(restore(args.file, database_url=args.database_url, files_dir=args.files_dir,
                         pause=not args.no_pause, inspect=args.inspect, yes=args.yes))
    elif args.cmd == "restored":
        asyncio.run(restored(args.backup_taken_at))
    elif args.cmd == "demo-job":
        sys.exit(asyncio.run(demo_job()))
    elif args.cmd == "worker-alive":
        sys.exit(0 if asyncio.run(worker_alive()) else 1)


if __name__ == "__main__":
    main()
