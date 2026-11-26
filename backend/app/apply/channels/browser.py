"""Browser channel (DESIGN.md 8.2, 8.3, 18.1): a runner fills the form on the posting's site. Enforcement is
**instructed and audited**: the server cannot stop a click, so every step before and after it is recorded and
bounded. Invariants, not settings:

- **No send without a consumed permit for this packet hash.** The permit is consumed when the runner calls
  ``request_submit_permit`` (the gateway calls ``dispatch.queue(..., runner_token_id=token)``, which consumes it
  and writes the ``DispatchAttempt`` in one transaction). Until then there is only a *task*: the approved packet
  waiting for a runner (:func:`queue_task`). ``BrowserChannel.dispatch`` refuses (``failed``, nothing handed over)
  unless the attempt's permit is consumed, bound to the same packet hash and held by a claimed task.
- **Flow.** (1) ``dispatch.queue(app)`` without a runner token, or :func:`queue_approved_tasks` for an approved
  browser packet, creates the ``AgentTask``. (2) The gateway hands it to a runner (:func:`mark_task_claimed`).
  (3) At Submit the runner asks for a permit; the gateway calls ``dispatch.queue(app, runner_token_id=...)`` then
  ``dispatch.run(attempt_id)``, which rechecks the gates and calls :meth:`BrowserChannel.dispatch`. A ``handed_off``
  attempt means **cleared: the runner may click Submit**; a ``cancelled`` attempt means refused. (4) The runner
  reports; the gateway calls :func:`record_result`.
- **The attempt is in flight until the runner reports.** ``handed_off`` is uncertain: it keeps the duplicate and
  employer locks and is settled by :func:`record_result`, :meth:`BrowserChannel.reconcile` (runner evidence, a
  confirmation email matched by mail sync) or the owner. **An uncertain attempt is never given to a runner to
  submit again**: no task is queued, claimed or cleared for an application with an open or sent attempt.
- **Evidence or it did not happen.** ``submitted`` without evidence is ``unknown``. ``failed`` is the runner's
  word that nothing was submitted; it settles as not sent (back to ``ready``) and is never retried automatically.
- A report for an attempt with no consumed permit raises :class:`UnpermittedReport` (the gateway suspends the
  token, 18.1); nothing is recorded as sent.

Interface the gateway calls: :func:`queue_task` / :func:`queue_approved_tasks`, :func:`mark_task_claimed`,
:func:`record_result`, :func:`evidence_from_report`, :func:`expire_stale_tasks`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import outcomes, packets
from app.apply.channels import registry
from app.apply.channels.base import ChannelName, DispatchOutcome, DispatchRequest, Enforcement
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    Application,
    Channel,
    DispatchAttempt,
    DispatchStatus,
    MailClassification,
    MailThread,
    Stage,
    SubmitPermit,
)
from app.schemas.json_types import Evidence

ReportedOutcome = Literal["submitted", "uncertain", "failed"]
OPEN_TASK = (AgentTaskStatus.queued, AgentTaskStatus.claimed, AgentTaskStatus.blocked)
# What counts as proof from a runner (the owner's own mark and a sent-mail id are other channels' evidence).
RUNNER_EVIDENCE = frozenset({"confirmation_page", "reference", "confirmation_email"})


class BrowserError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = "refused") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code  # app.apply.errors.CODES, plus ``no_permit``


class UnpermittedReport(BrowserError):
    """A runner reported on an attempt with no consumed permit for this packet (18.1 "Detection")."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 403, "no_permit")


# ----- tasks ------------------------------------------------------------------------------------


async def _open_tasks(session: AsyncSession, app_id: uuid.UUID) -> list[AgentTask]:
    return list((await session.scalars(select(AgentTask).where(
        AgentTask.application_id == app_id, AgentTask.type == AgentTaskType.apply,
        AgentTask.status.in_(OPEN_TASK)).with_for_update())).all())


