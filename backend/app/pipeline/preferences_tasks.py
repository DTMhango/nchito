"""Queue task for preference learning: the periodic pass that turns new feedback into suggestions.

Hourly; each campaign is analysed at most once per ``preferences.analysis_every_hours`` and only when
its evidence changed (``preferences.analyse_due``). Suggestions are proposals: nothing is applied.
"""

from __future__ import annotations

import logging

from app.core.db import get_sessionmaker
from app.pipeline import preferences
from app.worker.queue import SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


@queue_app.periodic(cron="17 * * * *", periodic_id="preferences_tick")
@queue_app.task(name="preferences_tick", queue=SYSTEM_QUEUE, queueing_lock="preferences_tick", pass_context=False)
async def preferences_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        done = await preferences.analyse_due(session)
        await session.commit()
    if done:
        log.info("preferences: analysed %d campaign(s)", len(done))
