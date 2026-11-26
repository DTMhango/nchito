"""Approving and sending a message: the application's own packet, permit and dispatch path, extended.

- **Packet.** Approval snapshots the message as an immutable, hashed packet (``packets.build_message``:
  recipients, subject, body, thread reference, channel, message kind). Editing anything afterwards makes a
  new packet; the old approval and permits go with the old one.
- **Approval.** By the owner, always, except the one automatic case below. Refused while any check blocks
  (including a question for the owner, an unconfirmed recipient or a commitment without a confirmed answer).
- **Permit, then attempt.** ``queue`` takes the permit lock, runs the message gates, gets a single-use permit
  (``permits.grant_message``), consumes it and writes the ``DispatchAttempt`` in one transaction. The worker's
  ``apply_tick`` sends it after the email send delay through the email channel, rechecking these gates first
  (``recheck``, called by ``dispatch.recheck``). An uncertain send is reconciled, never resent; a failed one is
  never retried on its own.
- **The automatic case** (setting ``followups.auto_send``, off by default): only the plain no-reply
  follow-up, drafted by the system, with clean checks, only to addresses the application itself was sent to,
  never after any reply from the employer, within the follow-up caps and outside quiet hours. Each condition is
  a gate, checked when queued and again at dispatch.
- **Pause.** The master pause and a paused campaign stop every message, except one the owner approved while a
  wind-down is active (withdrawals and declines after accepting an offer).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import dispatch, gates, outcomes, packets, permits, stages
from app.apply.packets import domain_of
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    ApplicationPacket,
    Channel,
    DispatchAttempt,
    DispatchStatus,
    Stage,
)
from app.models.followups import OutboundMessage, WindDown
from app.pipeline.checks import service as check_service
from app.pipeline.checks.findings import worst
from app.pipeline.followups import checks
from app.pipeline.followups import context as ctx_mod
from app.pipeline.followups.context import MessageContext
from app.schemas.json_types import GateResult, PacketContents, PacketDestination, PacketEmail

AUTO_ACTOR = "system:auto-follow-up"
OPEN = (DispatchStatus.reserved, DispatchStatus.handed_off, DispatchStatus.unknown)
GONE = (DispatchStatus.sent, DispatchStatus.acknowledged)


class SendError(Exception):
    def __init__(self, message: str, code: str, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.message, self.code, self.status, self.extra = message, code, status, extra


@dataclass
class QueueOutcome:
    status: str  # queued | denied
    reason: str
    attempt: DispatchAttempt | None = None
    gates: list[dict[str, Any]] = field(default_factory=list)
    code: str | None = None


# ----- state ---------------------------------------------------------------------------------------


async def attempts(session: AsyncSession, msg: OutboundMessage) -> list[DispatchAttempt]:
    if msg.packet_id is None:
        return []
    return list((await session.scalars(select(DispatchAttempt).where(DispatchAttempt.packet_id == msg.packet_id)
                                       .order_by(DispatchAttempt.created_at))).all())


def send_state(rows: list[DispatchAttempt]) -> str:
    if not rows:
        return "none"
    last = rows[-1]
    if last.status == DispatchStatus.reserved:
        return "sending" if last.started_at is not None else "queued"
    if last.status in GONE:
        return "sent"
    if last.status in (DispatchStatus.unknown, DispatchStatus.handed_off):
        return "uncertain"
    if last.status in (DispatchStatus.failed, DispatchStatus.bounced):
        return "failed"
    return "cancelled"


async def locked(session: AsyncSession, msg: OutboundMessage) -> str | None:
    """Why ``msg`` can no longer be changed (a send is open, uncertain or done), or None."""
    state = send_state(await attempts(session, msg))
    return None if state in ("none", "failed", "cancelled") else f"this message is {state}"


async def active_wind_down(session: AsyncSession) -> WindDown | None:
    return await session.scalar(select(WindDown).where(WindDown.status == "active")
                                .order_by(WindDown.created_at.desc()).limit(1))


def is_automatic(packet: ApplicationPacket) -> bool:
    return (packet.approved_by or "").startswith("system")


# ----- approval ------------------------------------------------------------------------------------


async def recheck_message(session: AsyncSession, msg: OutboundMessage, *, now: datetime) -> MessageContext:
    """Run the code checks again on the message as it stands (the Kit may have changed)."""
    app = await session.get(Application, msg.application_id)
    assert app is not None
    ctx = await ctx_mod.load(session, app)
    _, kit = await check_service.context(session, app)
    await checks.run(session, msg, ctx, kit, await settings_service.values(session), today=now.date())
    return ctx


def contents_for(msg: OutboundMessage, ctx: MessageContext) -> PacketContents:
    if not msg.to:
        raise SendError("the message has no recipient", "no_recipient", 409)
    if not ctx.sending_identity:
        raise SendError("no mailbox to send from: connect one", "no_identity", 409)
    domain = domain_of(msg.to[0]) or ""
    verified = msg.to[0].lower() in {a.lower() for a in ctx.known}
    email = PacketEmail(to=list(msg.to), cc=list(msg.cc), subject=msg.subject, body=checks.body_of(msg.paragraphs),
                        thread_ref=msg.thread_ref)
    return PacketContents(requisition=ctx.job.requisition_id,
                          destination=PacketDestination(url=f"mailto:{msg.to[0]}", domain=domain, verified=verified),
                          sending_identity=ctx.sending_identity, email=email, channel="email",
                          message_kind=msg.kind)  # type: ignore[arg-type]


async def approve(session: AsyncSession, msg: OutboundMessage, *, actor: str,
                  now: datetime | None = None) -> ApplicationPacket:
    """Snapshot and approve ``msg``. Refused (``SendError``) unless it is a draft whose checks all pass or
    only warn."""
    now = now or utcnow()
    if msg.status not in ("draft", "approved"):
        raise SendError(f"a {msg.status} message cannot be approved", "message_not_draft")
    why = await locked(session, msg)
    if why:
        raise SendError(why, "already_handed_over")
    ctx = await recheck_message(session, msg, now=now)
    if worst(msg.check_results) == "block":
        code = "message_questions" if msg.questions else "check_blocking"
        raise SendError("the checks block this message", code, results=[r.model_dump() for r in msg.check_results])
    app = ctx.app
    previous = await session.get(ApplicationPacket, msg.packet_id) if msg.packet_id else None
    built = await packets.build_message(session, app, contents_for(msg, ctx), previous, actor=actor, now=now)
    packet = built.packet
    packet.approved_at, packet.approved_by = now, actor
    msg.packet_id, msg.status = packet.id, "approved"
    await session.flush()
    await stages.add_event(session, app.id, "message_approved", actor, {
        "message_id": str(msg.id), "kind": msg.kind, "packet_hash": packet.content_hash, "recipients": msg.to})
    await audit.record(session, actor=actor, action="message.approved", subject_type="application",
                       subject_id=app.id, detail={"message_id": str(msg.id), "kind": msg.kind,
                                                  "packet_id": str(packet.id), "packet_hash": packet.content_hash,
                                                  "recipients": msg.to, "automatic": actor == AUTO_ACTOR})
    return packet


async def withdraw_approval(session: AsyncSession, msg: OutboundMessage, *, actor: str, reason: str,
                            now: datetime | None = None) -> None:
    """Back to draft: the packet is retired and its permits revoked (used by edits and the wind-down)."""
    now = now or utcnow()
    packet = await session.get(ApplicationPacket, msg.packet_id) if msg.packet_id else None
    if packet is not None and packet.invalidated_at is None:
        packet.invalidated_at, packet.invalidated_reason = now, reason
        await permits.revoke(session, packet_id=packet.id, reason=reason, actor=actor, now=now)
    if msg.status == "approved":
        msg.status = "draft"
    await session.flush()


# ----- gates ---------------------------------------------------------------------------------------


def _g(name: str, ok: bool | None, detail: str) -> GateResult:
    outcome = "unknown" if ok is None else "pass" if ok else "fail"
    return GateResult(gate=name, passed=outcome == "pass", outcome=outcome, detail=detail)


async def _follow_up_counts(session: AsyncSession, msg: OutboundMessage, now: datetime, tz: str,
                            exclude: uuid.UUID | None) -> tuple[int, int]:
    """(follow-ups sent or in flight for this application, automatic message sends today)."""
    base = (select(DispatchAttempt, OutboundMessage).join(OutboundMessage, OutboundMessage.packet_id
                                                          == DispatchAttempt.packet_id)
            .where(DispatchAttempt.status.in_((*OPEN, *GONE))))
    if exclude is not None:
        base = base.where(DispatchAttempt.id != exclude)
    rows = (await session.execute(base)).all()
    per_app = len({m.id for a, m in rows if m.application_id == msg.application_id and m.kind == "follow_up"
                   and m.id != msg.id})
    day, _ = gates.window_starts(now, tz)
    today = sum(1 for a, m in rows if m.automatic and a.created_at is not None and a.created_at >= day)
    return per_app, today


async def message_gates(session: AsyncSession, msg: OutboundMessage, packet: ApplicationPacket | None, *,
                        now: datetime, attempt_id: uuid.UUID | None = None) -> list[GateResult]:
    """Every gate a message send must pass (unknown is never a pass)."""
    app = await session.get(Application, msg.application_id)
    assert app is not None
    values = await settings_service.values(session)
    ctx = await ctx_mod.load(session, app)
    auto = packet is not None and is_automatic(packet)
    winddown = await active_wind_down(session)
    owner_in_winddown = winddown is not None and not auto
    out: list[GateResult] = []

    paused = await dispatch.is_paused(session)
    out.append(_g("global_pause", not paused or owner_in_winddown,
                  "running" if not paused else "paused; an owner-approved message may go during a wind-down"
                  if owner_in_winddown else "autopilot is paused"))
    campaign = await dispatch.campaign_pause(session, app)
    out.append(_g("campaign_paused", campaign is None or owner_in_winddown, campaign or "campaign not paused"))
    current = (packet is not None and packet.invalidated_at is None and msg.packet_id == packet.id
               and msg.status == "approved")
    out.append(_g("message_current", current, f"packet v{packet.version}" if current and packet else
                  "this message changed or was withdrawn after approval"))
    out.append(_g("approval_bound", packet is not None and packet.approved_at is not None,
                  f"approved by {packet.approved_by}" if packet is not None and packet.approved_at else "not approved"))
    fresh = checks.is_checked(msg) and worst(msg.check_results) != "block"
    out.append(_g("message_checks", fresh, "checks pass" if fresh else "checks block or are out of date"))
    known = {a.lower() for a in [*msg.known_recipients, *msg.confirmed_recipients]}
    unknown = [a for a in [*msg.to, *msg.cc] if a.lower() not in known]
    out.append(_g("recipient_known", bool(msg.to) and not unknown,
                  "recipients confirmed" if msg.to and not unknown else f"not confirmed: {', '.join(unknown) or '-'}"))
    quiet = dispatch.quiet_hours_end(values, now)
    if quiet == "unknown":
        out.append(_g("quiet_hours", None, "quiet hours or the time zone are not known"))
    elif auto and quiet is not None:
        out.append(_g("quiet_hours", False, "inside quiet hours: an automatic follow-up waits"))
    else:
        out.append(_g("quiet_hours", True,
                      "outside quiet hours" if quiet is None else "the send waits for them to end"))
    if auto:
        out += await _auto_gates(session, msg, ctx, values, now=now, attempt_id=attempt_id)
    return out


async def _auto_gates(session: AsyncSession, msg: OutboundMessage, ctx: MessageContext, values: dict[str, Any], *,
                      now: datetime, attempt_id: uuid.UUID | None) -> list[GateResult]:
    out = [_g("auto_follow_ups", bool(values["followups.auto_send"]),
              "automatic follow-ups are on" if values["followups.auto_send"] else "automatic follow-ups are off"),
           _g("plain_follow_up", msg.kind == "follow_up" and msg.automatic,
              "plain no-reply follow-up" if msg.kind == "follow_up" else f"a {msg.kind} message is never automatic")]
    sent_to = set(ctx.sent_to)
    targets = {a.lower() for a in [*msg.to, *msg.cc]}
    if not sent_to:
        out.append(_g("recipient_sent_before", None, "the address the application went to is not known"))
    else:
        out.append(_g("recipient_sent_before", bool(targets) and targets <= sent_to,
                      "same address as the application" if targets and targets <= sent_to
                      else f"not an address the application was sent to: {', '.join(sorted(targets - sent_to))}"))
    replied = ctx.employer_replied or ctx.app.stage != Stage.submitted
    out.append(_g("employer_reply", not replied, "no reply from the employer" if not replied else
                  f"the employer has replied (stage {ctx.app.stage.value}, {len(ctx.threads)} linked thread(s))"))
    per_app, today = await _follow_up_counts(session, msg, now, str(values["general.timezone"]), attempt_id)
    limit, daily = int(values["followups.max_per_application"]), int(values["followups.auto_daily_cap"])
    out.append(_g("followup_cap", per_app < limit and today < daily,
                  f"{per_app} of {limit} follow-ups for this application, {today} of {daily} automatic today"))
    return out


def failures(results: list[GateResult]) -> list[GateResult]:
    return [g for g in results if g.outcome != "pass"]


# ----- queue, recheck, cancel ----------------------------------------------------------------------


async def queue(session: AsyncSession, msg: OutboundMessage, *, actor: str,
                now: datetime | None = None) -> QueueOutcome:
    """Permit and attempt in the caller's transaction (the caller commits); the worker sends after the delay."""
    from app.apply import errors

    now = now or utcnow()
    await permits.lock_permits(session)
    packet = await session.get(ApplicationPacket, msg.packet_id) if msg.packet_id else None
    if packet is None:
        return QueueOutcome("denied", "the message is not approved", code="not_approved")
    if await locked(session, msg):
        return QueueOutcome("denied", "this message has already been queued or sent", code="duplicate")
    results = await message_gates(session, msg, packet, now=now)
    result = await permits.grant_message(session, packet, results, actor=actor, now=now)
    if not result.granted or result.permit is None:
        return QueueOutcome("denied", result.reason, None, result.gates,
                            errors.for_gate_results(result.gates, result.reason))
    permit = await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel="email",
                                   actor=actor, now=now)
    delay = int(await settings_service.get_value(session, "automation.email_send_delay_minutes"))
    attempt = DispatchAttempt(application_id=msg.application_id, packet_id=packet.id, packet_hash=packet.content_hash,
                              channel=Channel.email, permit_id=permit.id, status=DispatchStatus.reserved,
                              send_after=now + timedelta(minutes=delay), gate_results=permit.checks)
    session.add(attempt)
    await session.flush()
    await outcomes._log(session, attempt, "dispatch.reserved", actor, message_id=str(msg.id), message_kind=msg.kind,
                        approved_by=packet.approved_by, send_after=attempt.send_after.isoformat(), gates=result.gates)
    return QueueOutcome("queued", "queued: it goes after the send delay", attempt, result.gates)


