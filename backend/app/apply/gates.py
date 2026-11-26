"""Permit-time gates (DESIGN.md 8.1, 18.1-18.3; CONTRACTS.md 10).

Assembles the decision-table input for one application, packet and channel, including the
``permit_checks`` the table needs, and runs ``pipeline.decisions.decide`` with purpose ``permit``.
Approval (automatic) and the submit permit both go through :func:`evaluate`, so they cannot
disagree with discovery or with each other.

Checks added here (each ``(outcome, reason[, owner_settles])``):

- ``packet_current``: the packet is the application's newest and has not been invalidated, and its
  hash is the one asked for. ``channel_bound``: the channel asked for is the packet's.
- ``approval_bound`` (permit only): the application's approval is this packet.
- ``job_version``: the posting has not changed since the packet was built.
- ``document_checks``: no blocking check; an automatic approval also needs no waivers.
- ``answers_auto``: every answer comes from a confirmed ``auto`` answer (owner settles).
- ``destination_verified``: the destination's domain is the posting's own (owner settles).
- ``trusted_site``: browser only, the destination is on the trusted list (18.1; owner settles).
- ``duplicate``: nothing already sent or in flight for this job, requisition or application.
- ``outstanding_permit`` (permit only): no other unused, unexpired permit for this application.
- ``runner``: the runner token is not revoked or suspended.
- ``budget``: a server browser runner needs the monthly cap to cover one agent task.
- ``employer_conflict`` (permit only): the 7.1 check under the per-employer lock.

Counters: ``sent_today`` / ``sent_week`` count dispatch attempts that may have gone out plus permits
still outstanding (so concurrent permits reserve capacity), excluding the manual channel, over the
owner's local day and the last seven local days.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.llm.ledger import Ledger
from app.models.applications import (
    LIVE_STAGES,
    Application,
    ApplicationPacket,
    DispatchAttempt,
    DispatchStatus,
    SubmitPermit,
)
from app.models.base import ReviewState
from app.models.kit import Answer, AnswerClass
from app.models.platform import ApiToken
from app.models.search import Assessment, Campaign, Job, Rubric
from app.pipeline import conflicts
from app.pipeline.decisions import Decision, DecisionInput, GateDecision, decide
from app.pipeline.filters import campaign_record, load_records
from app.pipeline.scoring import decision_input, setting_versions

Approval = Literal["owner", "auto"]
Check = tuple[str, str] | tuple[str, str, bool]
MICROS_PER_MINOR = 10_000  # money.py: micros are millionths of the major unit, minor units hundredths

# Attempt states that may have reached the employer, or still could: they count against the caps and
# block a second send. ``failed`` (nothing left) and ``cancelled`` do not.
SENT_OR_IN_FLIGHT = frozenset({DispatchStatus.reserved, DispatchStatus.handed_off, DispatchStatus.sent,
                               DispatchStatus.acknowledged, DispatchStatus.bounced, DispatchStatus.unknown})


@dataclass
class Evaluation:
    decision: Decision
    input: DecisionInput
    checks: dict[str, Check]

    @property
    def status(self) -> str:
        return self.decision.permit or "denied"

    @property
    def reason(self) -> str:
        return self.decision.permit_reason or ""

    def gate_results(self) -> list[dict[str, Any]]:
        return [{"gate": g.gate, "passed": g.outcome == "pass", "outcome": g.outcome,
                 "detail": f"{g.outcome}: {g.reason}" + (f" ({', '.join(_ref(r) for r in g.rules)})" if g.rules
                                                          else "")}
                for g in self.decision.gates if g.mandatory or g.outcome != "pass"]


def _ref(r: Any) -> str:
    return f"{r.rule}={r.effective_value} [{r.source}{' ' + r.version if r.version else ''}]"


def window_starts(now: datetime, tz_name: str) -> tuple[datetime, datetime]:
    """Start of the owner's local day and of the last seven local days, in UTC."""
    tz = ZoneInfo(tz_name)
    local_midnight = datetime.combine(now.astimezone(tz).date(), time(0), tzinfo=tz)
    return local_midnight, local_midnight - timedelta(days=6)


async def sent_counts(session: AsyncSession, now: datetime, tz_name: str) -> dict[str, int]:
    day, week = window_starts(now, tz_name)
    attempts = (await session.execute(select(DispatchAttempt.created_at).where(
        DispatchAttempt.status.in_(SENT_OR_IN_FLIGHT), DispatchAttempt.channel != "manual",
        DispatchAttempt.created_at >= week))).scalars().all()
    permits = (await session.execute(
        select(SubmitPermit.issued_at, ApplicationPacket.contents)
        .join(ApplicationPacket, ApplicationPacket.id == SubmitPermit.packet_id)
        .where(SubmitPermit.used_at.is_(None), SubmitPermit.expires_at > now))).all()
    outstanding = [issued for issued, contents in permits if contents.channel != "manual"]
    stamps = [*attempts, *outstanding]
    return {"sent_today": sum(1 for t in stamps if t >= day), "sent_week": sum(1 for t in stamps if t >= week)}


