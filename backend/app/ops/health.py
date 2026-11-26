"""Health: database reachability, worker heartbeat, version."""

from __future__ import annotations

import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.clock import utcnow
from app.core.config import get_config
from app.models.platform import Notification, Owner, WorkerHeartbeat
from app.models.search import Run, RunKind, RunStatus


class DbHealth(BaseModel):
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


class WorkerHealth(BaseModel):
    ok: bool
    last_beat_at: datetime | None = None
    age_seconds: float | None = None
    workers: int = 0


class Health(BaseModel):
    status: str  # ok | degraded | down
    version: str
    time: datetime
    db: DbHealth
    worker: WorkerHealth


async def check(session: AsyncSession) -> Health:
    started = time.perf_counter()
    try:
        await session.execute(text("SELECT 1"))
        db = DbHealth(ok=True, latency_ms=round((time.perf_counter() - started) * 1000, 2))
    except (SQLAlchemyError, OSError) as exc:
        db = DbHealth(ok=False, error=type(exc).__name__)
        return Health(status="down", version=__version__, time=utcnow(), db=db, worker=WorkerHealth(ok=False))

    beats = (await session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.beat_at.desc()))).all()
    now = utcnow()
    if beats:
        age = (now - beats[0].beat_at).total_seconds()
        worker = WorkerHealth(ok=age <= get_config().worker_stale_after_seconds, last_beat_at=beats[0].beat_at,
                              age_seconds=round(age, 1), workers=len(beats))
    else:
        worker = WorkerHealth(ok=False)
    return Health(status="ok" if worker.ok else "degraded", version=__version__, time=now, db=db, worker=worker)


# ----- detailed health (owner) and alert state --------------------------------------------------

Status = Literal["ok", "warn", "down", "unknown"]


class Component(BaseModel):
    name: str
    status: Status
    detail: str | None = None
    at: datetime | None = None
    value: float | None = None


class ConnectionHealth(BaseModel):
    id: uuid.UUID
    provider: str
    label: str
    enabled: bool
    health: str
    last_checked_at: datetime | None


class QueueDepth(BaseModel):
    waiting: int = 0
    running: int = 0
    failed: int = 0


