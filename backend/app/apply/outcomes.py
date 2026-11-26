"""Recording what happened to a dispatch attempt (DESIGN.md 8.5, 18.3). Invariants, not settings:

- **Evidence or it did not happen.** ``sent`` needs evidence (a sent-mail id, confirmation page,
  reference or confirmation email, or the owner's own mark). A channel reporting ``sent`` without
  evidence is recorded as ``unknown``.
- **Uncertain is held, not retried.** ``unknown`` moves the application to ``submitted_unconfirmed``: it
  stays live, so the duplicate and employer locks hold, and only reconciliation or the owner settles it.
- **Final outcomes are final.** An attempt that is ``sent``, ``acknowledged``, ``bounced``, ``failed`` or
  ``cancelled`` is never changed again.
- Every outcome is in the application timeline and the append-only audit with the attempt, packet hash,
  permit and evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.apply.channels.base import DispatchOutcome
from app.core import audit
from app.models.applications import (
    Application,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.schemas.json_types import Evidence

OPEN_STATUSES = frozenset({DispatchStatus.reserved, DispatchStatus.handed_off, DispatchStatus.unknown})
FINAL_STATUSES = frozenset(set(DispatchStatus) - OPEN_STATUSES)


class OutcomeError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def is_uncertain(attempt: DispatchAttempt) -> bool:
    """Handed to a channel (or possibly so) with no final outcome."""
    return attempt.status in (DispatchStatus.handed_off, DispatchStatus.unknown) or (
        attempt.status == DispatchStatus.reserved and attempt.started_at is not None)


async def lock_application(session: AsyncSession, application_id: uuid.UUID) -> Application:
    app = await session.scalar(select(Application).where(Application.id == application_id).with_for_update()
                               .execution_options(populate_existing=True))
    if app is None:
        raise OutcomeError("application not found", 404)
    return app


async def other_open(session: AsyncSession, app_id: uuid.UUID, attempt_id: uuid.UUID) -> bool:
    found = await session.scalar(select(DispatchAttempt.id).where(
        DispatchAttempt.application_id == app_id, DispatchAttempt.id != attempt_id,
        DispatchAttempt.status.in_(OPEN_STATUSES)).limit(1))
    return found is not None


def _facts(attempt: DispatchAttempt, **extra: Any) -> dict[str, Any]:
    return {"attempt_id": str(attempt.id), "application_id": str(attempt.application_id),
            "packet_hash": attempt.packet_hash, "channel": attempt.channel.value,
            "permit_id": str(attempt.permit_id) if attempt.permit_id else None, **extra}


async def _log(session: AsyncSession, attempt: DispatchAttempt, action: str, actor: str, **extra: Any) -> None:
    detail = _facts(attempt, **extra)
    await stages.add_event(session, attempt.application_id, action.replace(".", "_"), actor, detail)
    await audit.record(session, actor=actor, action=action, subject_type="dispatch_attempt", subject_id=attempt.id,
                       detail=detail)


async def give_back(session: AsyncSession, app: Application, attempt: DispatchAttempt, why: str, *, now: datetime
                    ) -> bool:
    """Nothing left for this application: back to ``ready`` (and its locks released), unless another
    attempt is still open."""
    if app.stage not in (Stage.applying, Stage.submitted_unconfirmed):
        return False
    if await other_open(session, app.id, attempt.id):
        return False
    await stages.transition(session, app, Stage.ready, actor="system", via="system", now=now, why=why,
                            detail={"attempt_id": str(attempt.id)})
    return True


async def close_confirmations(session: AsyncSession, app_id: uuid.UUID, resolution: dict[str, Any], *, actor: str,
                              now: datetime) -> list[PendingAction]:
    rows = list((await session.scalars(select(PendingAction).where(
        PendingAction.application_id == app_id, PendingAction.type == PendingActionType.confirm_submission,
        PendingAction.status == PendingStatus.open))).all())
    for action in rows:
        action.status, action.resolved_at, action.resolution = PendingStatus.resolved, now, {**resolution,
                                                                                               "by": actor}
        await audit.record(session, actor=actor, action="pending_action.resolved", subject_type="pending_action",
                           subject_id=action.id, detail={"type": action.type.value, **resolution})
    await session.flush()
    return rows


async def cancel(session: AsyncSession, attempt: DispatchAttempt, app: Application, reason: str, *, actor: str,
                 now: datetime, gates: list[dict[str, Any]] | None = None) -> None:
    """Cancel an attempt nothing was handed to yet. The application goes back to ``ready``."""
    if attempt.status != DispatchStatus.reserved or attempt.started_at is not None:
        raise OutcomeError("already handed to the channel: it cannot be recalled, only reconciled")
    attempt.status, attempt.error, attempt.outcome_at = DispatchStatus.cancelled, reason, now
    await session.flush()
    await _log(session, attempt, "dispatch.cancelled", actor, reason=reason, gates=gates or [])
    await give_back(session, app, attempt, f"send cancelled: {reason}", now=now)


async def record(session: AsyncSession, attempt: DispatchAttempt, outcome: DispatchOutcome, *, via: str, actor: str,
                 now: datetime) -> DispatchStatus:
    """Record a channel's (or the owner's) outcome on an open attempt. ``failed`` only sets the status:
    the caller decides between a bounded retry and giving the claim back."""
    if attempt.status in FINAL_STATUSES:
        raise OutcomeError(f"this send is already {attempt.status.value}")
    app = await lock_application(session, attempt.application_id)
    status = outcome.status
    error = outcome.error
    if status == "sent" and outcome.evidence is None:
        status, error = "unknown", "the channel reported it sent without evidence"
    if outcome.provider_message_id:
        attempt.provider_message_id = outcome.provider_message_id
    if status == "sent":
        assert outcome.evidence is not None
        evidence = outcome.evidence if outcome.evidence.at else outcome.evidence.model_copy(
            update={"at": now.isoformat()})
        attempt.status, attempt.evidence, attempt.outcome_at, attempt.error = DispatchStatus.sent, evidence, now, None
        app.confirmation_evidence = [*app.confirmation_evidence, evidence]
        if evidence.kind == "reference" and not app.reference:
            app.reference = evidence.value[:200]
        await session.flush()
        if app.stage in (Stage.applying, Stage.submitted_unconfirmed):
            await stages.transition(session, app, Stage.submitted, actor=actor, via="system", now=now,
                                    why=f"sent ({evidence.kind})", detail={"attempt_id": str(attempt.id),
                                                                           "evidence": evidence.model_dump()})
        await close_confirmations(session, app.id, {"resolution": "confirmed", "via": via,
                                                    "attempt_id": str(attempt.id)}, actor=actor, now=now)
        await _log(session, attempt, "dispatch.sent", actor, via=via, evidence=evidence.model_dump(),
                   provider_message_id=attempt.provider_message_id)
        return DispatchStatus.sent
    if status == "handed_off":
        attempt.status, attempt.error = DispatchStatus.handed_off, error
        await session.flush()
        await _log(session, attempt, "dispatch.handed_off", actor, via=via,
                   provider_message_id=attempt.provider_message_id)
        return DispatchStatus.handed_off
    if status == "failed":
        attempt.status, attempt.error, attempt.outcome_at = DispatchStatus.failed, error or "failed", now
        await session.flush()
        await _log(session, attempt, "dispatch.failed", actor, via=via, error=attempt.error)
        return DispatchStatus.failed
    # unknown: held for reconciliation, never resent.
    attempt.status, attempt.error = DispatchStatus.unknown, error or "outcome unknown"
    await session.flush()
    if app.stage == Stage.applying:
        await stages.transition(session, app, Stage.submitted_unconfirmed, actor=actor, via="system", now=now,
                                why=f"outcome unknown: {attempt.error}", detail={"attempt_id": str(attempt.id)})
    await _log(session, attempt, "dispatch.uncertain", actor, via=via, error=attempt.error)
    return DispatchStatus.unknown


def owner_evidence(reference: str | None, note: str | None, now: datetime) -> Evidence:
    reference = (reference or "").strip()
    if reference:
        return Evidence(kind="reference", value=reference[:200], at=now.isoformat())
    return Evidence(kind="owner_marked", value=(note or "").strip()[:500] or "marked submitted by the owner",
                    at=now.isoformat())


async def settle_sent_by_owner(session: AsyncSession, attempt: DispatchAttempt, *, reference: str | None,
                               note: str | None, actor: str, now: datetime) -> DispatchStatus:
    """The owner says it went out (manual handoff, or an uncertain send they checked)."""
    if attempt.status not in OPEN_STATUSES:
        raise OutcomeError(f"this send is already {attempt.status.value}")
    return await record(session, attempt, DispatchOutcome(status="sent", evidence=owner_evidence(reference, note, now)),
                        via="owner", actor=actor, now=now)


async def settle_not_sent(session: AsyncSession, attempt: DispatchAttempt, *, reason: str, via: str, actor: str,
                          now: datetime) -> None:
    """Established (by the channel's reconcile or the owner) that nothing left: the attempt is failed and the
    application goes back to ``ready``. Never followed by an automatic resend."""
    if attempt.status not in OPEN_STATUSES:
        raise OutcomeError(f"this send is already {attempt.status.value}")
    app = await lock_application(session, attempt.application_id)
    attempt.status, attempt.error, attempt.outcome_at = DispatchStatus.failed, f"not sent: {reason}", now
    await session.flush()
    await close_confirmations(session, app.id, {"resolution": "not_sent", "via": via,
                                                "attempt_id": str(attempt.id)}, actor=actor, now=now)
    await _log(session, attempt, "dispatch.not_sent", actor, via=via, reason=reason)
    await give_back(session, app, attempt, f"not sent: {reason}", now=now)