async def _blocking_attempt(session: AsyncSession, app_id: uuid.UUID) -> DispatchAttempt | None:
    """An attempt that forbids handing the application to a runner: open (in flight or uncertain) or sent."""
    return await session.scalar(select(DispatchAttempt).where(
        DispatchAttempt.application_id == app_id,
        DispatchAttempt.status.in_([*outcomes.OPEN_STATUSES, DispatchStatus.sent, DispatchStatus.acknowledged]))
        .order_by(DispatchAttempt.created_at.desc()).limit(1))


async def queue_task(session: AsyncSession, application_id: uuid.UUID, *, actor: str = "system",
                     now: datetime | None = None) -> AgentTask:
    """Queue the runner task for the approved, current browser packet (idempotent per packet hash). Takes no
    permit and sends nothing. The caller commits."""
    from app.apply import dispatch  # dispatch imports this module lazily through the registry

    now = now or utcnow()
    app = await outcomes.lock_application(session, application_id)
    if await dispatch.is_paused(session):
        raise BrowserError("autopilot is paused", 409, "paused")
    packet = await packets.current(session, app.id)
    if packet is None:
        raise BrowserError("no current packet", 409, "no_packet")
    if packet.contents.channel != "browser":
        raise BrowserError(f"the packet is for {packet.contents.channel}, not the browser", 409, "channel_mismatch")
    if app.approved_packet_id != packet.id or packet.approved_at is None:
        raise BrowserError("the current packet is not approved", 409, "not_approved")
    if not packet.contents.destination.verified:
        raise BrowserError(f"{packet.contents.destination.domain} is not confirmed as the posting's own site", 409,
                           "destination_unverified")
    blocking = await _blocking_attempt(session, app.id)
    if blocking is not None:
        raise BrowserError(f"an earlier send is {blocking.status.value}: it is reconciled, never given to a runner "
                           "again", 409, "already_handed_over")
    if app.stage != Stage.ready:
        raise BrowserError(f"an application in {app.stage.value} cannot be handed to a runner", 409, "illegal_stage")
    existing = None
    for task in await _open_tasks(session, app.id):
        if task.payload.get("packet_hash") == packet.content_hash:
            existing = task
        else:  # built for an older packet: withdraw it
            await _end_task(session, task, AgentTaskStatus.cancelled, {"reason": "the packet changed"}, now)
    if existing is not None:
        return existing
    max_steps = int(await settings_service.get_value(session, "automation.agent_max_steps"))
    task = AgentTask(type=AgentTaskType.apply, application_id=app.id, status=AgentTaskStatus.queued,
                     payload={"packet_id": str(packet.id), "packet_version": packet.version,
                              "packet_hash": packet.content_hash, "destination_url": packet.contents.destination.url,
                              "destination_domain": packet.contents.destination.domain, "max_steps": max_steps,
                              "queued_at": now.isoformat()})
    session.add(task)
    await session.flush()
    await audit.record(session, actor=actor, action="browser.task_queued", subject_type="agent_task",
                       subject_id=task.id, detail={"application_id": str(app.id), "packet_hash": packet.content_hash,
                                                   "domain": packet.contents.destination.domain})
    return task


async def queue_approved_tasks(session: AsyncSession, *, now: datetime | None = None) -> list[AgentTask]:
    """A task for every ready application whose approved current packet is for the browser and has no task or
    attempt yet. Commits each. The permit is still asked for, and every gate rechecked, at Submit."""
    now = now or utcnow()
    apps = (await session.scalars(select(Application).where(
        Application.stage == Stage.ready, Application.approved_packet_id.is_not(None)))).all()
    queued: list[AgentTask] = []
    for app in apps:
        packet = await packets.current(session, app.id)
        if packet is None or packet.id != app.approved_packet_id or packet.contents.channel != "browser":
            continue
        tried = await session.scalar(select(DispatchAttempt.id).where(
            DispatchAttempt.application_id == app.id, DispatchAttempt.packet_hash == packet.content_hash).limit(1))
        had_task = await session.scalar(select(AgentTask.id).where(
            AgentTask.application_id == app.id, AgentTask.payload["packet_hash"].astext == packet.content_hash,
            AgentTask.type == AgentTaskType.apply).limit(1))
        if tried is not None or had_task is not None:
            continue
        try:
            queued.append(await queue_task(session, app.id, now=now))
        except BrowserError:
            await session.rollback()
            continue
        await session.commit()
    return queued