class DetailedHealth(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    time: datetime
    components: list[Component]
    queue: QueueDepth
    connections: list[ConnectionHealth]
    workers: list[WorkerHealth] = []


class Ready(BaseModel):
    ready: bool
    database: bool
    migrated: bool


def _free_disk_mb(path: Path) -> float | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return round(shutil.disk_usage(probe).free / (1024 * 1024), 1)
    except OSError:
        return None


async def _queue_depth(session: AsyncSession) -> QueueDepth:
    try:
        rows = (await session.execute(text("SELECT status::text, count(*) FROM procrastinate_jobs GROUP BY 1"))).all()
    except SQLAlchemyError:
        await session.rollback()
        return QueueDepth()
    by = {r[0]: int(r[1]) for r in rows}
    return QueueDepth(waiting=by.get("todo", 0), running=by.get("doing", 0), failed=by.get("failed", 0))


async def last_success(session: AsyncSession, kind: RunKind) -> datetime | None:
    return await session.scalar(select(func.max(Run.finished_at)).where(
        Run.kind == kind, Run.status.in_((RunStatus.succeeded, RunStatus.partial))))


def _age_component(name: str, last: datetime | None, now: datetime, stale_hours: int, never: str,
                   *, expected: bool, since: datetime | None) -> Component:
    """``since`` is when the instance was set up: nothing is overdue before one full interval has passed."""
    if last is None:
        overdue = expected and since is not None and (now - since).total_seconds() / 3600 > stale_hours
        return Component(name=name, status="warn" if overdue else "unknown", detail=never)
    hours = (now - last).total_seconds() / 3600
    status: Status = "ok" if hours <= stale_hours else "warn"
    return Component(name=name, status=status, at=last, value=round(hours, 1),
                     detail=None if status == "ok" else f"last success {hours:.0f} h ago (limit {stale_hours} h)")


async def detailed(session: AsyncSession, now: datetime | None = None) -> DetailedHealth:
    """Everything the owner's health panel and the alert monitor need. Never raises on a missing piece."""
    from app.core.settings import service as settings_service
    from app.models.platform import Connection
    from app.models.search import Schedule

    now = now or utcnow()
    basic = await check(session)
    since = await session.scalar(select(func.min(Owner.created_at)))
    values = await settings_service.values(session)
    components = [Component(name="database", status="ok" if basic.db.ok else "down", value=basic.db.latency_ms,
                            detail=basic.db.error)]
    stale_after = get_config().worker_stale_after_seconds
    if basic.worker.ok:
        worker_detail = None
    elif basic.worker.last_beat_at:
        worker_detail = f"no heartbeat for over {stale_after} s"
    else:
        worker_detail = "no worker has reported"
    components.append(Component(name="worker", status="ok" if basic.worker.ok else "down",
                                at=basic.worker.last_beat_at, value=basic.worker.age_seconds, detail=worker_detail))

    has_schedule = bool(await session.scalar(select(func.count()).select_from(Schedule).where(
        Schedule.enabled.is_(True), Schedule.kind == RunKind.sweep)))
    components.append(_age_component("sweep", await last_success(session, RunKind.sweep), now,
                                     values["health.sweep_stale_hours"], "no sweep has succeeded yet",
                                     expected=has_schedule, since=since))
    components.append(_age_component("backup", await last_success(session, RunKind.backup), now,
                                     values["health.backup_stale_hours"], "no backup has succeeded yet",
                                     expected=True, since=since))
    free = _free_disk_mb(get_config().files_dir)
    low = values["health.disk_min_free_mb"]
    components.append(Component(
        name="disk", status="unknown" if free is None else "ok" if free >= low else "warn", value=free,
        detail=None if free is None or free >= low else f"{free:.0f} MB free (limit {low} MB)"))

    conns = (await session.scalars(select(Connection).order_by(Connection.provider, Connection.created_at))).all()
    failing = [c for c in conns if c.enabled and c.health == "failing"]
    components.append(Component(
        name="connections", status="warn" if failing else "ok",
        detail=", ".join(f"{c.provider.value} ({c.label})" for c in failing) or None))

    status: Literal["ok", "degraded", "down"] = "down" if not basic.db.ok else (
        "ok" if all(c.status in ("ok", "unknown") for c in components) else "degraded")
    beats = (await session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.beat_at.desc()))).all()
    workers = [WorkerHealth(ok=(now - b.beat_at).total_seconds() <= stale_after, last_beat_at=b.beat_at,
                            age_seconds=round((now - b.beat_at).total_seconds(), 1), workers=1) for b in beats]
    return DetailedHealth(
        status=status, version=__version__, time=now, components=components, queue=await _queue_depth(session),
        workers=workers, connections=[ConnectionHealth(
            id=c.id, provider=c.provider.value, label=c.label, enabled=c.enabled, health=c.health,
            last_checked_at=c.last_checked_at) for c in conns])


async def ready(session: AsyncSession) -> Ready:
    """Readiness: the database answers and has been migrated. A stale worker does not make the web tier unready."""
    try:
        await session.execute(text("SELECT 1"))
        migrated = bool(await session.scalar(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")))
    except (SQLAlchemyError, OSError):
        return Ready(ready=False, database=False, migrated=False)
    return Ready(ready=migrated, database=True, migrated=migrated)


# ----- alerts: one per persistent failure, one on recovery -------------------------------------


async def alert_transitions(session: AsyncSession, report: DetailedHealth) -> list[str]:
    """Create health notifications for components that changed state since the last alert about them.

    A component is *failing* when its status is ``down`` or ``warn``. The previous state is read from the
    newest ``health`` notification for that component, so a persistent failure alerts once and its recovery
    alerts once; a restart does not repeat either.
    """
    from app.ops.notifications import notify

    sent: list[str] = []
    for comp in report.components:
        if comp.status == "unknown":
            continue
        failing = comp.status in ("down", "warn")
        last = await session.scalar(select(Notification).where(
            Notification.kind == "health", Notification.payload["component"].astext == comp.name
        ).order_by(Notification.created_at.desc()).limit(1))
        was_failing = last is not None and last.payload.get("state") == "failing"
        if failing == was_failing or (not failing and last is None):
            continue
        state = "failing" if failing else "recovered"
        name = comp.name.capitalize()
        title = f"{name} needs attention" if failing else f"{name} is back to normal"
        key = f"health:{comp.name}:{state}:{report.time.strftime('%Y%m%d%H%M')}"
        if await notify(session, kind="health", key=key, title=title, body=comp.detail if failing else None,
                        link="/settings", payload={"component": comp.name, "state": state}):
            sent.append(key)
    return sent