async def recheck(session: AsyncSession, attempt: DispatchAttempt, app: Application, packet: ApplicationPacket, *,
                  now: datetime) -> list[dict[str, Any]]:
    """The gates again at dispatch (called by ``dispatch.recheck`` for a message packet)."""
    msg = await session.scalar(select(OutboundMessage).where(OutboundMessage.packet_id == packet.id))
    if msg is None:
        return [{"gate": "message_current", "passed": False, "outcome": "fail",
                 "detail": "fail: the message for this packet is gone"}]
    results = await message_gates(session, msg, packet, now=now, attempt_id=attempt.id)
    return [{"gate": g.gate, "passed": False, "outcome": g.outcome, "detail": f"fail: {g.detail}"}
            for g in failures(results)]


async def cancel(session: AsyncSession, msg: OutboundMessage, *, actor: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    rows = await attempts(session, msg)
    if not rows:
        raise SendError("nothing is queued for this message", "still_queued", 409)
    attempt = rows[-1]
    app = await outcomes.lock_application(session, msg.application_id)
    try:
        await outcomes.cancel(session, attempt, app, "cancelled by the owner", actor=actor, now=now)
    except outcomes.OutcomeError as exc:
        raise SendError(exc.message, exc.code) from exc


async def automatic_sends_today(session: AsyncSession, now: datetime) -> int:
    tz = str(await settings_service.get_value(session, "general.timezone"))
    day, _ = gates.window_starts(now, tz)
    return int(await session.scalar(
        select(func.count()).select_from(DispatchAttempt)
        .join(OutboundMessage, OutboundMessage.packet_id == DispatchAttempt.packet_id)
        .where(OutboundMessage.automatic.is_(True), DispatchAttempt.created_at >= day,
               DispatchAttempt.status.in_((*OPEN, *GONE)))) or 0)
