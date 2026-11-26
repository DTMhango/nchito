"""Periodic tasks for browser applications and posting change alerts (imported by the worker).

``browser_tick`` queues runner tasks for approved browser packets and withdraws tasks no runner claimed in time.
It never takes a permit or sends: that happens when a runner reaches Submit (``apply/channels/browser.py``).
``posting_changes_scan`` rechecks the watched roles that are due (``tracking.change_*`` settings); a role that
cannot be read is recorded ``unknown``, never ``closed`` (``pipeline/changes.py``).
"""

from __future__ import annotations

import logging

from app.apply.channels import browser
from app.core.db import get_sessionmaker
from app.pipeline import changes, orchestrator, scoring
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@queue_app.periodic(cron="*/5 * * * *", periodic_id="browser_tick")
@queue_app.task(name="browser_tick", queue=SYSTEM_QUEUE, queueing_lock="browser_tick", pass_context=False)
async def browser_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        expired = await browser.expire_stale_tasks(session)
        await session.commit()
        queued = await browser.queue_approved_tasks(session)
    if expired or queued:
        log.info("browser tick: queued=%d expired=%d", len(queued), len(expired))


@queue_app.periodic(cron="*/15 * * * *", periodic_id="posting_changes_scan")
@queue_app.task(name="posting_changes_scan", queue=SYSTEM_QUEUE, queueing_lock="posting_changes_scan",
                pass_context=False)
async def posting_changes_scan(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        factory = orchestrator.DEPS.llm_factory
        llm = await factory(session, None) if factory is not None else await scoring.client_for(session)
        report = await changes.scan(session, llm=llm)
    if report.scanned or report.unknown:
        log.info("posting changes: scanned=%d changed=%d closed=%d unknown=%d", report.scanned, len(report.changed),
                 len(report.closed), len(report.unknown))