async def duplicate_check(session: AsyncSession, app: Application, job: Job, *,
                          exclude_attempt_id: uuid.UUID | None = None) -> tuple[str, str]:
    """Duplicate protection. ``exclude_attempt_id``: the attempt being dispatched (rechecked at dispatch)."""
    if app.applied_at is not None:
        return "fail", "this application has already been sent"
    stmt = select(DispatchAttempt.id).where(DispatchAttempt.application_id == app.id,
                                            DispatchAttempt.status.in_(SENT_OR_IN_FLIGHT))
    if exclude_attempt_id is not None:
        stmt = stmt.where(DispatchAttempt.id != exclude_attempt_id)
    attempt = await session.scalar(stmt.limit(1))
    if attempt is not None:
        return "fail", "a dispatch attempt for this application is already recorded"
    others = (await session.scalars(select(Application).where(Application.job_id == job.id,
                                                               Application.id != app.id))).all()
    if any(stages.counts_as_application(o) and o.stage not in stages.PRE_SUBMIT - {stages.S.applying}
           for o in others):
        return "fail", "another application to this job has gone out"
    if job.requisition_id:
        same = (await session.execute(
            select(Application).join(Job, Job.id == Application.job_id).where(
                Application.id != app.id, Job.requisition_id == job.requisition_id,
                func.lower(Job.canonical_employer) == job.canonical_employer.lower()))).scalars().all()
        if any(o.applied_at is not None or o.stage in LIVE_STAGES for o in same):
            return "fail", f"requisition {job.requisition_id} already applied to"
    return "pass", "no prior application to this job or requisition"


def _document_checks(app: Application, approval: Approval) -> Check:
    blocks = [c for c in app.check_results if c.status == "block" and not c.waived]
    if blocks:
        return "fail", f"document checks block: {', '.join(c.check for c in blocks)}"
    waived = [c for c in app.check_results if c.waived]
    if approval == "auto" and waived:
        return "fail", f"waived checks need your approval: {', '.join(c.check for c in waived)}", True
    return "pass", "document checks clean" if not waived else "document checks pass with your waivers"


async def _answers(session: AsyncSession, packet: ApplicationPacket) -> Check:
    not_auto = []
    for a in packet.contents.answers:
        row = await session.get(Answer, uuid.UUID(a.answer_id)) if a.answer_id else None
        if row is None or row.answer_class != AnswerClass.auto or row.review_state != ReviewState.confirmed:
            not_auto.append(a.question)
    if not_auto:
        return "unknown", f"not answered from confirmed automatic answers: {', '.join(not_auto)}", True
    return "pass", "every answer comes from a confirmed automatic answer"


async def _budget(session: AsyncSession, channel: str, runner: ApiToken | None, settings: dict[str, Any]
                  ) -> Check:
    if channel != "browser":
        return "pass", f"no model spend on the {channel} channel"
    if runner is not None and runner.runner_kind == "pc":
        return "pass", "the PC runner uses the owner's subscription"
    summary = await Ledger().summary(session)
    ceiling = int(settings["budget.agent_task_ceiling_minor"]) * MICROS_PER_MINOR
    if summary.remaining_micros is None:
        return "fail", "no monthly budget cap set: paid agent work stays off"
    if summary.remaining_micros < ceiling:
        return "fail", f"budget left ({summary.remaining_micros} micros) is below one agent task ceiling"
    return "pass", "budget covers one agent task"


def _runner(runner: ApiToken | None, runner_token_id: uuid.UUID | None) -> Check:
    if runner_token_id is None:
        return "pass", "server-side channel, no runner"
    if runner is None:
        return "fail", "runner token not found"
    if runner.revoked_at is not None or runner.suspended_at is not None:
        return "fail", f"runner {runner.name} is revoked or suspended"
    return "pass", f"runner {runner.name}"


async def _assessment(session: AsyncSession, app: Application) -> Assessment | None:
    if app.assessment_id:
        found = await session.get(Assessment, app.assessment_id)
        if found is not None:
            return found
    if app.campaign_id is None:
        return None
    return await session.scalar(select(Assessment).where(Assessment.job_id == app.job_id,
                                                         Assessment.campaign_id == app.campaign_id))


