"""Worker entrypoint: Procrastinate worker (runs, periodic scheduler tick) plus the heartbeat."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.core.db import dispose_engine
from app.pipeline import orchestrator
from app.worker.heartbeat import heartbeat_loop
from app.worker.queue import RUNS_QUEUE, SYSTEM_QUEUE, queue_app

log = logging.getLogger(__name__)


async def run_worker() -> None:
    orchestrator.install()  # sweep, expiry_check and retention handlers (the worker process only)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)

    beat_task = asyncio.create_task(heartbeat_loop(stop), name="heartbeat")
    async with queue_app.open_async():
        worker = asyncio.create_task(
            queue_app.run_worker_async(queues=[SYSTEM_QUEUE, RUNS_QUEUE], concurrency=4, install_signal_handlers=False),
            name="procrastinate",
        )
        stopper = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({worker, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if worker not in done:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        else:
            worker.result()
    stop.set()
    await beat_task
    await dispose_engine()
