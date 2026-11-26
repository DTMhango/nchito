"""Dispatch: an approved, current packet through permit, attempt, channel and outcome (DESIGN.md 8.1,
8.2, 8.5, 18.1-18.3). Invariants, never settings:

- **Permit, then attempt, in one transaction.** :func:`queue` asks for a submit permit (every gate, under
  the permit lock), consumes it and writes the ``DispatchAttempt`` (which reserves the caps) in the same
  transaction. Two workers cannot both create an attempt for one application: the second waits on the
  lock and then finds the first attempt (duplicate gate).
- **Rechecked at dispatch**, after the send delay (18.2): pause, packet still current and approved, packet
  sources unchanged (answers, files, recipient, posting: a changed pay answer means the old packet cannot
  go out), expiry, duplicates, the employer group and the caps. Any failure cancels the attempt before
  anything is handed over.
- **In flight is durable.** ``started_at`` is committed before the channel is called, and only an attempt
  with no ``started_at`` can be claimed (atomically, ``SKIP LOCKED``). An attempt left started with no
  outcome (a worker died) becomes uncertain after ``reconcile.in_flight_timeout_minutes``: it is
  reconciled, never resent, so a restart resumes without duplicates.
- **Uncertain is never resent.** A channel exception after the hand-over is ``unknown``; ``unknown`` is
  settled only by ``Channel.reconcile`` or the owner (``apply.reconcile``).
- **Bounded retry for definite failures only.** A channel's ``failed`` (nothing left) is retried at most
  ``automation.dispatch_max_retries`` times, each with a new permit and a new attempt.
- **Nothing dispatches while paused** (including paused after a restore from backup).
- The server sends on its own only through server-enforced channels (18.1): ``AUTO_DISPATCH_CHANNELS``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import approval, gates, outcomes, packets, permits
from app.apply.channels import registry
from app.apply.channels.base import DispatchOutcome, DispatchRequest
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
from app.models.search import Availability, Job
from app.pipeline import conflicts

AUTO_DISPATCH_CHANNELS = frozenset({"email"})

OpenChecker = Callable[[AsyncSession, Job], Awaitable[Any]]


async def _default_open_check(session: AsyncSession, job: Job) -> None:
    from app.pipeline import orchestrator

    await orchestrator.check_job_open(session, job)


_open_checker: OpenChecker = _default_open_check


def set_open_checker(checker: OpenChecker | None) -> None:
    """Replace the posting open-check used before an automatic send (tests inject a fake)."""
    global _open_checker
    _open_checker = checker or _default_open_check


class DispatchError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class QueueResult:
    status: str  # queued | wait_for_owner | denied
    reason: str
    attempt: DispatchAttempt | None = None
    gates: list[dict[str, Any]] = field(default_factory=list)
    pending_action_id: uuid.UUID | None = None

    @property
    def queued(self) -> bool:
        return self.status == "queued"


async def is_paused(session: AsyncSession) -> bool:
    return bool(await settings_service.get_value(session, "automation.paused"))


async def _refused(session: AsyncSession, app: Application, reason: str, actor: str) -> QueueResult:
    await audit.record(session, actor=actor, action="dispatch.refused", subject_type="application",
                       subject_id=app.id, detail={"reason": reason})
    return QueueResult("denied", reason)


async def failed_count(session: AsyncSession, app_id: uuid.UUID, packet_hash: str) -> int:
    return int(await session.scalar(select(func.count()).select_from(DispatchAttempt).where(
        DispatchAttempt.application_id == app_id, DispatchAttempt.packet_hash == packet_hash,
        DispatchAttempt.status == DispatchStatus.failed)) or 0)


async def _fresh_open_check(session: AsyncSession, packet: ApplicationPacket, job: Job, now: datetime) -> None:
    """Automatic approvals need the role confirmed open recently: recheck it before asking for a permit."""
    if not (packet.approved_by or "").startswith("system"):
        return
    hours = int(await settings_service.get_value(session, "automation.open_check_max_age_hours"))
    if job.last_checked_at is None or job.last_checked_at < now - timedelta(hours=hours):
        await _open_checker(session, job)
        await session.flush()


async def queue(session: AsyncSession, application_id: uuid.UUID, *, actor: str = "system",
                runner_token_id: uuid.UUID | None = None, automatic_retry: bool = False,
                now: datetime | None = None) -> QueueResult:
    """Permit request, then permit consumption and the attempt, in the caller's transaction (the caller
    commits). ``wait_for_owner`` raises the owner's approval request."""
    now = now or utcnow()
    app = await session.get(Application, application_id)
    if app is None:
        raise DispatchError("application not found", 404)
    packet = await packets.current(session, app.id)
    if packet is None:
        return await _refused(session, app, "no current packet", actor)
    channel = packet.contents.channel or (app.channel.value if app.channel else None)
    if channel is None or not registry.is_available(channel):
        return await _refused(session, app, f"no {channel or 'channel'} channel is available in this build", actor)
    if automatic_retry:
        limit = int(await settings_service.get_value(session, "automation.dispatch_max_retries"))
        failures = await failed_count(session, app.id, packet.content_hash)
        if failures > limit:
            return await _refused(session, app, f"send failed {failures} time(s); retry limit is {limit}", actor)
    job = await session.get(Job, app.job_id)
    assert job is not None
    await _fresh_open_check(session, packet, job, now)

    result = await permits.request(session, app.id, packet_hash=packet.content_hash, channel=channel,
                                   runner_token_id=runner_token_id, actor=actor, now=now)
    if result.status == "wait_for_owner":
        action = await approval.request_owner_approval(session, app, packet, result.reason)
        return QueueResult("wait_for_owner", result.reason, None, result.gates, action.id)
    if not result.granted or result.permit is None:
        return QueueResult("denied", result.reason, None, result.gates)
    permit = await permits.consume(session, result.permit.id, packet_hash=packet.content_hash, channel=channel,
                                   runner_token_id=runner_token_id, actor=actor, now=now)
    delay = 0
    if channel == "email" and not automatic_retry:
        delay = int(await settings_service.get_value(session, "automation.email_send_delay_minutes"))
    attempt = DispatchAttempt(application_id=app.id, packet_id=packet.id, packet_hash=packet.content_hash,
                              channel=Channel(channel), permit_id=permit.id, status=DispatchStatus.reserved,
                              send_after=now + timedelta(minutes=delay), gate_results=permit.checks)
    session.add(attempt)
    await session.flush()
    await outcomes._log(session, attempt, "dispatch.reserved", actor, packet_version=packet.version,
                        approved_by=packet.approved_by, runner_token_id=str(runner_token_id) if runner_token_id
                        else None, send_after=attempt.send_after.isoformat() if attempt.send_after else None,
                        retry=automatic_retry, gates=result.gates)
    return QueueResult("queued", result.reason, attempt, result.gates)


