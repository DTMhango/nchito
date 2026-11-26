"""Queue tasks for tailoring (Procrastinate, queue ``runs``).

``tailor_application`` processes one request under the lock ``tailor:<application id>``, so two
requests for one application never run at once; processing is idempotent per request (see
``service.process``). ``tailoring_resume`` re-queues requests paused for budget once the cap allows.
Runs call :func:`tailor` to request and queue tailoring for an application in their own transaction.
"""

from __future__ import annotations

import logging
import uuid

import procrastinate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.llm.client import LLMClient
from app.llm.service import LLMService
from app.models.applications import Application, TailoringRequest, TailoringStatus
from app.pipeline.tailoring import service
from app.worker.queue import RUNS_QUEUE, SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


def client_for(req: TailoringRequest) -> LLMClient:
    return LLMService().for_run(req.run_id)


async def enqueue(req: TailoringRequest) -> None:
    """Defer processing of ``req``; call after the transaction that created it commits."""
    await tailor_application.configure(lock=f"tailor:{req.application_id}", queue=RUNS_QUEUE).defer_async(
        request_id=str(req.id))


async def tailor(session: AsyncSession, application_id: uuid.UUID, *, actor: str = "system",
                 run_id: uuid.UUID | None = None) -> tuple[TailoringRequest, bool]:
    """For runs: request tailoring for one application. The caller commits, then calls :func:`enqueue`
    when the second value is ``True``."""
    app = await session.get(Application, application_id, with_for_update=True)
    if app is None:
        raise service.TailoringError("application not found", 404)
    return await service.request(session, app, actor=actor, run_id=run_id)


@queue_app.task(name="tailor_application", queue=RUNS_QUEUE,
                retry=procrastinate.RetryStrategy(max_attempts=3, exponential_wait=10))
async def tailor_application(request_id: str) -> None:
    async with get_sessionmaker()() as session:
        req = await session.get(TailoringRequest, uuid.UUID(request_id))
        if req is None:
            log.warning("tailoring request %s not found (enqueue transaction rolled back?)", request_id)
            return
        status = await service.process(session, client_for(req), req.id)
        await session.commit()
        if status == TailoringStatus.done:
            from app.pipeline import advance  # render, pack, then the approval policy

            await advance.after_tailored(session, req.application_id)
            await session.commit()
    log.info("tailoring request %s: %s", request_id, status.value)


@queue_app.periodic(cron="*/5 * * * *", periodic_id="tailoring_resume")
@queue_app.task(name="tailoring_resume", queue=SYSTEM_QUEUE, queueing_lock="tailoring_resume", pass_context=False)
async def tailoring_resume(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        resumed = await service.resume_paused(session, enqueue)
    if resumed:
        log.info("tailoring: resumed %d request(s) paused for budget", len(resumed))
