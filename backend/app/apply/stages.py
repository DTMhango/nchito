"""The one application state machine (DESIGN.md 4, 18.2).

Every stage change goes through :func:`transition`. It enforces the legal moves, records an
append-only ``ApplicationEvent`` with the actor and the reason, and keeps the dates and open
pending actions consistent. Nothing else writes ``Application.stage``.

Who may move what (``via``):

- ``owner``: the owner dragging a card or pressing a button. May not move an application into
  ``applying`` or a submitted state: dragging to Applied never creates submission evidence, the
  owner uses "I applied myself" (``applied_myself``) instead.
- ``system``: the apply stream and reconciliation (dispatch, confirmation).
- ``applied_myself``: the owner says they applied outside the platform. Reaches ``submitted``,
  marked owner-attested; no evidence is created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.applications import (
    END_STAGES,
    Application,
    ApplicationEvent,
    PendingAction,
    PendingStatus,
    Stage,
)

Via = Literal["owner", "system", "applied_myself"]

S = Stage

PRE_SUBMIT = frozenset({S.shortlisted, S.tailoring, S.ready, S.applying})
SUBMITTED_STATES = frozenset({S.submitted_unconfirmed, S.submitted})
# Stages that can only be reached once an application has gone out.
POST_SUBMIT = frozenset({S.submitted_unconfirmed, S.submitted, S.screening, S.interview, S.offer, S.accepted})
AFTER_SUBMITTED = POST_SUBMIT - SUBMITTED_STATES
OWNER_FORBIDDEN_TARGETS = frozenset({S.applying, S.submitted_unconfirmed, S.submitted})

_LATE = frozenset({S.rejected, S.withdrawn, S.closed})
TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    S.shortlisted: frozenset({S.tailoring, S.ready, S.skipped, S.closed}),
    S.tailoring: frozenset({S.shortlisted, S.ready, S.skipped, S.closed}),
    S.ready: frozenset({S.tailoring, S.applying, S.skipped, S.closed}),
    S.applying: frozenset({S.ready, S.submitted_unconfirmed, S.submitted, S.closed}),
    S.submitted_unconfirmed: frozenset({S.submitted, S.screening, S.interview, S.offer}) | _LATE,
    S.submitted: frozenset({S.screening, S.interview, S.offer}) | _LATE,
    S.screening: frozenset({S.interview, S.offer}) | _LATE,
    S.interview: frozenset({S.offer}) | _LATE,
    S.offer: frozenset({S.accepted}) | _LATE,
    S.accepted: frozenset(),
    S.rejected: frozenset(),
    S.withdrawn: frozenset(),
    S.closed: frozenset({S.shortlisted}),  # reopening, only if nothing was ever sent (checked below)
    S.skipped: frozenset({S.shortlisted}),
}
# "I applied myself" may start from any stage that has not gone out, including a reopened skip or close.
APPLIED_MYSELF_FROM = frozenset(PRE_SUBMIT | {S.submitted_unconfirmed, S.skipped, S.closed})


class IllegalTransition(Exception):
    """A refused stage change. ``reason`` is shown to the owner."""

    def __init__(self, reason: str, *, current: Stage, target: Stage) -> None:
        super().__init__(reason)
        self.reason = reason
        self.current = current
        self.target = target


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None


def check_transition(app: Application, target: Stage, via: Via) -> Verdict:
    """Pure check of a move, with the reason when it is refused."""
    current = app.stage
    if target == current:
        return Verdict(False, f"already in {current.value}")
    if via == "applied_myself":
        if target != S.submitted:
            return Verdict(False, "'I applied myself' records a submission only")
        if current not in APPLIED_MYSELF_FROM:
            return Verdict(False, f"cannot record a submission from {current.value}")
        return Verdict(True)
    if current == S.submitted_unconfirmed and target == S.ready:
        # Only reconciliation, once it has established that nothing left (8.5, 18.3).
        return Verdict(True) if via == "system" else Verdict(
            False, "only reconciliation can establish that an unconfirmed send never left")
    if via == "owner" and current == S.applying:
        return Verdict(False, "it is being sent right now; only the apply process can move it")
    if via == "owner" and target in OWNER_FORBIDDEN_TARGETS:
        if target == S.applying:
            return Verdict(False, "only the apply process moves a role to applying")
        return Verdict(False, "dragging to a submitted state creates no evidence: use 'I applied myself'")
    if target not in TRANSITIONS[current]:
        return Verdict(False, f"{current.value} cannot move to {target.value}")
    if current == S.closed and app.applied_at is not None:
        return Verdict(False, "a closed application that was sent cannot be reopened")
    if target in AFTER_SUBMITTED and app.applied_at is None and current not in SUBMITTED_STATES:
        return Verdict(False, "nothing has been sent yet: use 'I applied myself' first")
    return Verdict(True)


def allowed_targets(app: Application, via: Via = "owner") -> list[Stage]:
    """Stages the application may move to right now (drives the buttons on the job page)."""
    return [t for t in Stage if check_transition(app, t, via).ok]


_last_event_at: datetime | None = None


def _next_event_time() -> datetime:
    """A strictly increasing time. The system clock can tick coarsely (about 16 ms on Windows), so two
    events written back to back would share a time and their order would fall to a random id."""
    global _last_event_at
    now = utcnow()
    if _last_event_at is not None and now <= _last_event_at:
        now = _last_event_at + timedelta(microseconds=1)
    _last_event_at = now
    return now


async def add_event(session: AsyncSession, application_id: uuid.UUID, kind: str, actor: str,
                    detail: dict[str, Any] | None = None) -> ApplicationEvent:
    # An explicit time keeps events written in one transaction in order (now() is the same for all of them).
    event = ApplicationEvent(application_id=application_id, kind=kind, actor=actor, detail=detail or {},
                             created_at=_next_event_time())
    session.add(event)
    await session.flush()
    return event


async def transition(session: AsyncSession, app: Application, target: Stage, *, actor: str, why: str,
                     via: Via = "owner", now: datetime | None = None,
                     detail: dict[str, Any] | None = None) -> ApplicationEvent:
    """Move ``app`` to ``target`` or raise :class:`IllegalTransition`. Always records who and why."""
    verdict = check_transition(app, target, via)
    if not verdict.ok:
        raise IllegalTransition(verdict.reason or "illegal move", current=app.stage, target=target)
    now = now or utcnow()
    previous = app.stage
    app.stage = target
    if target in SUBMITTED_STATES and app.applied_at is None:
        app.applied_at = now
    if previous == S.submitted_unconfirmed and target in PRE_SUBMIT:
        app.applied_at = None  # reconciliation found that it never left
    if via == "applied_myself":
        app.owner_attested = True
        app.applied_outside = True
    if target in END_STAGES:
        app.ended_at = now
        await _expire_pending(session, app.id, f"application moved to {target.value}", now)
    elif previous in END_STAGES:
        app.ended_at = None
    payload = {"from": previous.value, "to": target.value, "why": why, "via": via, **(detail or {})}
    event = await add_event(session, app.id, "stage_change", actor, payload)
    await session.flush()
    return event


async def _expire_pending(session: AsyncSession, application_id: uuid.UUID, reason: str, now: datetime) -> None:
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.application_id == application_id, PendingAction.status == PendingStatus.open))
    for action in rows:
        action.status = PendingStatus.expired
        action.resolved_at = now
        action.resolution = {"resolution": "expired", "note": reason}


# ----- duplicates and employer limits --------------------------------------------------------------


def counts_as_application(app: Application) -> bool:
    """An application that blocks another one for the same job: anything but a skip or an
    unsent close."""
    if app.stage == S.skipped:
        return False
    return not (app.stage == S.closed and app.applied_at is None)


async def blocking_application(session: AsyncSession, job_id: uuid.UUID) -> Application | None:
    """The application that makes a second one for this job a duplicate, if any."""
    rows = await session.scalars(select(Application).where(Application.job_id == job_id)
                                 .order_by(Application.created_at))
    for app in rows:
        if counts_as_application(app):
            return app
    return None


async def live_applications_at_employer(session: AsyncSession, canonical_employer: str) -> int:
    """Applications in flight (applying until an end state) at one employer, for the employer limit."""
    from app.models.applications import LIVE_STAGES
    from app.models.search import Job

    total = await session.scalar(
        select(func.count()).select_from(Application).join(Job, Job.id == Application.job_id)
        .where(func.lower(Job.canonical_employer) == canonical_employer.lower(),
               Application.stage.in_(LIVE_STAGES)))
    return int(total or 0)


# ----- snooze --------------------------------------------------------------------------------------


def _as_datetime(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=UTC)


def deadline_is_imminent(deadline: datetime | date | None, now: datetime, imminent_days: int, *,
                         overdue_counts: bool) -> bool:
    if deadline is None:
        return False
    at = _as_datetime(deadline)
    if at < now:
        return overdue_counts
    return at <= now + timedelta(days=imminent_days)


def is_snoozed(snoozed_until: datetime | None, now: datetime, *, deadlines: list[datetime | date | None],
               imminent_days: int, overdue_counts: bool = True) -> bool:
    """A snooze hides an item until ``snoozed_until``, then it returns. An imminent deadline overrides it."""
    if snoozed_until is None or snoozed_until <= now:
        return False
    return not any(deadline_is_imminent(d, now, imminent_days, overdue_counts=overdue_counts) for d in deadlines)
