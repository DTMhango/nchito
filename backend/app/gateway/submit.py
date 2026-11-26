"""Submit permits and results through the gateway (DESIGN.md 8.1, 8.3, 8.5, 18.1-18.3).

Invariants, never settings:

- **Permit only through ``apply.permits.request``** (every gate again, under the permit and employer locks)
  and only for the answers actually entered: each entered answer must be in the approved packet with the
  same value, and each attached file must be one of its files. A new question or a changed value is a
  packet change: a new packet version holding what was entered is built and the owner is asked
  (``wait_for_owner``). An entered answer to a ``never`` or ``owner_only`` question, an unknown file, or a
  page off the destination is ``denied``. Unknown never grants.
- **Attempt before the click.** A granted permit writes a ``DispatchAttempt`` (in flight, caps reserved) in
  the same transaction, so a second permit for the application is refused (duplicate gate) and a runner
  that dies is reconciled, never repeated.
- **The permit is consumed by the result.** ``report_result(submitted)`` consumes the permit atomically
  (single use, unexpired, this runner, this packet). With evidence the send is ``sent``; without it,
  ``unknown`` and reconciliation.
- **Violation.** ``submitted`` without a permit that can be consumed is a violation: audited, an alert is
  raised, the runner is suspended and the submission is held as uncertain so duplicates stay locked.
- ``uncertain`` goes to reconciliation and is never retried automatically. ``failed`` (the runner says it
  never submitted) settles the attempt as failed and the role goes back to ``ready``.
- A dry run never gets a permit and records nothing on the application.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import approval, outcomes, packets, permits
from app.apply.channels.base import DispatchOutcome
from app.core import audit
from app.gateway.answers import raise_question
from app.gateway.auth import suspend
from app.gateway.common import (
    GatewayError,
    approved_packet,
    clip,
    own_task,
    parse_id,
    require_active,
    require_scope,
    same_site,
    setting,
    task_application,
)
from app.gateway.tasks import give_back, is_dry_run, open_attempt
from app.gateway.tools import ReportResultIn, ReportResultOut, RequestPermitIn, RequestPermitOut
from app.kit.answers import match, normalise, similarity
from app.kit.work_rights import to_record
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    Application,
    ApplicationPacket,
    Channel,
    DispatchAttempt,
    DispatchStatus,
    SubmitPermit,
)
from app.models.kit import Answer, AnswerClass
from app.models.platform import ApiToken
from app.models.search import Job
from app.pipeline.tailoring.answers import context_for
from app.schemas.json_types import Evidence

# ----- comparing what was entered with the packet -----------------------------------------------


def _same_value(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


async def _compare(session: AsyncSession, app: Application, job: Job, packet: ApplicationPacket,
                   body: RequestPermitIn, at: datetime) -> tuple[list[str], list[str], list[packets.DraftAnswer]]:
    """(refusals, changes, merged answers). Refusals deny; changes ask the owner."""
    threshold = float(await setting(session, "answers.match_similarity"))
    rows = list((await session.scalars(select(Answer))).all())
    records, by_id = [to_record(a) for a in rows], {a.id: a for a in rows}
    refusals: list[str] = []
    changes: list[str] = []
    merged = [packets.DraftAnswer(question=a.question, answer_id=uuid.UUID(a.answer_id)) if a.answer_id
              else packets.DraftAnswer(question=a.question, value=a.value) for a in packet.contents.answers]
    for entered in body.entered_answers:
        question, value = clip(entered.question, 500) or "", clip(entered.value, 2000) or ""
        bank = match(question, records, threshold=threshold, context=context_for(app, job), today=at.date())
        found = by_id.get(bank.answer_id) if bank.answer_id else None
        if bank.outcome == "do_not_answer" or (found is not None and found.answer_class == AnswerClass.owner_only):
            if not (bank.select and _same_value(value, bank.select)):
                refusals.append(f"an answer was entered for {question!r}, which is never answered by the runner")
            continue
        idx = next((i for i, a in enumerate(packet.contents.answers)
                    if normalise(a.question) == normalise(question) or similarity(a.question, question) >= threshold),
                   None)
        if idx is None:
            changes.append(f"new question {question!r} answered {value!r}")
            merged.append(packets.DraftAnswer(question=question, value=value))
        elif not _same_value(packet.contents.answers[idx].value, value):
            changes.append(f"{packet.contents.answers[idx].question!r} entered as {value!r}, "
                           f"approved as {packet.contents.answers[idx].value!r}")
            merged[idx] = packets.DraftAnswer(question=packet.contents.answers[idx].question, value=value)
    known = {f.sha256 for f in packet.contents.files}
    for sha in body.attached_files_sha256:
        if sha.lower() not in known:
            refusals.append(f"a file not in the approved packet was attached ({sha[:12]})")
    return refusals, changes, merged


def _draft(packet: ApplicationPacket, answers: list[packets.DraftAnswer]) -> packets.PacketDraft:
    c = packet.contents
    return packets.PacketDraft(channel="browser", destination_url=c.destination.url,
                               sending_identity=c.sending_identity, answers=answers, email=c.email, files=list(c.files),
                               link_permissions=list(c.link_permissions), requisition=c.requisition)


def _entered(body: RequestPermitIn, at: datetime) -> dict[str, Any]:
    return {"at": at.isoformat(), "summary": clip(body.summary, 1000), "current_url": clip(body.current_url, 2000),
            "answers": [{"question": clip(a.question, 500), "value": clip(a.value, 2000)}
                        for a in body.entered_answers],
            "files": [s[:64] for s in body.attached_files_sha256]}


async def _wait(session: AsyncSession, task: AgentTask, app: Application, packet: ApplicationPacket,
                reason: str) -> None:
    action = await approval.request_owner_approval(session, app, packet, reason)
    task.status = AgentTaskStatus.blocked
    task.payload = {**task.payload, "waiting_for": "approval", "approval_action_id": str(action.id)}


async def request_submit_permit(session: AsyncSession, token: ApiToken, body: RequestPermitIn, *,
                                at: datetime) -> RequestPermitOut:
    require_active(token)
    require_scope(token, "gateway:permits")
    task = await own_task(session, token, body.task_id, at=at, types=(AgentTaskType.apply,))
    actor = f"runner:{token.name}"
    app, job = await task_application(session, task)
    entered = _entered(body, at)
    task.released = {**task.released, "entered": entered}

    async def refuse(reason: str, changes: list[str] | None = None) -> RequestPermitOut:
        await audit.record(session, actor=actor, action="gateway.permit_denied", subject_type="agent_task",
                           subject_id=task.id, detail={"reason": reason, "changes": changes or [], **entered})
        return RequestPermitOut(decision="denied", reason=reason, changes=changes or [])

    if is_dry_run(task):
        return await refuse("dry run: no permit is ever granted")
    packet = await approved_packet(session, app)
    if packet is None:
        return await refuse("this application has no approved browser packet")
    url_domain = packets.domain_of(body.current_url)
    if not same_site(url_domain, packet.contents.destination.domain):
        from app.gateway.blockers import raise_blocker
        from app.gateway.tools import RaiseBlockerIn

        await raise_blocker(session, token, RaiseBlockerIn(
            task_id=str(task.id), type="redirect_off_domain", url=body.current_url,
            detail=f"permit asked from {url_domain or 'an unknown page'}, not {packet.contents.destination.domain}"),
            at=at)
        return await refuse(f"the page is on {url_domain or 'an unknown site'}, not "
                            f"{packet.contents.destination.domain}")
    refusals, changes, merged = await _compare(session, app, job, packet, body, at)
    if refusals:
        return await refuse("; ".join(refusals), changes)
    if changes:
        try:
            built = await packets.build(session, app, _draft(packet, merged), actor=actor, now=at)
        except packets.PacketError as exc:
            return await refuse(f"the entered answers cannot be packed: {exc.message}", changes)
        for text in changes:
            if text.startswith("new question"):
                await raise_question(session, app, task, text, {"reason": "met on the form", "entered_by": token.name})
        await _wait(session, task, app, built.packet, "the form asked for answers that differ from the approved packet")
        await audit.record(session, actor=actor, action="gateway.permit_wait_for_owner", subject_type="agent_task",
                           subject_id=task.id, detail={"changes": changes, "new_packet_hash": built.packet.content_hash,
                                                       **entered})
        return RequestPermitOut(decision="wait_for_owner", changes=changes,
                                reason="the entered answers differ from the approved packet; the owner is asked")
    result = await permits.request(session, app.id, packet_hash=packet.content_hash, channel="browser",
                                   runner_token_id=token.id, agent_task_id=task.id, actor=actor, now=at)
    if result.status == "wait_for_owner":
        await _wait(session, task, app, packet, result.reason)
        return RequestPermitOut(decision="wait_for_owner", reason=result.reason)
    if not result.granted or result.permit is None:
        return RequestPermitOut(decision="denied", reason=result.reason)
    permit = result.permit
    attempt = DispatchAttempt(application_id=app.id, packet_id=packet.id, packet_hash=packet.content_hash,
                              channel=Channel.browser, permit_id=permit.id, status=DispatchStatus.reserved,
                              send_after=at, started_at=at, gate_results=permit.checks)
    session.add(attempt)
    await session.flush()
    await outcomes._log(session, attempt, "dispatch.reserved", actor, packet_version=packet.version,
                        approved_by=packet.approved_by, runner=token.name, agent_task_id=str(task.id),
                        gates=result.gates)
    task.payload = {**task.payload, "permit_id": str(permit.id), "attempt_id": str(attempt.id)}
    return RequestPermitOut(decision="granted", permit_id=str(permit.id), expires_at=permit.expires_at.isoformat(),
                            reason=result.reason)


# ----- results -----------------------------------------------------------------------------------


def _evidence(body: ReportResultIn, at: datetime) -> Evidence | None:
    shot = clip(body.screenshot_ref, 500)
    if body.reference and body.reference.strip():
        return Evidence(kind="reference", value=clip(body.reference.strip(), 200) or "", screenshot_ref=shot,
                        at=at.isoformat())
    if body.confirmation_text and body.confirmation_text.strip():
        return Evidence(kind="confirmation_page", value=clip(body.confirmation_text.strip(), 1000) or "",
                        screenshot_ref=shot, at=at.isoformat())
    return None


async def _attempt_for(session: AsyncSession, task: AgentTask) -> DispatchAttempt | None:
    raw = task.payload.get("attempt_id")
    if not raw:
        return None
    return await session.scalar(select(DispatchAttempt).where(DispatchAttempt.id == uuid.UUID(raw)).with_for_update()
                                .execution_options(populate_existing=True))


async def _hold_uncertain(session: AsyncSession, task: AgentTask, app: Application, why: str, actor: str,
                          at: datetime) -> None:
    """Something may have gone out: keep it uncertain (duplicates locked) until reconciled."""
    attempt = await _attempt_for(session, task)
    if attempt is None or attempt.status not in outcomes.OPEN_STATUSES:
        attempt = await open_attempt(session, app.id)
    if attempt is None:
        packet = await packets.current(session, app.id)
        if packet is None:
            return
        attempt = DispatchAttempt(application_id=app.id, packet_id=packet.id, packet_hash=packet.content_hash,
                                  channel=Channel.browser, status=DispatchStatus.reserved, send_after=at,
                                  started_at=at, gate_results=[])
        session.add(attempt)
        await session.flush()
        if app.stage.value in ("ready", "shortlisted", "tailoring"):
            from app.apply import stages

            await stages.transition(session, app, stages.S.applying, actor="system", via="system", now=at,
                                    why="a runner reported a submission the system did not permit")
    if attempt.status in outcomes.OPEN_STATUSES and attempt.status != DispatchStatus.unknown:
        await outcomes.record(session, attempt, DispatchOutcome(status="unknown", error=why), via="gateway",
                              actor=actor, now=at)


async def violation(session: AsyncSession, token: ApiToken, task: AgentTask | None, reason: str, *,
                    at: datetime) -> None:
    from app.ops import notifications

    await suspend(session, token, reason=reason, now=at, keep=task.id if task else None)
    await audit.record(session, actor=f"runner:{token.name}", action="gateway.violation",
                       subject_type="agent_task" if task else "api_token", subject_id=task.id if task else token.id,
                       detail={"reason": reason, "runner": token.name, "at": at.isoformat()})
    await notifications.notify(session, kind="health", key=f"gateway-violation-{token.id}-{task.id if task else ''}",
                               title=f"Runner {token.name} suspended: a submission without a permit",
                               body=reason, link="/settings/connections")


async def report_result(session: AsyncSession, token: ApiToken, body: ReportResultIn, *,
                        at: datetime) -> ReportResultOut:
    actor = f"runner:{token.name}"
    try:
        task = await own_task(session, token, body.task_id, at=at)
    except GatewayError:
        if body.outcome != "submitted":
            raise
        # A runner reporting a submission on a task it does not hold: it went out without this system's permit.
        other = await session.get(AgentTask, parse_id(body.task_id))
        app = await session.get(Application, other.application_id) if other and other.application_id else None
        await violation(session, token, None, f"reported a submission for a task it does not hold ({body.task_id})",
                        at=at)
        if app is not None and other is not None:
            await _hold_uncertain(session, other, app, "a runner that did not hold the task reported it submitted",
                                  actor, at)
        return ReportResultOut(recorded=True, application_stage=app.stage.value if app else None)
    task.result = {"outcome": body.outcome, "detail": clip(body.detail), "reference": clip(body.reference, 200),
                   "confirmation_text": clip(body.confirmation_text), "screenshot_ref": clip(body.screenshot_ref, 500),
                   "permit_id": body.permit_id, "at": at.isoformat()}
    if task.type != AgentTaskType.apply:
        if is_dry_run(task):
            await give_back(session, task, reason="dry run finished", actor=actor, at=at)
        else:
            task.status = AgentTaskStatus.done if body.outcome != "failed" else AgentTaskStatus.failed
        return ReportResultOut(recorded=True)
    app, _ = await task_application(session, task)
    if is_dry_run(task) and body.outcome != "submitted":
        await give_back(session, task, reason=f"dry run finished: {body.outcome}", actor=actor, at=at)
        return ReportResultOut(recorded=False, application_stage=app.stage.value)
    attempt = await _attempt_for(session, task)
    if body.outcome == "submitted":
        consumed: SubmitPermit | None = None
        problem = None
        if not body.permit_id or body.permit_id != task.payload.get("permit_id") or attempt is None:
            problem = "no submit permit was granted for this task" if not task.payload.get("permit_id") \
                else "the permit reported is not the one granted for this task"
        else:
            try:
                consumed = await permits.consume(session, parse_id(body.permit_id, "permit"),
                                                 packet_hash=attempt.packet_hash, channel="browser",
                                                 runner_token_id=token.id, actor=actor, now=at)
            except permits.PermitRefused as exc:
                problem = f"the permit could not be used: {exc.reason}"
        if consumed is None:
            await violation(session, token, task, f"submitted without a usable permit: {problem}", at=at)
            await _hold_uncertain(session, task, app, f"submitted without a usable permit: {problem}", actor, at)
            task.status = AgentTaskStatus.failed
            task.result = {**task.result, "violation": problem}
        else:
            assert attempt is not None
            evidence = _evidence(body, at)
            outcome = DispatchOutcome(status="sent", evidence=evidence) if evidence else DispatchOutcome(
                status="unknown", error="the runner reported it submitted without a confirmation or reference")
            if attempt.status in outcomes.OPEN_STATUSES:
                await outcomes.record(session, attempt, outcome, via="gateway", actor=actor, now=at)
            task.status = AgentTaskStatus.done
    elif body.outcome == "uncertain":
        await _hold_uncertain(session, task, app, clip(body.detail, 500) or "the runner is not sure it went out",
                              actor, at)
        await permits.revoke(session, application_id=app.id, reason="runner reported uncertain", actor=actor, now=at)
        task.status = AgentTaskStatus.done
    else:
        await permits.revoke(session, application_id=app.id, reason="runner reported failed", actor=actor, now=at)
        if attempt is not None and attempt.status in outcomes.OPEN_STATUSES:
            await outcomes.record(session, attempt, DispatchOutcome(
                status="failed", error=f"runner: {clip(body.detail, 500) or 'failed before submitting'}"),
                via="gateway", actor=actor, now=at)
            locked = await outcomes.lock_application(session, app.id)
            await outcomes.give_back(session, locked, attempt, "the runner failed before submitting", now=at)
        task.status = AgentTaskStatus.failed
    await session.flush()
    await audit.record(session, actor=actor, action="gateway.result_reported", subject_type="agent_task",
                       subject_id=task.id, detail={**task.result, "application_id": str(app.id),
                                                   "task_status": task.status.value})
    await session.refresh(app)
    return ReportResultOut(recorded=True, application_stage=app.stage.value)
