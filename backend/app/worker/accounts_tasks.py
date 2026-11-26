"""Periodic portal-account pass: known-early sign-in requests and escalating reminders (imported by the worker)."""

from __future__ import annotations

from app.apply import accounts
from app.core.db import get_sessionmaker
from app.worker.queue import SYSTEM_QUEUE, queue_app


@queue_app.periodic(cron="*/10 * * * *", periodic_id="portal_accounts_tick")
@queue_app.task(name="portal_accounts_tick", queue=SYSTEM_QUEUE, queueing_lock="portal_accounts_tick",
                pass_context=False)
async def portal_accounts_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        await accounts.tick(session)
        await session.commit()
