"""Queue tasks for the interview pack (Procrastinate).

``interview_generate`` builds one pack's pending sections under the lock ``interview:<pack id>`` and the
queueing lock of the same name, so a pack is never queued or built twice at once; processing is
idempotent per generation (``service.process``). ``interview_tick`` makes the automatic offers, defers
packs queued by an accepted offer, and resumes packs paused for budget once the cap allows.
"""

from __future__ import annotations

import contextlib
import logging
import uuid

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.llm.service import LLMService
from app.models.applications import InterviewPack, InterviewPackStatus
from app.pipeline.interview import offer, service
from app.worker.queue import RUNS_QUEUE, SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


async def enqueue(pack: InterviewPack) -> None:
    """Defer generation of ``pack``; call after the transaction that queued it commits."""
    lock = f"interview:{pack.id}"
    with contextlib.suppress(AlreadyEnqueued):  # already waiting: processing picks up the latest request
        await interview_generate.configure(lock=lock, queueing_lock=lock, queue=RUNS_QUEUE).defer_async(
            pack_id=str(pack.id))


@queue_app.task(name="interview_generate", queue=RUNS_QUEUE,
                retry=procrastinate.RetryStrategy(max_attempts=3, exponential_wait=10))
async def interview_generate(pack_id: str) -> None:
    async with get_sessionmaker()() as session:
        status = await service.process(session, LLMService(), uuid.UUID(pack_id))
        await session.commit()
    log.info("interview pack %s: %s", pack_id, status.value)


@queue_app.periodic(cron="*/5 * * * *", periodic_id="interview_tick")
@queue_app.task(name="interview_tick", queue=SYSTEM_QUEUE, queueing_lock="interview_tick", pass_context=False)
async def interview_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        await offer.scan(session)
        await session.commit()
        queued = list((await session.scalars(select(InterviewPack).where(
            InterviewPack.status == InterviewPackStatus.queued))).all())
        for pack in queued:
            await enqueue(pack)
        resumed = await service.resume_paused(session, enqueue)
    if queued or resumed:
        log.info("interview: deferred %d pack(s), resumed %d paused for budget", len(queued), len(resumed))
