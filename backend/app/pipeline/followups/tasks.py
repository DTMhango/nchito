"""Worker task: the follow-up tick (every five minutes, system queue). Resumes campaigns paused until a date
that has come, then runs the follow-up due list (reminders, snooze wake-ups, the automatic follow-up when on).
Imported by ``app.worker.queue`` so it registers on ``queue_app``."""

from __future__ import annotations

import logging

from app.core.db import get_sessionmaker
from app.llm.service import LLMService
from app.pipeline.followups import campaigns, due
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@queue_app.periodic(cron="*/5 * * * *", periodic_id="followups_tick")
@queue_app.task(name="followups_tick", queue=SYSTEM_QUEUE, queueing_lock="followups_tick", pass_context=False)
async def followups_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        resumed = await campaigns.resume_due(session)
        await session.commit()
        report = await due.tick(session, LLMService())
        await session.commit()
    if resumed or any(report.values()):
        log.info("follow-ups: resumed %d campaign(s); %s", len(resumed), report)
