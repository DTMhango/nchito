"""Approval of an application packet (DESIGN.md 7.1, 8.1, 18.2).

- An approval binds to one packet (version and hash). Building a different packet invalidates it
  (``packets.build``); it never carries over.
- **Owner approval** is refused when any gate the owner cannot settle is failing or unknown: an
  excluded role (whatever its score), a role held in its employer group while the winner is live,
  an unwaived blocking document check, a mode that does not let the system apply (except the manual
  channel), a duplicate.
- **Automatic approval** happens only when the channel's mode is ``auto_apply`` and every gate passes
  with no unknowns (timing gates such as quiet hours and caps are left to the permit). Otherwise the
  owner is asked through an ``approve`` pending action.
- **Reject** skips the role (and promotes the next role in its employer group); **request changes**
  retires the packet and sends the application back to tailoring.
- Everything is in the application timeline and the append-only audit, with the gates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import gates, packets, policy, stages
from app.core import audit
from app.core.clock import utcnow
from app.kit import waivers
from app.models.applications import (
    Application,
    ApplicationPacket,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.kit import Guardrail
from app.models.search import Job
from app.pipeline import conflicts

AUTO_APPROVER = "system:auto"
APPROVABLE_STAGES = frozenset({Stage.shortlisted, Stage.tailoring, Stage.ready})


class ApprovalError(Exception):
    def __init__(self, message: str, status: int = 409, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail or {}


@dataclass
class ApprovalOutcome:
    approved: bool
    status: str  # granted | wait_for_owner | denied
    reason: str
    gates: list[dict[str, Any]] = field(default_factory=list)
    pending_action_id: uuid.UUID | None = None


async def _close_approvals(session: AsyncSession, app: Application, resolution: str, actor: str, now: datetime,
                           note: str | None = None) -> None:
    rows = (await session.scalars(select(PendingAction).where(
        PendingAction.application_id == app.id, PendingAction.type == PendingActionType.approve,
        PendingAction.status == PendingStatus.open))).all()
    for action in rows:
        action.status = PendingStatus.resolved
        action.resolved_at = now
        action.resolution = {"resolution": resolution, "note": note, "by": actor}
    await session.flush()


async def _mark_approved(session: AsyncSession, app: Application, packet: ApplicationPacket, *, actor: str,
                         evaluation: gates.Evaluation, now: datetime) -> None:
    packet.approved_at, packet.approved_by = now, actor
    app.approved_packet_id = packet.id
    if app.stage in (Stage.shortlisted, Stage.tailoring):
        await stages.transition(session, app, Stage.ready, actor=actor, via="system", now=now,
                                why="packet approved", detail={"packet_hash": packet.content_hash})
    await _close_approvals(session, app, "approved", actor, now)
    await stages.add_event(session, app.id, "approval", actor, {
        "packet_version": packet.version, "packet_hash": packet.content_hash, "channel": packet.contents.channel,
        "automatic": actor == AUTO_APPROVER, "mode": evaluation.decision.mode})
    await audit.record(session, actor=actor, action="application.approved", subject_type="application",
                       subject_id=app.id, detail={
                           "packet_id": str(packet.id), "packet_version": packet.version,
                           "packet_hash": packet.content_hash, "channel": packet.contents.channel,
                           "automatic": actor == AUTO_APPROVER, "mode": evaluation.decision.mode,
                           "reason": evaluation.reason, "gates": evaluation.gate_results()})


async def _apply_waivers(session: AsyncSession, app: Application, guardrail_ids: list[uuid.UUID],
                         reason: str | None, actor: str) -> None:
    if not guardrail_ids:
        return
    if not (reason or "").strip():
        raise ApprovalError("a reason is required to waive a guardrail", 422)
    already = await waivers.waived_ids(session, app.id)
    for gid in guardrail_ids:
        if str(gid) in already:
            continue
        guardrail = await session.get(Guardrail, gid)
        if guardrail is None:
            raise ApprovalError(f"guardrail {gid} not found", 404)
        try:
            await waivers.create(session, guardrail, app.id, reason or "", actor=actor)
        except waivers.WaiverError as exc:
            raise ApprovalError(str(exc), exc.status_code) from exc
    waived = await waivers.waived_ids(session, app.id)
    app.check_results = [c.model_copy(update={"waived": True}) if c.guardrail_id in waived and c.status == "block"
                         else c for c in app.check_results]
    await session.flush()


async def approve(session: AsyncSession, app: Application, *, packet_version: int, packet_hash: str, channel: str,
                  actor: str, waiver_ids: list[uuid.UUID] | None = None, waiver_reason: str | None = None,
                  now: datetime | None = None) -> ApprovalOutcome:
    """The owner approves exactly this packet for this channel."""
    now = now or utcnow()
    await session.execute(select(Application.id).where(Application.id == app.id).with_for_update())
    if app.stage not in APPROVABLE_STAGES:
        raise ApprovalError(f"an application in {app.stage.value} cannot be approved")
    packet = await packets.current(session, app.id)
    if packet is None:
        raise ApprovalError("no packet has been built for this application")
    if packet.version != packet_version or packet.content_hash != packet_hash:
        raise ApprovalError("the packet changed since you looked at it; review the new version", detail={
            "current_version": packet.version, "current_hash": packet.content_hash})
    if packet.contents.channel != channel:
        raise ApprovalError(f"this packet is for the {packet.contents.channel} channel, not {channel}")
    await _apply_waivers(session, app, waiver_ids or [], waiver_reason, actor)
    evaluation = await gates.evaluate(session, app, packet, channel=channel, approval="owner",
                                      packet_hash=packet_hash, for_approval=True, now=now)
    if evaluation.status != "granted":
        await audit.record(session, actor=actor, action="application.approval_refused", subject_type="application",
                           subject_id=app.id, detail={"packet_hash": packet_hash, "reason": evaluation.reason,
                                                      "gates": evaluation.gate_results()})
        raise ApprovalError(evaluation.reason, detail={"gates": evaluation.gate_results()})
    await _mark_approved(session, app, packet, actor=actor, evaluation=evaluation, now=now)
    return ApprovalOutcome(True, "granted", evaluation.reason, evaluation.gate_results())


async def request_owner_approval(session: AsyncSession, app: Application, packet: ApplicationPacket, reason: str
                                 ) -> PendingAction:
    """Open (or reuse) the ``approve`` pending action for this packet."""
    existing = await session.scalar(select(PendingAction).where(
        PendingAction.application_id == app.id, PendingAction.type == PendingActionType.approve,
        PendingAction.status == PendingStatus.open))
    job = await session.get(Job, app.job_id)
    detail = {"packet_id": str(packet.id), "packet_version": packet.version, "packet_hash": packet.content_hash,
              "channel": packet.contents.channel, "reason": reason}
    if existing is not None:
        existing.detail = detail
        await session.flush()
        return existing
    action = PendingAction(type=PendingActionType.approve, application_id=app.id,
                           title=f"Approve: {job.title if job else 'application'} at {job.employer if job else ''}",
                           detail=detail, deadline=_deadline(job))
    session.add(action)
    await session.flush()
    return action


def _deadline(job: Job | None) -> datetime | None:
    if job is None or job.deadline is None:
        return None
    return stages._as_datetime(job.deadline)


async def auto_approve(session: AsyncSession, app: Application, packet: ApplicationPacket, *,
                       now: datetime | None = None) -> ApprovalOutcome:
    """Approve automatically when the channel's mode is ``auto_apply`` and every gate passes with no
    unknowns; otherwise ask the owner (when the mode lets the system apply) and say why."""
    now = now or utcnow()
    channel = packet.contents.channel or (app.channel.value if app.channel else "manual")
    pol = await policy.for_application(session, app, channel)
    evaluation = await gates.evaluate(session, app, packet, channel=channel, approval="auto",
                                      packet_hash=packet.content_hash, for_approval=True, now=now)
    if pol.auto and evaluation.status == "granted":
        await _mark_approved(session, app, packet, actor=AUTO_APPROVER, evaluation=evaluation, now=now)
        return ApprovalOutcome(True, "granted", evaluation.reason, evaluation.gate_results())
    reason = evaluation.reason if pol.auto else pol.reason
    action_id = None
    if pol.system_applies and evaluation.status != "denied":
        action_id = (await request_owner_approval(session, app, packet, reason)).id
    await audit.record(session, actor="system", action="application.auto_approval_declined",
                       subject_type="application", subject_id=app.id, detail={
                           "packet_hash": packet.content_hash, "policy": pol.reason, "status": evaluation.status,
                           "reason": reason, "gates": evaluation.gate_results()})
    return ApprovalOutcome(False, evaluation.status, reason, evaluation.gate_results(), action_id)


async def after_packet_built(session: AsyncSession, app: Application, packet: ApplicationPacket, *,
                             now: datetime | None = None) -> ApprovalOutcome | None:
    """What a new packet leads to under the policy: automatic approval, an approval request, or nothing
    (``save_only`` / ``prepare``: the owner decides when to look)."""
    channel = packet.contents.channel or "manual"
    pol = await policy.for_application(session, app, channel)
    if not pol.system_applies:
        return None
    return await auto_approve(session, app, packet, now=now)


async def reject(session: AsyncSession, app: Application, *, actor: str, reason: str | None = None,
                 now: datetime | None = None) -> None:
    """The owner says no: the role is skipped and the next role in its employer group is promoted."""
    now = now or utcnow()
    if app.stage not in APPROVABLE_STAGES:
        raise ApprovalError(f"an application in {app.stage.value} cannot be rejected")
    packet = await packets.current(session, app.id)
    if packet is not None:
        await packets.invalidate(session, app, packet, f"rejected by the owner{f': {reason}' if reason else ''}",
                                 actor=actor, now=now)
    await _close_approvals(session, app, "rejected", actor, now, reason)
    await stages.transition(session, app, Stage.skipped, actor=actor, via="owner", now=now,
                            why=reason or "rejected at approval")
    job = await session.get(Job, app.job_id)
    assert job is not None
    job.triage = "skipped"
    await audit.record(session, actor=actor, action="application.rejected", subject_type="application",
                       subject_id=app.id, detail={"reason": reason,
                                                  "packet_hash": packet.content_hash if packet else None})
    await session.flush()
    await conflicts.on_job_changed(session, job, now=now)


async def request_changes(session: AsyncSession, app: Application, *, actor: str, note: str,
                          now: datetime | None = None) -> None:
    """The owner wants something changed: the packet is retired and the application goes back to tailoring."""
    now = now or utcnow()
    if not note.strip():
        raise ApprovalError("say what should change", 422)
    if app.stage not in APPROVABLE_STAGES:
        raise ApprovalError(f"an application in {app.stage.value} cannot be changed now")
    packet = await packets.current(session, app.id)
    if packet is not None:
        await packets.invalidate(session, app, packet, f"changes requested: {note}", actor=actor, now=now)
    await _close_approvals(session, app, "changes_requested", actor, now, note)
    if app.stage == Stage.ready:
        await stages.transition(session, app, Stage.tailoring, actor=actor, via="owner", now=now,
                                why=f"changes requested: {note}")
    else:
        await stages.add_event(session, app.id, "changes_requested", actor, {"note": note})
    await audit.record(session, actor=actor, action="application.changes_requested", subject_type="application",
                       subject_id=app.id, detail={"note": note,
                                                  "packet_hash": packet.content_hash if packet else None})
