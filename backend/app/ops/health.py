"""Health: database reachability, worker heartbeat, version."""

from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.clock import utcnow
from app.core.config import get_config
from app.models.platform import WorkerHeartbeat


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
