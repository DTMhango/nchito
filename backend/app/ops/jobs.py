"""The scheduled work of the ops stream: backups, retention, digest, delivery, health alerts.

Everything here is idempotent and safe to call every minute from ``ops_tick``: "is it due" looks at
the last recorded ``Run`` of that kind (and ``backups.cron`` / ``retention.cron`` in the owner's
time zone), so a restart or two workers do not repeat work.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import onedrive_records, records
from app.connect.filestore import FileStore
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.platform import Owner
from app.models.search import Run, RunKind, RunStatus
from app.ops import backup as backup_mod
from app.ops import digest, health, notifications, retention

log = logging.getLogger(__name__)


async def _baseline(session: AsyncSession, kind: RunKind) -> datetime | None:
    last = await session.scalar(select(func.max(Run.started_at)).where(Run.kind == kind))
    return last or await session.scalar(select(func.min(Owner.created_at)))


def cron_due(cron: str, tz: ZoneInfo, now: datetime, baseline: datetime | None) -> bool:
    """True when a fire time of ``cron`` lies after ``baseline`` and not after ``now``."""
    if baseline is None:
        return False
    prev: datetime = croniter(cron, now.astimezone(tz)).get_prev(datetime)
    return prev.astimezone(ZoneInfo("UTC")) > baseline


async def backup_due(session: AsyncSession, now: datetime) -> bool:
    values = await settings_service.values(session)
    return cron_due(values["backups.cron"], ZoneInfo(values["general.timezone"]), now,
                    await _baseline(session, RunKind.backup))


async def retention_due(session: AsyncSession, now: datetime) -> bool:
    values = await settings_service.values(session)
    return cron_due(values["retention.cron"], ZoneInfo(values["general.timezone"]), now,
                    await _baseline(session, RunKind.retention))


async def remote_store(session: AsyncSession, target: str) -> tuple[FileStore | None, str | None]:
    """The store a backup is copied to, and a warning if the target cannot be used."""
    if target == "gdrive":
        try:
            return await records.drive_store(session), None
        except Exception as exc:
            return None, f"Google Drive unavailable: {type(exc).__name__}: {exc}"[:300]
    if target == "onedrive":
        try:
            return await onedrive_records.onedrive_store(session), None
        except Exception as exc:
            return None, f"OneDrive unavailable: {type(exc).__name__}: {exc}"[:300]
    if target == "s3":
        try:
            return await records.first_s3_store(session), None
        except Exception as exc:
            return None, f"S3 storage unavailable: {type(exc).__name__}: {exc}"[:300]
    return None, None


async def run_backup_job(session: AsyncSession, *, trigger: str = "schedule", actor: str = "system"
                         ) -> tuple[Run, backup_mod.BackupInfo | None]:
    """One backup: local archive always, plus the configured remote. Recorded as a ``Run`` and in the audit.
    A failure is recorded and raised as a ``failed`` run (and a notification), never silently lost."""
    values = await settings_service.values(session)
    run = Run(kind=RunKind.backup, trigger=trigger, status=RunStatus.running, started_at=utcnow())
    session.add(run)
    await session.commit()
    store, warning = await remote_store(session, values["backups.target"])
    info: backup_mod.BackupInfo | None = None
    try:
        info = await backup_mod.create_backup(store=store, remote_label=values["backups.target"] if store else None)
        pruned = await backup_mod.prune_backups(values["backups.keep"], store=store)
        problem = info.remote_error or warning
        run.status = RunStatus.partial if problem else RunStatus.succeeded
        run.error = problem
        run.counts = {"size_bytes": info.size_bytes, "files": info.files, "pruned": len(pruned)}
        await audit.record(session, actor=actor, action="backup.completed", subject_type="backup",
                           subject_id=info.id, detail={"size_bytes": info.size_bytes, "remote": info.remote_target,
                                                       "remote_error": problem, "pruned": pruned})
    except Exception as exc:
        run.status, run.error = RunStatus.failed, f"{type(exc).__name__}: {exc}"[:500]
        await audit.record(session, actor=actor, action="backup.failed", subject_type="backup",
                           detail={"error": run.error})
        await notifications.notify(session, kind="backup", key=f"backup-failed:{run.id}", title="Backup failed",
                                   body=run.error, link="/settings", payload={"run_id": str(run.id)})
    run.finished_at = utcnow()
    await session.commit()
    return run, info


async def run_retention_job(session: AsyncSession, *, trigger: str = "schedule") -> Run:
    values = await settings_service.values(session)
    store, _ = await remote_store(session, values["backups.target"])
    return await retention.run_all(session, trigger=trigger, backup_store=store)


async def tick(session_factory, now: datetime | None = None) -> dict[str, object]:
    """One pass of everything scheduled. Each step has its own session and failure handling."""
    now = now or utcnow()
    done: dict[str, object] = {}

    async def step(name: str, fn) -> None:
        try:
            async with session_factory() as session:
                done[name] = await fn(session)
                await session.commit()
        except Exception:
            log.exception("ops step %s failed", name)
            done[name] = "error"

    async def collect(s: AsyncSession) -> int:
        return (await notifications.collect(s, now)).created

    async def digest_step(s: AsyncSession) -> bool:
        return await digest.send_digest_if_due(s, now)

    async def health_step(s: AsyncSession) -> int:
        return len(await health.alert_transitions(s, await health.detailed(s, now)))

    async def backup_step(s: AsyncSession) -> bool:
        if not await backup_due(s, now):
            return False
        await run_backup_job(s)
        return True

    async def retention_step(s: AsyncSession) -> bool:
        if not await retention_due(s, now):
            return False
        await run_retention_job(s)
        return True

    async def calendar_step(s: AsyncSession) -> int:
        from app.pipeline import events, events_google

        due = await events.run_due(s, now)
        await events_google.sync_pending(s)
        return due.reminders + due.debriefs

    async def deliver(s: AsyncSession) -> int:
        return (await notifications.deliver_due(s, now)).sent

    await step("backup", backup_step)
    await step("retention", retention_step)
    await step("health", health_step)
    await step("collect", collect)
    await step("calendar", calendar_step)
    await step("digest", digest_step)
    await step("deliver", deliver)  # last, so what the steps above created goes out in the same minute
    return done
