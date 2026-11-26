"""``gateway_tick`` (every minute, imported by ``app/worker/main.py``): silent runners' leases expire, so their
tasks go back to the queue from their checkpoints (or to reconciliation once a permit was given).

Apply tasks are not handed out here: the browser channel creates them (``dispatch.queue`` and the worker's
``browser_tick``), and a task blocked for the owner's approval is returned to its runner by
``browser.queue_task`` when the new packet is approved."""

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


async def tick(session: AsyncSession, *, at: datetime | None = None) -> TickReport:
    at = at or common.now()
    report = TickReport()
    report.expired = await tasks.expire_leases(session, at=at)
    await session.commit()
    return report


@queue_app.periodic(cron="* * * * *", periodic_id="gateway_tick")
@queue_app.task(name="gateway_tick", queue=SYSTEM_QUEUE, queueing_lock="gateway_tick", pass_context=False)
async def gateway_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        report = await tick(session)
    if report.expired:
        log.info("gateway tick: expired=%d", len(report.expired))