async def _end_task(session: AsyncSession, task: AgentTask, status: AgentTaskStatus, result: dict[str, Any],
                    now: datetime) -> None:
    task.status, task.result = status, {**result, "at": now.isoformat()}
    await session.flush()
    await audit.record(session, actor="system", action=f"browser.task_{status.value}", subject_type="agent_task",
                       subject_id=task.id, detail={"application_id": str(task.application_id), **result})


async def withdraw_unclaimed_tasks(session: AsyncSession, application_id: uuid.UUID, reason: str, *,
                                   now: datetime) -> int:
    """Withdraw tasks no runner has claimed (an uncertain or sent attempt means no runner is asked again)."""
    count = 0
    for task in await _open_tasks(session, application_id):
        if task.status == AgentTaskStatus.queued:
            await _end_task(session, task, AgentTaskStatus.cancelled, {"reason": reason}, now)
            count += 1
    return count


async def expire_stale_tasks(session: AsyncSession, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Withdraw queued tasks no runner claimed within ``runners.browser_task_expiry_hours``. The approved packet
    stays; the next worker pass queues a new task."""
    now = now or utcnow()
    hours = int(await settings_service.get_value(session, "runners.browser_task_expiry_hours"))
    rows = (await session.scalars(select(AgentTask).where(
        AgentTask.type == AgentTaskType.apply, AgentTask.status == AgentTaskStatus.queued)
        .with_for_update(skip_locked=True))).all()
    expired = []
    for task in rows:
        queued_at = task.payload.get("queued_at")
        if queued_at and datetime.fromisoformat(queued_at) <= now - timedelta(hours=hours):
            await _end_task(session, task, AgentTaskStatus.cancelled, {"reason": f"no runner claimed it in {hours} h",
                                                                       "expired": True}, now)
            expired.append(task.id)
    return expired


async def mark_task_claimed(session: AsyncSession, task_id: uuid.UUID, *, token_id: uuid.UUID | None,
                            now: datetime | None = None) -> AgentTask:
    """A runner takes a queued task. Refused (and the task withdrawn) when the application has an open or sent
    attempt: an uncertain send is never handed to a runner again. The caller commits."""
    now = now or utcnow()
    task = await session.scalar(select(AgentTask).where(AgentTask.id == task_id).with_for_update()
                                .execution_options(populate_existing=True))
    if task is None:
        raise BrowserError("task not found", 404, "not_found")
    if task.status != AgentTaskStatus.queued:
        raise BrowserError(f"the task is {task.status.value}", 409, "already_handed_over")
    if task.application_id is not None:
        blocking = await _blocking_attempt(session, task.application_id)
        if blocking is not None:
            await _end_task(session, task, AgentTaskStatus.cancelled,
                            {"reason": f"an earlier send is {blocking.status.value}"}, now)
            raise BrowserError(f"an earlier send is {blocking.status.value}: it is reconciled, never given to a "
                               "runner again", 409, "already_handed_over")
    task.status, task.claimed_by_token_id, task.claimed_at, task.heartbeat_at = (
        AgentTaskStatus.claimed, token_id, now, now)
    task.attempts += 1
    await session.flush()
    await audit.record(session, actor=f"runner:{token_id}" if token_id else "runner", action="browser.task_claimed",
                       subject_type="agent_task", subject_id=task.id,
                       detail={"application_id": str(task.application_id), "token_id": str(token_id)})
    return task


# ----- results ----------------------------------------------------------------------------------


def evidence_from_report(*, confirmation_text: str | None = None, reference: str | None = None,
                         screenshot_ref: str | None = None, now: datetime | None = None) -> Evidence | None:
    """Evidence from a runner's report: the reference if it gave one, else the confirmation text; None when
    it gave neither (the report is then uncertain)."""
    at = (now or utcnow()).isoformat()
    if reference and reference.strip():
        return Evidence(kind="reference", value=reference.strip()[:200], screenshot_ref=screenshot_ref, at=at)
    if confirmation_text and confirmation_text.strip():
        return Evidence(kind="confirmation_page", value=confirmation_text.strip()[:500],
                        screenshot_ref=screenshot_ref, at=at)
    return None


async def _task_for(session: AsyncSession, attempt: DispatchAttempt, permit: SubmitPermit | None,
                    task_id: uuid.UUID | None) -> AgentTask | None:
    ident = task_id or (permit.agent_task_id if permit else None)
    if ident is not None:
        return await session.get(AgentTask, ident)
    return await session.scalar(select(AgentTask).where(
        AgentTask.application_id == attempt.application_id, AgentTask.type == AgentTaskType.apply,
        AgentTask.payload["packet_hash"].astext == attempt.packet_hash).order_by(AgentTask.created_at.desc()).limit(1))


async def record_result(session: AsyncSession, attempt: DispatchAttempt, outcome: ReportedOutcome,
                        evidence: Evidence | None = None, *, task_id: uuid.UUID | None = None,
                        detail: str | None = None, actor: str = "runner", now: datetime | None = None
                        ) -> DispatchStatus:
    """Record what the runner reported for ``attempt``. ``submitted`` with runner evidence settles as sent;
    ``submitted`` without it, and ``uncertain``, hold the attempt for reconciliation (never resent); ``failed``
    settles as not sent (the role goes back to ready, nothing is retried). A report on a settled attempt changes
    nothing. The caller commits."""
    now = now or utcnow()
    if attempt.channel != Channel.browser:
        raise BrowserError("not a browser attempt", 409, "channel_mismatch")
    if attempt.status in outcomes.FINAL_STATUSES:
        await audit.record(session, actor=actor, action="browser.report_ignored", subject_type="dispatch_attempt",
                           subject_id=attempt.id, detail={"reported": outcome, "status": attempt.status.value})
        return attempt.status
    permit = await session.get(SubmitPermit, attempt.permit_id) if attempt.permit_id else None
    if permit is None or permit.used_at is None or permit.packet_hash != attempt.packet_hash:
        raise UnpermittedReport("no consumed permit for this packet: the report is not accepted")
    if attempt.status == DispatchStatus.reserved and attempt.started_at is None:
        raise UnpermittedReport("the attempt was never cleared to submit: the report is not accepted")
    task = await _task_for(session, attempt, permit, task_id)
    report = {"attempt_id": str(attempt.id), "outcome": outcome, "detail": detail, "reported_at": now.isoformat(),
              "evidence": evidence.model_dump() if evidence else None}
    if task is not None:
        task.result = report
        task.status = AgentTaskStatus.failed if outcome == "failed" else AgentTaskStatus.done
    if outcome == "failed":
        await outcomes.settle_not_sent(session, attempt, reason=detail or "the runner reported it did not submit",
                                       via="runner", actor=actor, now=now)
        return DispatchStatus.failed
    if outcome == "submitted" and evidence is not None and evidence.kind in RUNNER_EVIDENCE:
        status = await outcomes.record(session, attempt, DispatchOutcome(status="sent", evidence=evidence),
                                       via="runner", actor=actor, now=now)
    else:
        why = detail or ("the runner reported a submission without confirmation" if outcome == "submitted"
                         else "the runner is not sure the form was submitted")
        status = await outcomes.record(session, attempt, DispatchOutcome(status="unknown", error=why),
                                       via="runner", actor=actor, now=now)
        await withdraw_unclaimed_tasks(session, attempt.application_id, "an earlier send is uncertain", now=now)
    return status


# ----- the channel ------------------------------------------------------------------------------


@dataclass
class BrowserChannel:
    """Dispatch hands nothing over by itself: it clears the runner that already holds the task."""

    session: AsyncSession
    name: ClassVar[ChannelName] = "browser"
    enforcement: ClassVar[Enforcement] = "instructed"

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        session = self.session
        attempt = await session.get(DispatchAttempt, uuid.UUID(request.attempt_id), populate_existing=True)
        if attempt is None or attempt.channel != Channel.browser:
            return DispatchOutcome(status="failed", error="not a browser attempt")
        if not attempt.packet_hash == request.packet_hash == registry.packet_hash(request.packet):
            return DispatchOutcome(status="failed", error="the packet does not match its hash")
        permit = await session.get(SubmitPermit, attempt.permit_id) if attempt.permit_id else None
        if permit is None or permit.used_at is None or permit.packet_hash != request.packet_hash:
            return DispatchOutcome(status="failed", error="no consumed permit for this packet hash")
        task = await _task_for(session, attempt, permit, None)
        if task is None or task.status != AgentTaskStatus.claimed \
                or task.payload.get("packet_hash") != request.packet_hash:
            return DispatchOutcome(status="failed", error="no claimed runner task holds this packet")
        task.payload = {**task.payload, "attempt_id": str(attempt.id), "cleared_at": utcnow().isoformat()}
        await session.flush()
        await audit.record(session, actor="channel:browser", action="browser.cleared", subject_type="dispatch_attempt",
                           subject_id=attempt.id, detail={"task_id": str(task.id), "packet_hash": request.packet_hash,
                                                          "permit_id": str(permit.id)})
        return DispatchOutcome(status="handed_off")

    async def cancel(self, attempt_id: str) -> bool:
        attempt = await self.session.get(DispatchAttempt, uuid.UUID(attempt_id))
        return attempt is not None and attempt.status == DispatchStatus.reserved and attempt.started_at is None

    async def reconcile(self, attempt_id: str) -> DispatchOutcome:
        """Find out what happened without asking a runner to do anything: the runner's own report on its task,
        then a confirmation email matched to the application since the attempt started."""
        session = self.session
        attempt = await session.get(DispatchAttempt, uuid.UUID(attempt_id), populate_existing=True)
        if attempt is None:
            return DispatchOutcome(status="unknown", error="attempt not found")
        task = await _task_for(session, attempt, None, None)
        report = (task.result or {}) if task is not None else {}
        if report.get("attempt_id") == str(attempt.id):
            raw = report.get("evidence")
            if report.get("outcome") == "submitted" and raw and raw.get("kind") in RUNNER_EVIDENCE:
                return DispatchOutcome(status="sent", evidence=Evidence.model_validate(raw))
            if report.get("outcome") == "failed":
                return DispatchOutcome(status="failed", error=report.get("detail") or "the runner did not submit")
        since = attempt.started_at or attempt.created_at
        app = await session.get(Application, attempt.application_id)
        if app is not None:
            for item in app.confirmation_evidence:
                if item.kind == "confirmation_email" and item.at and datetime.fromisoformat(item.at) >= since:
                    return DispatchOutcome(status="sent", evidence=item)
        thread = await session.scalar(select(MailThread).where(
            MailThread.application_id == attempt.application_id,
            MailThread.classification == MailClassification.confirmation, MailThread.needs_review.is_(False),
            MailThread.last_message_at >= since).order_by(MailThread.last_message_at.desc()).limit(1))
        if thread is not None:
            ref = (thread.provider_message_ids or [thread.provider_thread_id])[-1]
            return DispatchOutcome(status="sent", evidence=Evidence(
                kind="confirmation_email", value=str(ref), at=thread.last_message_at.isoformat()
                if thread.last_message_at else None))
        return DispatchOutcome(status="unknown", error="no runner evidence or confirmation email yet")


async def factory(session: AsyncSession) -> BrowserChannel:
    return BrowserChannel(session)