# ----- dispatch-time recheck ---------------------------------------------------------------------


def _draft_from(contents: Any) -> packets.PacketDraft:
    return packets.PacketDraft(
        channel=contents.channel, destination_url="" if contents.channel == "email" else contents.destination.url,
        sending_identity=contents.sending_identity,
        answers=[packets.DraftAnswer(question=a.question, answer_id=uuid.UUID(a.answer_id)) if a.answer_id
                 else packets.DraftAnswer(question=a.question, value=a.value) for a in contents.answers],
        email=contents.email, files=list(contents.files), link_permissions=list(contents.link_permissions),
        requisition=contents.requisition)


async def _sources_changed(session: AsyncSession, app: Application, packet: ApplicationPacket) -> list[str] | None:
    """Rebuild the packet from its sources now; the paths that differ, or None when it is unchanged."""
    try:
        fresh = await packets.assemble(session, app, _draft_from(packet.contents))
    except packets.PacketError as exc:
        return [exc.message]
    if packets.content_hash(fresh) == packet.content_hash:
        return None
    return [c["path"] for c in packets.diff(packet.contents, fresh)] or ["contents"]


async def recheck(session: AsyncSession, attempt: DispatchAttempt, app: Application, *, now: datetime
                  ) -> tuple[list[dict[str, Any]], list[str] | None]:
    """The gates rechecked at dispatch. Returns (failures, changed packet paths)."""
    failures: list[dict[str, Any]] = []

    def fail(gate: str, reason: str) -> None:
        failures.append({"gate": gate, "passed": False, "outcome": "fail", "detail": f"fail: {reason}"})

    if await is_paused(session):
        fail("global_pause", "autopilot is paused")
    packet = await session.get(ApplicationPacket, attempt.packet_id)
    current = await packets.current(session, app.id)
    changed = None
    if packet is None or current is None or current.id != attempt.packet_id \
            or current.content_hash != attempt.packet_hash:
        fail("packet_current", "the packet was replaced after it was queued")
    elif app.approved_packet_id != packet.id or packet.approved_at is None:
        fail("approval_bound", "the approval no longer covers this packet")
    else:
        changed = await _sources_changed(session, app, packet)
        if changed:
            fail("packet_sources", f"changed since approval: {', '.join(changed)}")
    job = await session.get(Job, app.job_id)
    assert job is not None
    if job.availability == Availability.closed:
        fail("role_open", "the posting is closed")
    if job.deadline is not None and job.deadline < now.date():
        fail("deadline", f"the deadline {job.deadline} has passed")
    outcome, reason = await gates.duplicate_check(session, app, job, exclude_attempt_id=attempt.id)
    if outcome != "pass":
        fail("duplicate", reason)
    conflict = await conflicts.check_conflict_at_submit(session, app, now=now, claim=False)
    if conflict.outcome != "pass":
        fail("employer_conflict", conflict.reason)
    if attempt.channel != Channel.manual:
        values = await settings_service.values(session)
        counts = await gates.sent_counts(session, now, values["general.timezone"])  # includes this attempt
        if counts["sent_today"] > int(values["automation.daily_cap"]):
            fail("daily_cap", f"{counts['sent_today']} sends today exceeds the cap {values['automation.daily_cap']}")
        if counts["sent_week"] > int(values["automation.weekly_cap"]):
            fail("weekly_cap", f"{counts['sent_week']} sends this week exceeds the cap "
                               f"{values['automation.weekly_cap']}")
    return failures, changed


