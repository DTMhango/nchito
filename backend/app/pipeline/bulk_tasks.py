"""Queue task for bulk operations (Procrastinate, queue ``runs``).

One operation runs at a time per operation id (the lock), item by item; it is idempotent, so a retried
task finishes what is left and never repeats a finished item (``app.pipeline.bulk.execute``).
"""

from __future__ import annotations

import logging
import uuid

import procrastinate

from app.core.db import get_sessionmaker
from app.pipeline import bulk
from app.worker.queue import RUNS_QUEUE, queue_app

log = logging.getLogger(__name__)


async def enqueue(operation_id: uuid.UUID) -> None:
    """Defer the run; call after the transaction that queued the operation has committed."""
    await run_bulk_operation.configure(lock=f"bulk:{operation_id}", queue=RUNS_QUEUE).defer_async(
        operation_id=str(operation_id))


@queue_app.task(name="run_bulk_operation", queue=RUNS_QUEUE,
                retry=procrastinate.RetryStrategy(max_attempts=3, exponential_wait=10))
async def run_bulk_operation(operation_id: str) -> None:
    async with get_sessionmaker()() as session:
        op = await bulk.execute(session, uuid.UUID(operation_id))
        log.info("bulk operation %s: %s", operation_id, op.status)
