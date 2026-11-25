"""Worker heartbeat: one row per worker process, refreshed on an interval. /api/health reads it."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.clock import Clock, SystemClock
from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.models.platform import WorkerHeartbeat

log = logging.getLogger(__name__)


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def beat(session: AsyncSession, name: str, clock: Clock) -> None:
    now = clock.now()
    stmt = insert(WorkerHeartbeat).values(worker_name=name, beat_at=now, version=__version__, info={})
    stmt = stmt.on_conflict_do_update(index_elements=[WorkerHeartbeat.worker_name],
                                      set_={"beat_at": now, "version": __version__, "updated_at": now})
    await session.execute(stmt)


async def heartbeat_loop(stop: asyncio.Event, clock: Clock | None = None) -> None:
    clock = clock or SystemClock()
    name = worker_name()
    interval = get_config().worker_heartbeat_seconds
    while not stop.is_set():
        try:
            async with get_sessionmaker()() as session:
                await beat(session, name, clock)
                await session.commit()
        except Exception:  # keep beating through transient database errors
            log.exception("heartbeat failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
