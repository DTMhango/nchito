"""``gateway_tick`` (every minute, imported by ``app/worker/main.py``): silent runners' leases expire, tasks the
owner has approved go back to their runner, and approved browser packets are handed to the runner queue."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.gateway import common, tasks
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@dataclass
class TickReport:
    expired: dict[UUID, str] = field(default_factory=dict)
    requeued: list[UUID] = field(default_factory=list)
    queued: list[UUID] = field(default_factory=list)


async def tick(session: AsyncSession, *, at: datetime | None = None) -> TickReport:
    at = at or common.now()
    report = TickReport()
    report.expired = await tasks.expire_leases(session, at=at)
    report.requeued = await tasks.requeue_approved(session, at=at)
    report.queued = await tasks.hand_out(session, at=at)
    await session.commit()
    return report


@queue_app.periodic(cron="* * * * *", periodic_id="gateway_tick")
@queue_app.task(name="gateway_tick", queue=SYSTEM_QUEUE, queueing_lock="gateway_tick", pass_context=False)
async def gateway_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        report = await tick(session)
    if report.expired or report.requeued or report.queued:
        log.info("gateway tick: expired=%d requeued=%d queued=%d", len(report.expired), len(report.requeued),
                 len(report.queued))
