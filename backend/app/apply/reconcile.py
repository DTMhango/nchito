"""Reconciliation of uncertain sends (DESIGN.md 8.5, 18.3). Invariants, not settings:

- An uncertain attempt (``unknown``, ``handed_off``, or started with no outcome) is **never resent**. It is
  settled only by ``Channel.reconcile`` (sent items, confirmations) or by the owner.
- ``Channel.reconcile`` runs every ``reconcile.check_every_minutes``. ``sent`` with evidence settles it
  as sent; ``failed`` settles it as not sent (the application goes back to ``ready``; nothing is retried
  automatically); anything else keeps waiting.
- Once an attempt has waited ``reconcile.confirmation_wait_hours`` the owner is asked (one
  ``confirm_submission`` pending action per attempt) and checks keep running until someone settles it.
- Every check and decision is audited with the attempt.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import outcomes
from app.apply.channels import registry
from app.apply.channels.base import DispatchOutcome
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
)
from app.models.search import Job

OwnerDecision = Literal["check", "sent", "not_sent"]


def _uncertain_clause():
    return or_(DispatchAttempt.status.in_((DispatchStatus.unknown, DispatchStatus.handed_off)),
               (DispatchAttempt.status == DispatchStatus.reserved) & DispatchAttempt.started_at.is_not(None))


async def _ask_owner(session: AsyncSession, attempt: DispatchAttempt, *, now: datetime) -> PendingAction | None:
    existing = await session.scalar(select(PendingAction).where(
        PendingAction.type == PendingActionType.confirm_submission, PendingAction.status == PendingStatus.open,
        PendingAction.application_id == attempt.application_id))
    if existing is not None:
        return None
    app =await session.get(Application, attempt.application_id)
    job = await session.get(Job, app.job_id) if app else None
    label = f"{job.title} at {job.employer}" if job else "an application"
    action = PendingAction(type=PendingActionType.confirm_submission, application_id=attempt.application_id,
                           title=f"Did it go out? {label}", detail={
                               "kind": "confirm_submission", "attempt_id": str(attempt.id),
                               "channel": attempt.channel.value, "packet_hash": attempt.packet_hash,
                               "since": (attempt.started_at or attempt.created_at).isoformat(),
                               "reason": attempt.error or "no confirmation yet"})
    session.add(action)
    await session.flush()
    await audit.record(session, actor="system", action="reconcile.owner_asked", subject_type="dispatch_attempt",
                       subject_id=attempt.id, detail={"pending_action_id": str(action.id)})
    return action


async def check(session: AsyncSession, attempt: DispatchAttempt, *, actor: str = "system:reconcile",
                now: datetime | None = None) -> str:
    """Ask the channel once. Returns ``sent``, ``not_sent`` or ``waiting``."""
    now = now or utcnow()
    if not outcomes.is_uncertain(attempt):
        raise outcomes.OutcomeError(f"this send is {attempt.status.value}, not uncertain", code="not_uncertain")
    try:
        channel = await registry.get(session, attempt.channel.value)
        outcome = await channel.reconcile(str(attempt.id))
    except Exception as exc:  # a failed check proves nothing
        outcome = DispatchOutcome(status="unknown", error=f"reconcile failed: {type(exc).__name__}: {exc}"[:500])
    attempt.reconcile_attempts += 1
    attempt.last_reconciled_at = now
    await session.flush()
    await audit.record(session, actor=actor, action="reconcile.checked", subject_type="dispatch_attempt",
                       subject_id=attempt.id, detail={"result": outcome.status, "error": outcome.error,
                                                      "provider_message_id": outcome.provider_message_id,
                                                      "check": attempt.reconcile_attempts})
    if outcome.status == "sent" and outcome.evidence is not None:
        await outcomes.record(session, attempt, outcome, via="reconcile", actor=actor, now=now)
        return "sent"
    if outcome.status == "failed":
        await outcomes.settle_not_sent(session, attempt, reason=outcome.error or "the channel found it never left",
                                       via="reconcile", actor=actor, now=now)
        return "not_sent"
    if attempt.status == DispatchStatus.reserved:
        await outcomes.record(session, attempt, DispatchOutcome(status="unknown", error=attempt.error or
                                                                "started, no outcome recorded"),
                              via="reconcile", actor=actor, now=now)
    wait_hours = int(await settings_service.get_value(session, "reconcile.confirmation_wait_hours"))
    if (attempt.started_at or attempt.created_at) <= now - timedelta(hours=wait_hours):
        await _ask_owner(session, attempt, now=now)
    return "waiting"


async def reconcile_due(session: AsyncSession, *, now: datetime | None = None) -> dict[uuid.UUID, str]:
    """Check every uncertain attempt not checked within ``reconcile.check_every_minutes``. Commits each."""
    now = now or utcnow()
    minutes = int(await settings_service.get_value(session, "reconcile.check_every_minutes"))
    rows = (await session.scalars(select(DispatchAttempt).where(
        _uncertain_clause(), or_(DispatchAttempt.last_reconciled_at.is_(None),
                                 DispatchAttempt.last_reconciled_at <= now - timedelta(minutes=minutes)))
        .order_by(DispatchAttempt.created_at).with_for_update(skip_locked=True))).all()
    results: dict[uuid.UUID, str] = {}
    for attempt in rows:
        if attempt.status == DispatchStatus.reserved:
            # Started, no outcome yet: it may still be sending. Leave it to the in-flight timeout.
            in_flight = int(await settings_service.get_value(session, "reconcile.in_flight_timeout_minutes"))
            if attempt.started_at and attempt.started_at > now - timedelta(minutes=in_flight):
                continue
        results[attempt.id] = await check(session, attempt, now=now)
    await session.commit()
    return results


async def decide(session: AsyncSession, attempt: DispatchAttempt, decision: OwnerDecision, *, actor: str,
                 reference: str | None = None, note: str | None = None, now: datetime | None = None) -> str:
    """The owner settles an uncertain attempt: ``check`` asks the channel now, ``sent`` records it as sent
    (with the reference, if any), ``not_sent`` records that it never left (the role goes back to ready;
    nothing is resent automatically)."""
    now = now or utcnow()
    if decision == "check":
        return await check(session, attempt, actor=actor, now=now)
    if attempt.status not in outcomes.OPEN_STATUSES:
        raise outcomes.OutcomeError(f"this send is already {attempt.status.value}")
    if attempt.status == DispatchStatus.reserved and attempt.started_at is None:
        raise outcomes.OutcomeError("this send has not started; cancel it instead", code="not_started")
    if decision == "sent":
        await outcomes.settle_sent_by_owner(session, attempt, reference=reference, note=note, actor=actor, now=now)
        return "sent"
    await outcomes.settle_not_sent(session, attempt, reason=(note or "").strip() or "the owner confirmed it did not go "
                                   "out", via="owner", actor=actor, now=now)
    return "not_sent"