async def _claim(session: AsyncSession, attempt_id: uuid.UUID, now: datetime) -> DispatchAttempt | None:
    return await session.scalar(
        select(DispatchAttempt).where(DispatchAttempt.id == attempt_id,
                                      DispatchAttempt.status == DispatchStatus.reserved,
                                      DispatchAttempt.started_at.is_(None))
        .with_for_update(skip_locked=True).execution_options(populate_existing=True))


async def run(session: AsyncSession, attempt_id: uuid.UUID, *, now: datetime | None = None) -> DispatchStatus | None:
    """Send one reserved attempt when it is due. Commits in three steps: the recheck and the in-flight
    marker, the channel call (outside any transaction), the outcome. Returns the recorded status, or None
    when the attempt is not due, already taken or already done."""
    now = now or utcnow()
    attempt = await _claim(session, attempt_id, now)
    if attempt is None or (attempt.send_after is not None and attempt.send_after > now):
        await session.commit()
        return None
    app = await outcomes.lock_application(session, attempt.application_id)
    failures, changed = await recheck(session, attempt, app, now=now)
    if failures:
        if changed:
            packet = await session.get(ApplicationPacket, attempt.packet_id)
            assert packet is not None
            await packets.invalidate(session, app, packet, f"changed during the send delay: {', '.join(changed)}",
                                     actor="system", now=now)
        reason = "; ".join(f["detail"].removeprefix("fail: ") for f in failures)
        await outcomes.cancel(session, attempt, app, reason, actor="system", now=now, gates=failures)
        await session.commit()
        return DispatchStatus.cancelled
    attempt.started_at = now
    await session.flush()
    await outcomes._log(session, attempt, "dispatch.started", "system")
    packet = await session.get(ApplicationPacket, attempt.packet_id)
    assert packet is not None
    request = DispatchRequest(attempt_id=str(attempt.id), application_id=str(app.id),
                              packet_hash=attempt.packet_hash, packet=packet.contents)
    channel_name = attempt.channel.value
    await session.commit()  # durable: from here on the attempt is in flight and is never claimed again

    try:
        channel = await registry.get(session, channel_name)
    except Exception as exc:  # nothing was handed over: a definite failure
        outcome = DispatchOutcome(status="failed", error=f"channel unavailable: {exc}")
    else:
        try:
            outcome = await channel.dispatch(request)
        except Exception as exc:  # the channel may already have handed it over: uncertain, never resent
            outcome = DispatchOutcome(status="unknown", error=f"{type(exc).__name__}: {exc}"[:2000])

    attempt = await session.get(DispatchAttempt, attempt_id, populate_existing=True)
    assert attempt is not None
    status = await outcomes.record(session, attempt, outcome, via="dispatch", actor=f"channel:{channel_name}",
                                   now=now)
    if status == DispatchStatus.failed:
        await _after_failure(session, attempt, now=now)
    await session.commit()
    return status


