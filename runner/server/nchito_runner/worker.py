"""The task loop: owner's settings, next_task, work it, hand it back, repeat. Heartbeat and graceful shutdown.

Before every claim the runner reads ``get_runner_config``: a runner the owner switched off (or a suspended one)
claims nothing, and the owner's caps apply under this deployment's ceiling. A task the runner stops working
without a result (clean shutdown, day budget, a rehearsal) is given back with ``release_task`` and resumes from
its checkpoint; a task with a submit click is reported uncertain, never retried. The heartbeat is an MCP
``ping`` (it updates the runner's last-seen); the task's lease is kept by the tool calls on it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from .browser import BrowserSession
from .budget import Budget, BudgetExhausted, Caps
from .config import RunnerConfig
from .driver import Driver
from .gateway import Gateway, GatewayError
from .guard import Guard
from .toolbox import DEFAULT_EVIDENCE_MAX_BYTES, TaskState, Toolbox

log = logging.getLogger("nchito_runner")

DAY_WAIT_SECONDS = 300.0
MINOR_PER_MAJOR = {"USD": 100}  # the Agent SDK reports cost in USD; other ledger currencies cannot be compared


def owner_caps(server: dict[str, Any], ceiling: Caps) -> Caps:
    """The owner's caps from ``get_runner_config``. Money caps apply when the ledger is in USD (what the SDK
    reports); otherwise only the token caps can be compared and the money ceiling stays the environment's."""
    per = MINOR_PER_MAJOR.get(str(server.get("currency") or "").upper())
    task_cost = int(server["task_cap_minor"]) / per if per else ceiling.task_cost_usd
    day_cost = int(server["day_cap_minor"]) / per if per else ceiling.day_cost_usd
    return Caps(task_cost, day_cost, int(server["task_max_tokens"]), int(server["day_max_tokens"]))


class Runner:
    def __init__(self, cfg: RunnerConfig, gateway: Gateway, driver: Driver, budget: Budget, *,
                 clock: Callable[[], datetime] | None = None):
        self.cfg = cfg
        self.gw = gateway
        self.driver = driver
        self.budget = budget
        self.clock = clock  # the permit clock (tests align it with the server's)
        self.stop = asyncio.Event()
        self.server: dict[str, Any] = {}
        self._warned_currency = False

    # ----- owner's settings ---------------------------------------------------------------------
    async def refresh_config(self) -> dict[str, Any]:
        self.server = await self.gw.call("get_runner_config", {})
        if self.server.get("currency", "").upper() not in MINOR_PER_MAJOR and not self._warned_currency:
            log.warning("budget currency %s is not USD: the owner's money caps cannot be compared with the SDK's USD "
                        "cost, so RUNNER_*_MAX_COST_USD apply; token caps follow the owner", self.server.get("currency"))
            self._warned_currency = True
        self.budget.limit_to(owner_caps(self.server, self.budget.ceiling))
        return self.server

    # ----- one task ---------------------------------------------------------------------------
    async def run_one(self) -> str:
        """Returns 'disabled', 'idle', 'day_budget', or 'worked'."""
        server = await self.refresh_config()
        if not server.get("enabled"):
            return "disabled"
        try:
            self.budget.check_day()
        except BudgetExhausted as exc:
            log.warning("runner paused for the day: %s", exc)
            return "day_budget"
        task = await self.gw.call("next_task", {"kinds": list(self.cfg.task_kinds), "dry_run": self.cfg.dry_run})
        if not task.get("task_id"):
            return "idle"
        await self._work(task)
        return "worked"

    async def _work(self, task: dict[str, Any]) -> None:
        task_id = task["task_id"]
        kind = task.get("type") or "apply"
        cp = task.get("checkpoint") or {}
        if (cp.get("data") or {}).get("submit_attempted"):
            # A crash after the submit click: the form may have gone through. Never try again.
            await self.gw.call("report_result", {"task_id": task_id, "outcome": "uncertain",
                                                 "detail": "Runner restarted after a submit was attempted; not retried."})
            log.warning("task %s resumed after a submit attempt: reported uncertain", task_id)
            return
        rules = task.get("rules") or {}
        domain = rules.get("stay_on_domain")
        if not domain or kind not in self.cfg.task_kinds:
            detail = "Task carried no stay_on_domain rule." if not domain else f"This runner does not work {kind} tasks."
            with contextlib.suppress(GatewayError):
                await self.gw.call("release_task", {"task_id": task_id, "reason": detail})
            return
        guard = Guard([domain], now=self.clock, permit_safety=timedelta(seconds=self.cfg.permit_safety_seconds))
        browser = BrowserSession(guard, self.cfg.profile_dir, headless=self.cfg.headless)
        max_steps = min(int(rules.get("max_steps") or 0) or 1, int(self.server.get("max_steps") or 10**6))
        state = TaskState(task_id=task_id, posting_url=task.get("posting_url") or "", max_steps=max_steps,
                          task_type=kind, dry_run=self.cfg.dry_run, model=str(self.server.get("model") or ""),
                          evidence_max_bytes=int(self.server.get("evidence_max_bytes") or DEFAULT_EVIDENCE_MAX_BYTES),
                          checkpoint=cp or None)
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
            else:  # the browser never started: nothing was entered; give the task back
                with contextlib.suppress(GatewayError):
                    await self.gw.call("release_task", {"task_id": task_id, "reason": reason[:500]})
            await browser.close()
        if box is None:  # this runner cannot work right now: back off instead of claiming again at once
            raise RuntimeError(reason)

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
            if status == "disabled":
                log.info("runner switched off by the owner (or suspended); checking again in %ss", wait)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop.wait(), timeout=wait)
        with contextlib.suppress(Exception):
            await self.gw.close()