async def evaluate(session: AsyncSession, app: Application, packet: ApplicationPacket | None, *, channel: str,
                   approval: Approval | None, packet_hash: str | None = None, for_approval: bool = False,
                   runner_token_id: uuid.UUID | None = None, now: datetime,
                   extra_checks: dict[str, Check] | None = None) -> Evaluation:
    """Run the decision table for this application, packet and channel. ``for_approval`` evaluates an
    automatic approval (timing gates and permit-only checks are left out)."""
    job = await session.get(Job, app.job_id)
    assert job is not None
    campaign = await session.get(Campaign, app.campaign_id) if app.campaign_id else None
    if campaign is not None:
        await session.flush()
        await session.refresh(campaign)  # server-set updated_at is its version
    settings, versions = await setting_versions(session)
    records = await load_records(session, now=now, job_ids=[job.id], include_merged=True)
    record = records[0][1]
    assessment = await _assessment(session, app)
    rubric = await session.get(Rubric, assessment.rubric_id) if assessment and assessment.rubric_id else None
    crecord = campaign_record(campaign) if campaign is not None else {"automation": {}, "status": None}
    counters = {**await conflicts.employer_counters(session, job, now=now),
                **await sent_counts(session, now, settings["general.timezone"])}
    if app.stage in LIVE_STAGES:
        counters["employer_live"] = max(0, counters["employer_live"] - 1)
    runner = await session.get(ApiToken, runner_token_id) if runner_token_id else None

    checks: dict[str, Check] = {}
    current = None
    if packet is not None:
        current = await session.scalar(select(ApplicationPacket.id).where(
            ApplicationPacket.application_id == app.id, ApplicationPacket.invalidated_at.is_(None))
            .order_by(ApplicationPacket.version.desc()).limit(1))
    if packet is None:
        checks["packet_current"] = ("fail", "no packet built")
    elif packet.invalidated_at is not None or current != packet.id:
        checks["packet_current"] = ("fail", f"packet v{packet.version} is no longer current"
                                    + (f": {packet.invalidated_reason}" if packet.invalidated_reason else ""))
    elif packet_hash is not None and packet_hash != packet.content_hash:
        checks["packet_current"] = ("fail", "packet hash does not match")
    else:
        checks["packet_current"] = ("pass", f"packet v{packet.version} {packet.content_hash[:12]}")
    if packet is not None:
        bound = packet.contents.channel
        checks["channel_bound"] = (("pass", f"channel {channel}") if bound == channel
                                   else ("fail", f"packet is for {bound}, not {channel}"))
        checks["job_version"] = (("pass", "posting unchanged since the packet was built")
                                 if packet.contents.job_version in (None, job.content_hash)
                                 else ("fail", "the posting changed since the packet was built"))
        dest = packet.contents.destination
        checks["destination_verified"] = (("pass", f"{dest.domain} is the posting's own") if dest.verified
                                          else ("unknown", f"{dest.domain} is not confirmed as the posting's", True))
        if channel == "browser":
            checks["trusted_site"] = (("pass", f"{dest.domain} is on the trusted list") if dest.trusted
                                      else ("unknown", f"{dest.domain} is not a trusted site: ask first", True))
        if approval == "auto":
            checks["answers_auto"] = await _answers(session, packet)
    if not for_approval:
        approved = packet is not None and app.approved_packet_id == packet.id and packet.approved_at is not None
        checks["approval_bound"] = (("pass", f"approved by {packet.approved_by}") if approved and packet
                                    else ("fail", "this packet is not the approved one"))
        outstanding = await session.scalar(select(SubmitPermit.id).where(
            SubmitPermit.application_id == app.id, SubmitPermit.used_at.is_(None),
            SubmitPermit.expires_at > now).limit(1))
        checks["outstanding_permit"] = (("fail", "a permit for this application is already outstanding")
                                        if outstanding else ("pass", "no outstanding permit"))
    checks["document_checks"] = _document_checks(app, approval or "owner")
    checks["duplicate"] = await duplicate_check(session, app, job)
    checks["runner"] = _runner(runner, runner_token_id)
    checks["budget"] = await _budget(session, channel, runner, settings)
    checks.update(extra_checks or {})

    base = decision_input(now=now, record=record, crecord=crecord, settings=settings, versions=versions,
                          rubric=rubric, base_score=assessment.base_score if assessment else None, job=job,
                          override=assessment.override.model_dump() if assessment and assessment.override else None,
                          counters=counters, purpose="permit")
    data = dataclasses.replace(base, application={"approval": approval, "channel": channel,
                                                  "permit_checks": checks, "for_approval": for_approval})
    return Evaluation(decide(data), data, checks)


def blocking(evaluation: Evaluation) -> list[GateDecision]:
    return [g for g in evaluation.decision.gates if g.mandatory and g.outcome != "pass"]
