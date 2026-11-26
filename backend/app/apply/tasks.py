"""Worker tasks for dispatch and reconciliation (imported by ``app/worker/main.py``).

``apply_tick`` runs every minute: stale permit claims are given back, sends left in flight by a stopped
worker become uncertain, approved packets for server-sent channels are queued, due sends go out, and
uncertain sends are reconciled. ``apply_dispatch`` sends one attempt now (deferred by other code for
lower latency); both are safe to run at once, since an attempt is claimed atomically and never resent.
Neither task retries on its own: a crashed send is never repeated by the queue.
"""

from __future__ import annotations

import logging
import uuid

from app.apply import dispatch
from app.core.db import get_sessionmaker
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@queue_app.periodic(cron="* * * * *", periodic_id="apply_tick")
@queue_app.task(name="apply_tick", queue=SYSTEM_QUEUE, queueing_lock="apply_tick", pass_context=False)
async def apply_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        report = await dispatch.tick(session)
    if report.sent or report.reconciled or report.uncertain:
        log.info("apply tick: sent=%s reconciled=%s uncertain=%d", report.sent, report.reconciled,
                 len(report.uncertain))


@queue_app.task(name="apply_dispatch", queue=SYSTEM_QUEUE, pass_context=False)
async def apply_dispatch(attempt_id: str) -> None:
    async with get_sessionmaker()() as session:
        await dispatch.run(session, uuid.UUID(attempt_id))
