"""Wiring: connects the pipeline stages to the real AI client, the scorer and the conflicts module.

Installed once per process (``install``): the worker calls it at start-up, the web app at
``create_app``. Tests install their own doubles through the same hooks.

- Intake gets ``LLMService`` per run (``for_run``), so every paid call reserves in the budget
  ledger before the call, reconciles after, and honours the per-run cap.
- A sweep runs dedupe -> normalise -> filters -> score: scoring is the orchestrator's score hook.
- Scoring, backtests and custom facets get ``LLMService``; corrections re-evaluate conflict
  groups with ``conflicts.resolve_employers``.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMClient
from app.llm.service import LLMService
from app.models.search import Run
from app.pipeline import conflicts, corrections, orchestrator, scoring


async def llm_for(session: AsyncSession, run: Run | None = None) -> LLMClient:
    return LLMService().for_run(run.id if run is not None else None)


async def default_client(session: AsyncSession) -> LLMClient:
    return LLMService()


async def score_hook(session: AsyncSession, run: Run, job_ids: list[uuid.UUID],
                     llm: LLMClient | None) -> orchestrator.ScoreOutcome:
    """Filters then scoring for the run's campaign. ``score_jobs`` adds its own spend and counts to the
    run, so the outcome only carries the budget state."""
    summary = await scoring.score_jobs(session, run, job_ids, client=llm, paid=llm is not None)
    scope = summary.budget_scope if summary.parked else None
    return orchestrator.ScoreOutcome(cost_micros=0, budget_scope=scope)


def install() -> None:
    """Register the real implementations (idempotent; last registration wins)."""
    orchestrator.configure(llm_factory=llm_for)
    orchestrator.register_score_hook(score_hook)
    orchestrator.install()
    scoring.set_client_factory(default_client)
    corrections.set_conflict_reevaluator(conflicts.resolve_employers)


def uninstall() -> None:
    """Undo ``install`` (tests): no AI client, no scorer, no run handlers, no conflict re-evaluation."""
    from app.models.search import RunKind
    from app.pipeline import runs

    orchestrator.reset_deps()
    orchestrator.reset_score_hook()
    scoring.set_client_factory(None)
    corrections.set_conflict_reevaluator(None)
    for kind in (RunKind.sweep, RunKind.expiry_check, RunKind.retention):
        runs.unregister(kind)
