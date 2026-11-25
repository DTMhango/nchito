"""Run execution boundary.

A ``RunHandler`` executes one ``Run`` of one kind. Streams register handlers here
(``register(RunKind.sweep, handler)``) from their own modules; the worker's ``run_pipeline``
task looks the handler up. A kind with no handler yet is recorded as ``skipped`` with a reason,
never as success.

Handler invariants:
- It receives an open session; it must not commit partial results that would move a sweep
  checkpoint on failure (a failed sweep does not move the checkpoint).
- It returns the final status and fills ``run.counts`` / ``run.source_results`` / ``run.cost_minor``.
- It must be safe to call again for the same run after a crash (restart resumes without duplicates).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import Run, RunKind, RunStatus

RunHandler = Callable[[AsyncSession, Run], Awaitable[RunStatus]]

_HANDLERS: dict[RunKind, RunHandler] = {}


def register(kind: RunKind, handler: RunHandler) -> None:
    if kind in _HANDLERS:
        raise ValueError(f"a handler for {kind} is already registered")
    _HANDLERS[kind] = handler


def handler_for(kind: RunKind) -> RunHandler | None:
    return _HANDLERS.get(kind)


def unregister(kind: RunKind) -> None:
    """For tests."""
    _HANDLERS.pop(kind, None)
