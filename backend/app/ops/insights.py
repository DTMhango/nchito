"""Insights aggregates (DESIGN.md 10.3, wave 4): counts, rates, durations and spend from the database.

No model calls. One filter set (date range, campaign, track, source, market, channel) applies everywhere.
Counting rules, so the numbers can be trusted:

- A role counts once: merged jobs are left out, a second application for the same job is ignored, and skipped
  or never-sent closed applications are not applications. A snoozed application counts like any other.
- ``sent`` means the application has ``applied_at``: sent by the system or logged with "I applied myself".
- ``reply`` means the employer answered: the application reached screening, interview, offer or accepted, or
  was rejected after it was sent. Reached stages come from the stage-change events and the current stage.
- A rate is always returned with its sample size and a ``too_few`` flag (``insights.min_sample``).
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply.approval import AUTO_APPROVER
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    ApplicationEvent,
    ApplicationPacket,
    ApplicationSpecVersion,
    Channel,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    Stage,
)
from app.models.kit import Track
from app.models.platform import AuditEvent, LedgerEntry, LedgerKind
from app.models.search import Assessment, AssessmentState, Campaign, Job, JobSighting, Source

REPLY_STAGES = frozenset({Stage.screening, Stage.interview, Stage.offer, Stage.accepted})
INTERVIEW_STAGES = frozenset({Stage.interview, Stage.offer, Stage.accepted})
OFFER_STAGES = frozenset({Stage.offer, Stage.accepted})
BLOCKER_TYPES = frozenset({
    PendingActionType.sign_in, PendingActionType.create_account, PendingActionType.captcha,
    PendingActionType.unknown_question, PendingActionType.assessment, PendingActionType.declaration,
    PendingActionType.unsupported_form, PendingActionType.redirect_off_domain, PendingActionType.page_instruction})

FUNNEL_STAGES: list[tuple[str, str]] = [
    ("found", "Found"), ("passed_filters", "Passed filters"), ("scored_above", "Scored above threshold"),
    ("tailored", "Tailored"), ("approved", "Approved"), ("sent", "Sent"), ("reply", "Reply"),
    ("interview", "Interview"), ("offer", "Offer")]
NONE_KEY = "none"
NOT_STATED = "Not stated"

SpendPeriod = Literal["week", "month"]


class InsightFilters(BaseModel):
    since: date | None = None
    until: date | None = None
    campaign_id: uuid.UUID | None = None
    track_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    country: str | None = None
    channel: Channel | None = None


class FunnelStep(BaseModel):
    key: str
    label: str
    count: int
    of_previous: float | None = Field(description="Share of the step before (null when that is zero)")
    of_found: float | None = None


class CampaignFunnel(BaseModel):
    campaign_id: uuid.UUID | None
    campaign: str
    steps: list[FunnelStep]


class RateRow(BaseModel):
    key: str = Field(description="Track id, source id or country; the filter value for a drill-through")
    label: str
    sent: int
    replies: int
    interviews: int
    rate: float | None = Field(description="replies / sent; null when nothing was sent")
    too_few: bool = Field(description="Fewer than insights.min_sample sent: do not read the rate as a trend")


class RateTables(BaseModel):
    min_sample: int
    by_track: list[RateRow]
    by_source: list[RateRow]
    by_market: list[RateRow]


class DurationRow(BaseModel):
    stage: str
    n: int
    median_days: float | None
    p75_days: float | None
    too_few: bool


class TimeInStage(BaseModel):
    stages: list[DurationRow]
    first_reply: DurationRow


class SpendRow(BaseModel):
    period: str = Field(description="First day of the week or month, ISO date")
    stage: str
    model: str
    micros: int


class SpendReport(BaseModel):
    currency: str
    period: SpendPeriod
    rows: list[SpendRow]
    total_micros: int
    sent: int
    interviews: int
    per_sent_micros: int | None
    per_interview_micros: int | None


class SourceRow(BaseModel):
    source_id: uuid.UUID | None
    name: str
    found: int
    duplicates: int
    passed: int
    applied: int
    replies: int


class CountRow(BaseModel):
    key: str
    count: int


class AutomationOutcomes(BaseModel):
    auto: int
    approved: int
    manual: int
    uncertain_sends: int
    blockers: list[CountRow]
    permits_denied: list[CountRow]


class InsightsOut(BaseModel):
    since: date
    until: date
    filters: InsightFilters
    notes: list[str]
    funnel: list[CampaignFunnel]
    response: RateTables
    time_in_stage: TimeInStage
    spend: SpendReport
    sources: list[SourceRow]
    automation: AutomationOutcomes
    exclusions: list[CountRow] = Field(description="Hard filters that excluded the most roles, most first")


# ----- helpers ------------------------------------------------------------------------------------


def ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolated quantile; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 2)


def duration_row(label: str, days: list[float], min_sample: int) -> DurationRow:
    median = round(statistics.median(days), 2) if days else None
    return DurationRow(stage=label, n=len(days), median_days=median, p75_days=quantile(days, 0.75),
                       too_few=len(days) < min_sample)


def period_start(day: date, period: SpendPeriod, week_start: str) -> date:
    if period == "month":
        return day.replace(day=1)
    offset = day.weekday() if week_start == "monday" else (day.weekday() + 1) % 7
    return day - timedelta(days=offset)


@dataclass
class AppFacts:
    app: Application
    job: Job
    campaign_id: uuid.UUID | None
    track_id: uuid.UUID | None
    source_id: uuid.UUID | None
    country: str
    reached: set[Stage] = field(default_factory=set)
    first_reply_at: datetime | None = None
    tailored: bool = False
    approved: bool = False
    approver: str | None = None

    @property
    def sent(self) -> bool:
        return self.app.applied_at is not None

    @property
    def replied(self) -> bool:
        return bool(self.reached & REPLY_STAGES) or (Stage.rejected in self.reached and self.sent)

    @property
    def interviewed(self) -> bool:
        return bool(self.reached & INTERVIEW_STAGES)

    @property
    def offered(self) -> bool:
        return bool(self.reached & OFFER_STAGES)


def country_of(job: Job) -> str:
    return (job.location.country or "").strip() or NOT_STATED


def _bounds(since: date, until: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(since, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


class Collector:
    """Loads what one report needs, once, with the filters applied."""

    def __init__(self, session: AsyncSession, f: InsightFilters, since: date, until: date, tz: ZoneInfo) -> None:
        self.session, self.f, self.since, self.until, self.tz = session, f, since, until, tz
        self.start, self.end = _bounds(since, until, tz)
        self.sources: dict[uuid.UUID, str] = {}
        self.tracks: dict[uuid.UUID, str] = {}
        self.campaigns: dict[uuid.UUID, tuple[str, uuid.UUID | None]] = {}
        self.job_source: dict[uuid.UUID, uuid.UUID | None] = {}
        self.events: dict[uuid.UUID, list[tuple[datetime, str]]] = defaultdict(list)

    async def load_lookups(self) -> None:
        s = self.session
        self.sources = {i: n for i, n in (await s.execute(select(Source.id, Source.name))).all()}
        self.tracks = {i: n for i, n in (await s.execute(select(Track.id, Track.name))).all()}
        self.campaigns = {i: (n, t) for i, n, t in (await s.execute(
            select(Campaign.id, Campaign.name, Campaign.track_id))).all()}
        for job_id, source_id in await s.execute(
                select(JobSighting.job_id, JobSighting.source_id).order_by(JobSighting.first_seen_at,
                                                                           JobSighting.id)):
            self.job_source.setdefault(job_id, source_id)

    def track_of(self, campaign_id: uuid.UUID | None) -> uuid.UUID | None:
        return self.campaigns[campaign_id][1] if campaign_id in self.campaigns else None

    def _job_ok(self, job: Job, campaign_id: uuid.UUID | None) -> bool:
        f = self.f
        if job.merged_into_id is not None:
            return False
        if f.source_id and self.job_source.get(job.id) != f.source_id:
            return False
        if f.country and country_of(job).lower() != f.country.strip().lower():
            return False
        if f.campaign_id and campaign_id != f.campaign_id:
            return False
        return not (f.track_id and self.track_of(campaign_id) != f.track_id)

    async def applications(self) -> list[AppFacts]:
        s, f = self.session, self.f
        rows = (await s.execute(
            select(Application, Job).join(Job, Job.id == Application.job_id)
            .where(Application.created_at >= self.start, Application.created_at < self.end)
            .order_by(Application.created_at, Application.id))).all()
        seen: set[uuid.UUID] = set()
        facts: list[AppFacts] = []
        for app, job in rows:
            if app.stage == Stage.skipped or (app.stage == Stage.closed and app.applied_at is None):
                continue
            if job.id in seen or not self._job_ok(job, app.campaign_id):
                continue
            if f.channel and app.channel != f.channel:
                continue
            seen.add(job.id)
            facts.append(AppFacts(app=app, job=job, campaign_id=app.campaign_id,
                                  track_id=self.track_of(app.campaign_id), source_id=self.job_source.get(job.id),
                                  country=country_of(job), reached={app.stage}))
        if not facts:
            return facts
        by_id = {x.app.id: x for x in facts}
        ids = list(by_id)
        for app_id, created, detail in await s.execute(
                select(ApplicationEvent.application_id, ApplicationEvent.created_at, ApplicationEvent.detail)
                .where(ApplicationEvent.application_id.in_(ids), ApplicationEvent.kind == "stage_change")
                .order_by(ApplicationEvent.created_at, ApplicationEvent.id)):
            target = detail.get("to")
            if not isinstance(target, str):
                continue
            self.events[app_id].append((created, target))
            try:
                stage = Stage(target)
            except ValueError:
                continue
            x = by_id[app_id]
            x.reached.add(stage)
            if (stage in REPLY_STAGES or stage == Stage.rejected) and x.first_reply_at is None:
                x.first_reply_at = created
        for (app_id,) in await s.execute(select(ApplicationSpecVersion.application_id)
                                         .where(ApplicationSpecVersion.application_id.in_(ids)).distinct()):
            by_id[app_id].tailored = True
        for app_id, approver in await s.execute(
                select(ApplicationPacket.application_id, ApplicationPacket.approved_by)
                .where(ApplicationPacket.application_id.in_(ids), ApplicationPacket.approved_at.is_not(None))
                .order_by(ApplicationPacket.approved_at)):
            x = by_id[app_id]
            x.approved = True
            x.approver = x.approver or approver
        return facts

    async def assessments(self) -> list[tuple[Assessment, Job]]:
        rows = (await self.session.execute(
            select(Assessment, Job).join(Job, Job.id == Assessment.job_id)
            .where(Assessment.created_at >= self.start, Assessment.created_at < self.end))).all()
        return [(a, j) for a, j in rows if self._job_ok(j, a.campaign_id)]

    async def jobs(self) -> list[Job]:
        return list((await self.session.scalars(
            select(Job).where(Job.created_at >= self.start, Job.created_at < self.end))).all())


# ----- the sections -------------------------------------------------------------------------------


def _funnel(assessments: Iterable[tuple[Assessment, Job]], apps: list[AppFacts], threshold: int,
            c: Collector) -> list[CampaignFunnel]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a, _job in assessments:
        row = counts[str(a.campaign_id)]
        row["found"] += 1
        if a.state in (AssessmentState.scored, AssessmentState.parked):
            row["passed_filters"] += 1
        if a.state == AssessmentState.scored and a.score is not None and a.score >= threshold:
            row["scored_above"] += 1
    for x in apps:
        row = counts[str(x.campaign_id) if x.campaign_id else NONE_KEY]
        for key, hit in (("tailored", x.tailored), ("approved", x.approved or x.sent), ("sent", x.sent),
                         ("reply", x.sent and x.replied), ("interview", x.interviewed), ("offer", x.offered)):
            row[key] += 1 if hit else 0
    out: list[CampaignFunnel] = []
    for key, row in counts.items():
        steps: list[FunnelStep] = []
        prev = 0
        for i, (code, label) in enumerate(FUNNEL_STAGES):
            n = row.get(code, 0)
            steps.append(FunnelStep(key=code, label=label, count=n, of_previous=ratio(n, prev) if i else None,
                                    of_found=ratio(n, row.get("found", 0)) if i else None))
            prev = n
        if key == NONE_KEY:
            out.append(CampaignFunnel(campaign_id=None, campaign="No campaign", steps=steps))
        else:
            cid = uuid.UUID(key)
            out.append(CampaignFunnel(campaign_id=cid, campaign=c.campaigns.get(cid, ("Deleted campaign", None))[0],
                                      steps=steps))
    return sorted(out, key=lambda r: (-r.steps[0].count, r.campaign))


def _rate_rows(apps: list[AppFacts], key_of: Callable[[AppFacts], str], label_of: Callable[[str], str],
               min_sample: int) -> list[RateRow]:
    groups: dict[str, list[AppFacts]] = defaultdict(list)
    for x in apps:
        if x.sent:
            groups[key_of(x)].append(x)
    rows = []
    for k, g in groups.items():
        replies = sum(1 for x in g if x.replied)
        rows.append(RateRow(key=k, label=label_of(k), sent=len(g), replies=replies,
                            interviews=sum(1 for x in g if x.interviewed), rate=ratio(replies, len(g)),
                            too_few=len(g) < min_sample))
    return sorted(rows, key=lambda r: (-r.sent, r.label))


def _time_in_stage(apps: list[AppFacts], events: dict[uuid.UUID, list[tuple[datetime, str]]],
                   min_sample: int) -> TimeInStage:
    stays: dict[str, list[float]] = defaultdict(list)
    replies: list[float] = []
    for x in apps:
        timeline = events.get(x.app.id, [])
        entered, stage = x.app.created_at, Stage.shortlisted.value
        for at, target in timeline:
            stays[stage].append(max((at - entered).total_seconds() / 86400, 0.0))
            entered, stage = at, target
        if x.sent and x.first_reply_at and x.app.applied_at:
            replies.append(max((x.first_reply_at - x.app.applied_at).total_seconds() / 86400, 0.0))
    order = [s.value for s in Stage]
    rows = [duration_row(s, days, min_sample)
            for s, days in sorted(stays.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)]
    return TimeInStage(stages=rows, first_reply=duration_row("first_reply", replies, min_sample))


async def _spend(session: AsyncSession, c: Collector, period: SpendPeriod, week_start: str, currency: str,
                 sent: int, interviews: int) -> SpendReport:
    totals: dict[tuple[date, str, str], int] = defaultdict(int)
    query = select(LedgerEntry.created_at, LedgerEntry.stage, LedgerEntry.model, LedgerEntry.amount_micros).where(
        LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.currency == currency,
        LedgerEntry.created_at >= c.start, LedgerEntry.created_at < c.end)
    for at, stage, model, micros in await session.execute(query):
        day = at.astimezone(c.tz).date()
        totals[(period_start(day, period, week_start), stage, model or "unknown")] += micros
    rows = [SpendRow(period=p.isoformat(), stage=s, model=m, micros=v) for (p, s, m), v in sorted(totals.items())]
    total = sum(r.micros for r in rows)
    return SpendReport(currency=currency, period=period, rows=rows, total_micros=total, sent=sent,
                       interviews=interviews, per_sent_micros=total // sent if sent else None,
                       per_interview_micros=total // interviews if interviews else None)


def _sources(jobs: list[Job], assessments: list[tuple[Assessment, Job]], apps: list[AppFacts],
             c: Collector) -> list[SourceRow]:
    passed = {j.id for a, j in assessments if a.state in (AssessmentState.scored, AssessmentState.parked)}
    by_job = {x.job.id: x for x in apps}
    rows: dict[uuid.UUID | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for job in jobs:
        sid = c.job_source.get(job.id)
        if c.f.source_id and sid != c.f.source_id:
            continue
        if c.f.country and country_of(job).lower() != c.f.country.strip().lower():
            continue
        r = rows[sid]
        if job.merged_into_id is not None:
            r["duplicates"] += 1
            continue
        r["found"] += 1
        r["passed"] += 1 if job.id in passed else 0
        x = by_job.get(job.id)
        if x and x.sent:
            r["applied"] += 1
            r["replies"] += 1 if x.replied else 0
    out = [SourceRow(source_id=sid, name=c.sources.get(sid, "Unknown source") if sid else "Unknown source",
                     found=r["found"], duplicates=r["duplicates"], passed=r["passed"], applied=r["applied"],
                     replies=r["replies"]) for sid, r in rows.items()]
    return sorted(out, key=lambda r: (-r.found, r.name))


async def _automation(session: AsyncSession, apps: list[AppFacts], c: Collector) -> AutomationOutcomes:
    auto = approved = manual = 0
    for x in apps:
        if not x.sent:
            continue
        by_hand = x.app.applied_outside or x.app.origin != "system" or (x.app.channel == Channel.manual
                                                                         and not x.approved)
        if by_hand:
            manual += 1
        elif x.approver == AUTO_APPROVER:
            auto += 1
        else:
            approved += 1
    uncertain = await session.scalar(select(func.count()).select_from(DispatchAttempt).where(
        DispatchAttempt.status == DispatchStatus.unknown, DispatchAttempt.created_at >= c.start,
        DispatchAttempt.created_at < c.end)) or 0
    blockers = (await session.execute(
        select(PendingAction.type, func.count()).where(
            PendingAction.type.in_(BLOCKER_TYPES), PendingAction.created_at >= c.start,
            PendingAction.created_at < c.end).group_by(PendingAction.type))).all()
    denied: dict[str, int] = defaultdict(int)
    for (reason,) in await session.execute(select(AuditEvent.detail["reason"].astext).where(
            AuditEvent.action == "gateway.permit_denied", AuditEvent.created_at >= c.start,
            AuditEvent.created_at < c.end)):
        denied[(reason or "No reason given")[:200]] += 1
    return AutomationOutcomes(
        auto=auto, approved=approved, manual=manual, uncertain_sends=int(uncertain),
        blockers=sorted((CountRow(key=t.value, count=int(n)) for t, n in blockers),
                        key=lambda r: (-r.count, r.key)),
        permits_denied=sorted((CountRow(key=k, count=n) for k, n in denied.items()),
                              key=lambda r: (-r.count, r.key)))


def _exclusions(assessments: list[tuple[Assessment, Job]]) -> list[CountRow]:
    """Per excluded role, the first hard filter it failed (the one that stopped it)."""
    counts: dict[str, int] = defaultdict(int)
    for a, _ in assessments:
        if a.state != AssessmentState.filtered_out:
            continue
        failed = next((r for r in a.filter_results if r.result == "fail"), None)
        counts[failed.name if failed else "Unspecified"] += 1
    return sorted((CountRow(key=k, count=n) for k, n in counts.items()), key=lambda r: (-r.count, r.key))


async def build_insights(session: AsyncSession, f: InsightFilters, *, period: SpendPeriod = "week",
                         now: datetime | None = None) -> InsightsOut:
    values = await settings_service.values(session)
    tz = ZoneInfo(str(values["general.timezone"]))
    today = (now or utcnow()).astimezone(tz).date()
    until = f.until or today
    since = f.since or until - timedelta(days=int(values["insights.default_range_days"]))
    if since > until:
        since, until = until, since
    min_sample = int(values["insights.min_sample"])
    c = Collector(session, f, since, until, tz)
    await c.load_lookups()
    apps = await c.applications()
    assessments = await c.assessments()
    jobs = await c.jobs()

    sent = sum(1 for x in apps if x.sent)
    interviews = sum(1 for x in apps if x.interviewed)
    notes = ["Reply means the employer answered: screening, interview, offer, or a rejection after sending."]
    if f.channel:
        notes.append("The channel filter applies to applications only; found, filtered and scored counts "
                     "are not split by channel.")

    def track_label(k: str) -> str:
        return "No track" if k == NONE_KEY else c.tracks.get(uuid.UUID(k), "Deleted track")

    def source_label(k: str) -> str:
        return "Unknown source" if k == NONE_KEY else c.sources.get(uuid.UUID(k), "Deleted source")

    return InsightsOut(
        since=since, until=until, filters=f, notes=notes,
        funnel=_funnel(assessments, apps, int(values["scoring.threshold_shortlist"]), c),
        response=RateTables(
            min_sample=min_sample,
            by_track=_rate_rows(apps, lambda x: str(x.track_id) if x.track_id else NONE_KEY, track_label,
                                min_sample),
            by_source=_rate_rows(apps, lambda x: str(x.source_id) if x.source_id else NONE_KEY, source_label,
                                 min_sample),
            by_market=_rate_rows(apps, lambda x: x.country, lambda k: k, min_sample)),
        time_in_stage=_time_in_stage(apps, c.events, min_sample),
        spend=await _spend(session, c, period, str(values["insights.week_start"]),
                           str(values["budget.currency"]), sent, interviews),
        sources=_sources(jobs, assessments, apps, c),
        automation=await _automation(session, apps, c),
        exclusions=_exclusions(assessments))
