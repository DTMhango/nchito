"""The task loop: next_task, work it, hand it back, repeat. Heartbeat and graceful shutdown.

Lease semantics (the contract has no release tool): a runner that stops saves a checkpoint and
stops pinging, and the server returns the stale claim to the queue with that checkpoint. When
the gateway lists an optional ``release_task`` tool, it is called as well.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Any

from .browser import BrowserSession
from .budget import Budget, BudgetExhausted
from .config import RunnerConfig
from .driver import Driver
from .gateway import Gateway, GatewayError
from .guard import Guard
from .toolbox import TaskState, Toolbox

log = logging.getLogger("nchito_runner")

DAY_WAIT_SECONDS = 300.0


class Runner:
    def __init__(self, cfg: RunnerConfig, gateway: Gateway, driver: Driver, budget: Budget):
        self.cfg = cfg
        self.gw = gateway
        self.driver = driver
        self.budget = budget
        self.stop = asyncio.Event()

    # ----- one task ---------------------------------------------------------------------------
    async def run_one(self) -> str:
        """Returns 'idle', 'day_budget', or 'worked'."""
        try:
            self.budget.check_day()
        except BudgetExhausted as exc:
            log.warning("runner paused for the day: %s", exc)
            return "day_budget"
        task = await self.gw.call("next_task", {"kinds": ["apply"]})
        if not task.get("task_id"):
            return "idle"
        await self._work(task)
        return "worked"

    async def _work(self, task: dict[str, Any]) -> None:
        task_id = task["task_id"]
        cp = task.get("checkpoint") or {}
        if (cp.get("data") or {}).get("submit_attempted"):
            # A crash after the submit click: the form may have gone through. Never try again.
            await self.gw.call("report_result", {"task_id": task_id, "outcome": "uncertain",
                                                 "detail": "Runner restarted after a submit was attempted; not retried."})
            log.warning("task %s resumed after a submit attempt: reported uncertain", task_id)
            return
        rules = task.get("rules") or {}
        domain = rules.get("stay_on_domain")
        if not domain:
            await self.gw.call("report_result", {"task_id": task_id, "outcome": "failed",
                                                 "detail": "Task carried no stay_on_domain rule."})
            return
        guard = Guard([domain], permit_safety=timedelta(seconds=self.cfg.permit_safety_seconds))
        browser = BrowserSession(guard, self.cfg.profile_dir, self.cfg.state_dir / "evidence", headless=self.cfg.headless)
        state = TaskState(task_id=task_id, posting_url=task.get("posting_url") or "",
                          max_steps=int(rules.get("max_steps") or 0) or 1, checkpoint=cp or None)
        self.budget.start_task()
        box: Toolbox | None = None
        heartbeat: asyncio.Task[None] | None = None
        reason = "agent ended without a result"
        try:
            await browser.start()
            box = Toolbox(state, self.gw, browser, guard, self.budget)
            heartbeat = asyncio.create_task(self._heartbeat())
            run = asyncio.create_task(self.driver.run(box, task, self.budget))
            stopper = asyncio.create_task(self.stop.wait())
            done, _ = await asyncio.wait({run, stopper}, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if run not in done:
                run.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run
                reason = "runner shutting down"
            elif run.exception():
                reason = f"agent error: {type(run.exception()).__name__}: {str(run.exception())[:300]}"
                log.error("task %s: %s", task_id, reason)
            try:
                self.budget.check()
            except BudgetExhausted as exc:
                state.budget_stop = state.budget_stop or exc
                reason = str(exc)
        except Exception as exc:
            reason = f"runner error: {type(exc).__name__}: {str(exc)[:300]}"
            log.exception("task %s failed", task_id)
        finally:
            if heartbeat:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await heartbeat
            if box:
                if state.budget_stop:
                    reason = str(state.budget_stop)
                await box.close_out(reason=reason, shutting_down=self.stop.is_set())
                await box.aclose()
            else:  # the browser never started: nothing was entered, nothing to resume
                with contextlib.suppress(GatewayError):
                    await self.gw.call("report_result", {"task_id": task_id, "outcome": "failed", "detail": reason[:500]})
            await browser.close()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.heartbeat_seconds)
            try:
                await self.gw.ping()
            except Exception as exc:
                log.warning("heartbeat failed: %s", exc)

    # ----- forever ------------------------------------------------------------------------------
    async def run_forever(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            try:
                status = await self.run_one()
                backoff = 1.0
            except Exception as exc:
                log.error("loop error: %s", exc)
                status = "error"
            if status == "worked":
                continue
            wait = {"day_budget": DAY_WAIT_SECONDS, "error": min(backoff, 60.0)}.get(status, self.cfg.poll_seconds)
            if status == "error":
                backoff *= 2
            if status == "day_budget":
                with contextlib.suppress(Exception):
                    await self.gw.ping()  # stay visible as "alive, out of budget"
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop.wait(), timeout=wait)
        with contextlib.suppress(Exception):
            await self.gw.close()

