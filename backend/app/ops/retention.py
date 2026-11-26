"""Retention beyond roles: old notifications, temporary files, old backups. DESIGN.md 14.

The job-side rules (drop text of below-threshold roles, archive unsubmitted ones) live in
``app.pipeline.orchestrator.run_retention``; ``run_all`` runs both.

Safety: ``PROTECTED_TABLES`` hold duplicate-protection history, the audit, submitted snapshots and
the owner's records. ``run_all`` counts their rows before and after and rolls back, raising
``ProtectedDataError``, if any row count drops. Nothing here deletes from them, and the temp-file
rule only looks inside ``FILES_DIR/tmp``.
"""

from __future__ import annotations

import logging
import shutil
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect.filestore import FileStore
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.models.platform import Notification
from app.models.search import Run, RunKind, RunStatus
from app.ops.backup import TEMP_DIR_NAME, prune_backups

log = logging.getLogger(__name__)

PROTECTED_TABLES = (
    "application", "application_event", "application_packet", "submit_permit", "dispatch_attempt",
    "audit_event", "job", "job_sighting", "assessment", "ledger_entry", "mail_thread", "contact",
    "vault_document", "setting_revision", "config_revision",
)


class ProtectedDataError(RuntimeError):
    pass


async def protected_counts(session: AsyncSession) -> dict[str, int]:
    from sqlalchemy import text

    counts: dict[str, int] = {}
    for table in PROTECTED_TABLES:
        counts[table] = int(await session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)  # noqa: S608
    return counts


def clean_temp_files(files_dir: Path, older_than: datetime) -> int:
    """Delete files under ``files_dir/tmp`` not modified since ``older_than``. Nothing else is touched."""
    root = (files_dir / TEMP_DIR_NAME).resolve()
    if not root.is_dir() or root == files_dir.resolve():
        return 0
    removed = 0
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime, older_than.tzinfo) < older_than:
                path.unlink()
                removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            log.warning("could not remove temporary file %s", path)
    if removed and not any(root.iterdir()):
        shutil.rmtree(root, ignore_errors=True)
    return removed


async def run_ops_retention(session: AsyncSession, *, now: datetime | None = None, dry_run: bool = False,
                            backup_store: FileStore | None = None) -> Counter[str]:
    """Notifications past ``retention.notifications_days``, temp files past ``retention.temp_files_days``,
    backups beyond ``backups.keep``."""
    now = now or utcnow()
    values = await settings_service.values(session)
    counts: Counter[str] = Counter()
    note_cutoff = now - timedelta(days=values["retention.notifications_days"])
    old = select(func.count()).select_from(Notification).where(Notification.created_at < note_cutoff)
    counts["notifications_deleted"] = int(await session.scalar(old) or 0)
    if not dry_run:
        await session.execute(delete(Notification).where(Notification.created_at < note_cutoff))
        counts["temp_files_deleted"] = clean_temp_files(
            get_config().files_dir, now - timedelta(days=values["retention.temp_files_days"]))
        counts["backups_pruned"] = len(await prune_backups(values["backups.keep"], store=backup_store))
    return counts


async def run_all(session: AsyncSession, *, trigger: str = "schedule", dry_run: bool = False,
                  backup_store: FileStore | None = None) -> Run:
    """One retention run: role rules plus the rules above, recorded as a ``Run`` of kind ``retention``."""
    from app.pipeline.orchestrator import run_retention

    now = utcnow()
    run = Run(kind=RunKind.retention, trigger=trigger, dry_run=dry_run, status=RunStatus.running, started_at=now)
    session.add(run)
    await session.flush()
    run_id = run.id
    before = await protected_counts(session)
    counts: Counter[str] = Counter()
    try:
        await run_retention(session, run)  # commits; fills run.counts with the role rules' counts
        counts.update(run.counts)
        counts.update(await run_ops_retention(session, now=now, dry_run=dry_run, backup_store=backup_store))
        after = await protected_counts(session)
        shrunk = {t: (before[t], after[t]) for t in before if after[t] < before[t]}
        if shrunk:
            await session.rollback()
            raise ProtectedDataError(f"retention would have removed protected rows: {shrunk}")
        run.counts = dict(counts)
        run.status, run.finished_at = RunStatus.succeeded, utcnow()
    except Exception as exc:
        await session.rollback()
        run = await session.get(Run, run_id) or run
        run.status, run.finished_at, run.error = RunStatus.failed, utcnow(), f"{type(exc).__name__}: {exc}"[:500]
        await session.commit()
        raise
    await session.commit()
    return run
