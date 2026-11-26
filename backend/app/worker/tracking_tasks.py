"""Periodic tracking tasks: follow-up reminders and stale pending actions (imported by the worker)."""

from __future__ import annotations

from app.apply.reminders import create_follow_up_reminders, remind_stale_pending
from app.core.db import get_sessionmaker
from app.worker.queue import SYSTEM_QUEUE, queue_app


@queue_app.periodic(cron="*/30 * * * *", periodic_id="tracking_reminders")
@queue_app.task(name="tracking_reminders", queue=SYSTEM_QUEUE, queueing_lock="tracking_reminders",
                pass_context=False)
async def tracking_reminders(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        await create_follow_up_reminders(session)
        await remind_stale_pending(session)
        await session.commit()
