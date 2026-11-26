"""Procrastinate app and tasks (queue on PostgreSQL; no Redis)."""

from __future__ import annotations

import logging
import uuid

import procrastinate

from app.core.clock import SystemClock, utcnow
from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.core.events import publish
from app.models.search import Run, RunStatus
from app.pipeline.capture import process_capture as run_capture
from app.pipeline.runs import handler_for
from app.worker.scheduler import tick

log = logging.getLogger(__name__)

RUNS_QUEUE = "runs"
SYSTEM_QUEUE = "system"

queue_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_config().libpq_url),
)


async def enqueue_run(run: Run) -> None:
    """Defer ``run_pipeline`` for a run. Sweeps share one lock so they run one at a time."""
    lock = "sweep" if run.kind.value == "sweep" else f"run:{run.id}"
    await run_pipeline.configure(lock=lock, queue=RUNS_QUEUE).defer_async(run_id=str(run.id))


@queue_app.task(name="run_pipeline", queue=RUNS_QUEUE, retry=procrastinate.RetryStrategy(max_attempts=3,
                                                                                        exponential_wait=10))
async def run_pipeline(run_id: str) -> None:
    async with get_sessionmaker()() as session:
        run = await session.get(Run, uuid.UUID(run_id), with_for_update=True)
        if run is None:
            log.warning("run %s not found (enqueue transaction rolled back?)", run_id)
            return
        if run.status not in (RunStatus.queued, RunStatus.running):
            log.info("run %s already %s", run_id, run.status)
            return
        handler = handler_for(run.kind)
        if handler is None:
            run.status = RunStatus.skipped
            run.error = f"no handler registered for '{run.kind.value}' runs in this build"
            run.finished_at = utcnow()
            await publish(session, "run.finished", {"run_id": run_id, "status": run.status.value})
            await session.commit()
            return
        run.status = RunStatus.running
        run.started_at = run.started_at or utcnow()
        await publish(session, "run.started", {"run_id": run_id})
        await session.commit()
        try:
            status = await handler(session, run)
        except Exception as exc:
            await session.rollback()
            run = await session.get(Run, uuid.UUID(run_id))
            assert run is not None
            run.status = RunStatus.failed
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
            run.finished_at = utcnow()
            await publish(session, "run.finished", {"run_id": run_id, "status": "failed"})
            await session.commit()
            raise
        run.status = status
        run.finished_at = utcnow()
        await publish(session, "run.finished", {"run_id": run_id, "status": status.value})
        await session.commit()


async def enqueue_capture(job_id: uuid.UUID) -> None:
    """Defer ``process_capture`` for a captured stub (call after the capture transaction commits)."""
    await process_capture.configure(queue=RUNS_QUEUE, lock=f"capture:{job_id}").defer_async(job_id=str(job_id))


@queue_app.task(name="process_capture", queue=RUNS_QUEUE, retry=procrastinate.RetryStrategy(max_attempts=3,
                                                                                            exponential_wait=10))
async def process_capture(job_id: str) -> None:
    async with get_sessionmaker()() as session:
        result = await run_capture(session, uuid.UUID(job_id))
        if result is not None and result.error:
            log.info("capture %s kept as a stub: %s", job_id, result.error)
        await session.commit()


@queue_app.periodic(cron="* * * * *", periodic_id="scheduler_tick")
@queue_app.task(name="scheduler_tick", queue=SYSTEM_QUEUE, queueing_lock="scheduler_tick", pass_context=False)
async def scheduler_tick(timestamp: int) -> None:
    async with get_sessionmaker()() as session:
        result = await tick(session, SystemClock(), enqueue_run)
        await session.commit()
        from app.pipeline.orchestrator import resume_paused

        resumed = await resume_paused(session, enqueue_run)  # runs paused for budget, once the cap allows
    if resumed:
        log.info("tick: resumed %d run(s) paused for budget", len(resumed))
    if result.enqueued or result.skipped_overlap or result.skipped_missed:
        log.info("tick: enqueued=%d overlap=%d missed=%d", len(result.enqueued), len(result.skipped_overlap),
                 len(result.skipped_missed))


# Stream task modules register themselves on ``queue_app`` when imported.
from app.pipeline import bulk_tasks as _bulk_tasks  # noqa: E402, F401
from app.pipeline.interview import tasks as _interview_tasks  # noqa: E402, F401
from app.pipeline.tailoring import tasks as _tailoring_tasks  # noqa: E402, F401
