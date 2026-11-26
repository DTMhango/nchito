"""Periodic mailbox check (imported by the worker). The task runs every minute; each connection is read
only when ``mail.check_interval_minutes`` has passed since its last check."""

from __future__ import annotations

import logging

from app.connect.mail_sync import run_due_checks
from app.core.db import get_sessionmaker
from app.llm.deps import llm_service
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@queue_app.periodic(cron="* * * * *", periodic_id="mail_check")
@queue_app.task(name="mail_check", queue=SYSTEM_QUEUE, queueing_lock="mail_check", pass_context=False)
async def mail_check(timestamp: int) -> None:
    summary = await run_due_checks(get_sessionmaker(), llm_service())
    if summary.checked or summary.failed:
        log.info("mail check: checked=%d failed=%d", summary.checked, summary.failed)