async def _after_failure(session: AsyncSession, attempt: DispatchAttempt, *, now: datetime) -> None:
    """A definite failure: a bounded retry with a new permit and a new attempt, or the claim goes back."""
    retry = None
    if not await is_paused(session):
        retry = await queue(session, attempt.application_id, actor="system", automatic_retry=True, now=now)
    if retry is not None and retry.queued and retry.attempt is not None:
        await outcomes._log(session, attempt, "dispatch.retry_queued", "system", retry_attempt_id=str(retry.attempt.id))
        return
    app = await outcomes.lock_application(session, attempt.application_id)
    why = f"send failed: {attempt.error}" + (f"; not retried: {retry.reason}" if retry is not None else "")
    await outcomes._log(session, attempt, "dispatch.gave_up", "system", reason=why)
    await outcomes.give_back(session, app, attempt, why, now=now)


# ----- the periodic tick -------------------------------------------------------------------------


async def mark_stale_in_flight(session: AsyncSession, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Attempts started with no outcome for too long (a worker died mid-send) become uncertain."""
    now = now or utcnow()
    minutes = int(await settings_service.get_value(session, "reconcile.in_flight_timeout_minutes"))
    rows = (await session.scalars(select(DispatchAttempt).where(
        DispatchAttempt.status == DispatchStatus.reserved, DispatchAttempt.started_at.is_not(None),
        DispatchAttempt.started_at <= now - timedelta(minutes=minutes))
        .with_for_update(skip_locked=True))).all()
    for attempt in rows:
        await outcomes.record(session, attempt, DispatchOutcome(
            status="unknown", error="no outcome recorded: the worker stopped while sending; it will be reconciled, "
                                    "never resent"), via="restart", actor="system", now=now)
    return [a.id for a in rows]


async def queue_approved(session: AsyncSession, *, now: datetime | None = None) -> list[QueueResult]:
    """Queue every ready application whose current packet is approved for a server-sent channel and has
    never had an attempt (a cancelled, failed or reconciled attempt is not requeued automatically)."""
    now = now or utcnow()
    apps = (await session.scalars(select(Application).where(
        Application.stage == Stage.ready, Application.approved_packet_id.is_not(None)))).all()
    results = []
    for app in apps:
        packet = await packets.current(session, app.id)
        if packet is None or packet.id != app.approved_packet_id \
                or packet.contents.channel not in AUTO_DISPATCH_CHANNELS:
            continue
        tried = await session.scalar(select(DispatchAttempt.id).where(
            DispatchAttempt.application_id == app.id, DispatchAttempt.packet_hash == packet.content_hash).limit(1))
        if tried is not None:
            continue
        results.append(await queue(session, app.id, actor="system", now=now))
        await session.commit()
    return results


async def due_attempts(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    return list((await session.scalars(select(DispatchAttempt.id).where(
        DispatchAttempt.status == DispatchStatus.reserved, DispatchAttempt.started_at.is_(None),
        DispatchAttempt.send_after <= now).order_by(DispatchAttempt.send_after))).all())


@dataclass
class TickReport:
    released: list[uuid.UUID] = field(default_factory=list)
    uncertain: list[uuid.UUID] = field(default_factory=list)
    queued: list[QueueResult] = field(default_factory=list)
    sent: dict[uuid.UUID, str] = field(default_factory=dict)
    reconciled: dict[uuid.UUID, str] = field(default_factory=dict)


async def tick(session: AsyncSession, *, now: datetime | None = None, max_rounds: int = 3) -> TickReport:
    """One pass of the apply loop (every minute, from the worker). Commits as it goes."""
    from app.apply import reconcile

    now = now or utcnow()
    report = TickReport()
    report.released = await permits.release_stale_claims(session, now=now)
    report.uncertain = await mark_stale_in_flight(session, now=now)
    await session.commit()
    if not await is_paused(session):
        report.queued = await queue_approved(session, now=now)
        for _ in range(max_rounds):  # a definite failure may queue its retry; run it in the same tick
            due = [a for a in await due_attempts(session, now) if a not in report.sent]
            if not due:
                break
            for attempt_id in due:
                status = await run(session, attempt_id, now=now)
                if status is not None:
                    report.sent[attempt_id] = status.value
    report.reconciled = await reconcile.reconcile_due(session, now=now)
    await session.commit()
    return report
