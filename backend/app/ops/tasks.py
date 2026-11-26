"""Worker task: one periodic ``ops_tick`` (backups, retention, health alerts, digest, notification delivery).

Imported by ``app/worker/main.py`` so Procrastinate registers it. A failure inside any step is logged and
isolated by ``jobs.tick``; the tick itself never raises into the queue.
"""

from __future__ import annotations

import logging

from app.core.db import get_sessionmaker
from app.ops import jobs
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@queue_app.periodic(cron="* * * * *", periodic_id="ops_tick")
@queue_app.task(name="ops_tick", queue=SYSTEM_QUEUE, queueing_lock="ops_tick", pass_context=False)
async def ops_tick(timestamp: int) -> None:
    done = await jobs.tick(get_sessionmaker())
    acted = {k: v for k, v in done.items() if v not in (False, 0, None)}
    if acted:
        log.info("ops tick: %s", acted)
