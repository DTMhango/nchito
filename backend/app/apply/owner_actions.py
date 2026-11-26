"""Resolving the pending actions that are the owner's decisions (DESIGN.md 7.1, 8.4, 18.4).

- ``approved`` (``approve``): approve the packet the action names, only if it is still the current one.
- ``chosen`` (``conflict_choice``): pick a role in an employer group.
  ``displace_prepared``: keep the prepared role, or take the challenger (the prepared application is
  skipped, the group is resolved again and the challenger wins).
  ``better_role_after_applying``: keep the earlier application, or release the better role from its
  group (the earlier application cannot be recalled). Either way the choice is not asked again.
- ``continue`` (the blocker kinds ``accounts.CHOICES`` allows: sign-in, account, verification code, CAPTCHA,
  assessment, declaration; a suspicious page only with ``acknowledged``): the task goes back to the same runner
  from its checkpoint; it still needs a submit permit. Sibling actions that share the blocker close too.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import approval, packets, stages
from app.core import audit
from app.core.clock import utcnow
from app.models.applications import (
    Application,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.search import Job
from app.pipeline import conflicts

# Types that can carry a continuable blocker; which kinds may actually continue is ``accounts.choices_for``.
CONTINUABLE = frozenset({PendingActionType.sign_in, PendingActionType.create_account, PendingActionType.captcha,
                         PendingActionType.assessment, PendingActionType.declaration,
                         PendingActionType.redirect_off_domain, PendingActionType.page_instruction})


class ResolveError(Exception):
    def __init__(self, message: str, status: int = 409, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


async def _close(session: AsyncSession, action: PendingAction, resolution: dict[str, Any], actor: str,
                 now: datetime) -> None:
    action.status, action.resolved_at, action.resolution = PendingStatus.resolved, now, resolution
    await session.flush()
    if action.application_id:
        await stages.add_event(session, action.application_id, "pending_action_closed", actor, {
            "pending_action_id": str(action.id), "type": action.type.value, "status": "resolved", **resolution})
    await audit.record(session, actor=actor, action="pending_action.resolved", subject_type="pending_action",
                       subject_id=action.id, detail={"type": action.type.value, **resolution})


async def approve_from_action(session: AsyncSession, action: PendingAction, *, actor: str) -> None:
    if action.application_id is None:
        raise ResolveError("this approval has no application", 422)
    app = await session.get(Application, action.application_id)
    assert app is not None
    packet = await packets.current(session, app.id)
    wanted = action.detail.get("packet_hash")
    if packet is None or packet.content_hash != wanted:
        raise ResolveError("the packet changed since this approval was raised; open the receipt again")
    try:
        await approval.approve(session, app, packet_version=packet.version, packet_hash=packet.content_hash,
                               channel=packet.contents.channel or "manual", actor=actor)
    except approval.ApprovalError as exc:
        raise ResolveError(exc.message, exc.status) from exc
    await session.refresh(action)  # approve() closed it


async def _skip_prepared(session: AsyncSession, application_id: str, actor: str, why: str, now: datetime) -> None:
    app = await session.get(Application, uuid.UUID(application_id))
    if app is None or app.stage not in approval.APPROVABLE_STAGES:
        raise ResolveError("the prepared application can no longer be set aside")
    current = await packets.current(session, app.id)
    if current is not None:
        await packets.invalidate(session, app, current, why, actor=actor, now=now)
    await stages.transition(session, app, Stage.skipped, actor=actor, via="owner", now=now, why=why)
    job = await session.get(Job, app.job_id)
    assert job is not None
    job.triage = "skipped"
    await session.flush()


async def choose(session: AsyncSession, action: PendingAction, chosen_job_id: uuid.UUID | None, *, actor: str,
                 note: str | None = None, now: datetime | None = None) -> None:
    now = now or utcnow()
    if chosen_job_id is None:
        raise ResolveError("chosen_job_id is required", 422)
    detail = action.detail
    kind = detail.get("kind")
    chosen = str(chosen_job_id)
    if kind == "displace_prepared":
        keep, challenger = detail["current"]["job_id"], detail["challenger"]["job_id"]
        if chosen not in (keep, challenger):
            raise ResolveError("choose one of the two roles", 422)
        if chosen == challenger:
            await _skip_prepared(session, detail["application_id"], actor,
                                 f"owner chose {detail['challenger']['title']} instead", now)
    elif kind == "better_role_after_applying":
        applied, candidate = detail["applied_job_id"], detail["candidate"]["job_id"]
        if chosen not in (applied, candidate):
            raise ResolveError("choose the earlier application or the better role", 422)
        if chosen == candidate:
            job = await session.get(Job, chosen_job_id)
            if job is None:
                raise ResolveError("role not found", 404)
            if job.conflict_state.value == "held":
                await conflicts.release_held(session, job, actor=actor,
                                             reason=note or "owner chose it after applying to another role")
    else:
        raise ResolveError(f"unknown conflict choice {kind!r}", 422)
    await _close(session, action, {"resolution": "chosen", "chosen_job_id": chosen, "kind": kind, "note": note},
                 actor, now)
    employer = detail.get("current", detail.get("candidate", {})).get("job_id")
    job = await session.get(Job, uuid.UUID(employer)) if employer else None
    if job is not None:
        await conflicts.on_job_changed(session, job, now=now)


async def apply_proposal(session: AsyncSession, action: PendingAction, *, actor: str,
                         now: datetime | None = None) -> None:
    """Approve a proposal raised by another stream (``detail.kind`` has a resolver, ``apply.resolvers``)."""
    from app.apply import resolvers

    now = now or utcnow()
    try:
        await resolvers.apply(session, action, actor=actor)
    except resolvers.ResolverUnavailable as exc:
        raise ResolveError(str(exc), 501) from exc
    await session.refresh(action)
    if action.status == PendingStatus.open:
        await _close(session, action, {"resolution": "approved", "kind": resolvers.kind_of(action)}, actor, now)


async def confirm_submission(session: AsyncSession, action: PendingAction, *, actor: str,
                             reference: str | None = None, note: str | None = None,
                             now: datetime | None = None) -> None:
    """``confirmed``: the owner says the uncertain send went out. Settles its attempt as sent with the
    owner's evidence (the reference, if given); the action closes with it."""
    from app.apply import outcomes
    from app.models.applications import DispatchAttempt

    now = now or utcnow()
    raw = action.detail.get("attempt_id")
    attempt = await session.get(DispatchAttempt, uuid.UUID(raw), with_for_update=True) if raw else None
    if attempt is None:
        raise ResolveError("this confirmation names no send", 422)
    try:
        await outcomes.settle_sent_by_owner(session, attempt, reference=reference, note=note, actor=actor, now=now)
    except outcomes.OutcomeError as exc:
        raise ResolveError(exc.message, exc.status) from exc
    await session.refresh(action)
    if action.status == PendingStatus.open:
        await _close(session, action, {"resolution": "confirmed", "attempt_id": raw, "reference": reference},
                     actor, now)


async def continue_task(session: AsyncSession, action: PendingAction, *, actor: str, note: str | None = None,
                        now: datetime | None = None, acknowledged: bool = False) -> list[PendingAction]:
    """'I've signed in, continue' (8.4). Returns the actions that closed. The work is in ``accounts``: it marks
    the portal account signed in, re-checks expiry and duplicates, and requeues each task for the same runner."""
    from app.apply import accounts

    return await accounts.continue_blocker(session, action, actor=actor, note=note, now=now, acknowledged=acknowledged)
