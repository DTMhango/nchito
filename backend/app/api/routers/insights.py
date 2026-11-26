"""Insights and the Today summary. Today's widgets in wave 1; Insights in wave 4."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, not_implemented
from app.api.deps import RequireOwner, SessionDep
from app.api.routers.pending_actions import DecisionGroup, open_decisions
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm.money import micros_to_minor
from app.models.applications import END_STAGES, Application, InterviewRound, Stage
from app.models.applications import InterviewPack as InterviewPackRow
from app.models.platform import LedgerEntry, LedgerKind
from app.models.search import Assessment, Job, Run, RunKind, Source

router = APIRouter(prefix="/api", tags=["insights"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)


class FunnelStage(BaseModel):
    stage: str
    count: int


class SourceHealthRow(BaseModel):
    source_id: uuid.UUID
    name: str
    status: Literal["ok", "degraded", "failing", "unknown"]
    last_success_at: datetime | None


class SpendMeter(BaseModel):
    month_to_date_minor: int
    reserved_minor: int
    cap_minor: int | None
    currency: str
    estimated_unbilled_minor: int


class UpcomingItem(BaseModel):
    kind: Literal["deadline", "follow_up", "interview"]
    at: datetime | date
    title: str
    job_id: uuid.UUID | None
    application_id: uuid.UUID | None


class LastSweep(BaseModel):
    run_id: uuid.UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    counts: dict[str, int]
    cost_minor: int


class TopMatch(BaseModel):
    job_id: uuid.UUID
    title: str
    employer: str
    score: int | None


class TodayOut(BaseModel):
    needs_you: int = Field(description="Decisions waiting on the owner (a shared blocker counts once)")
    needs_you_groups: list[DecisionGroup] = Field(default_factory=list,
                                                  description="Soonest deadline and biggest consequence first")
    last_sweep_run_id: uuid.UUID | None
    last_sweep: LastSweep | None = None
    funnel: list[FunnelStage]
    sources: list[SourceHealthRow]
    top_match_ids: list[uuid.UUID]
    top_matches: list[TopMatch] = Field(default_factory=list)
    upcoming: list[UpcomingItem]
    spend: SpendMeter


class Series(BaseModel):
    key: str
    points: list[tuple[str, float]]


class InsightsOut(BaseModel):
    funnel_by_campaign: dict[str, list[FunnelStage]]
    response_rate: list[Series]
    time_in_stage_days: dict[str, float]
    spend_by_stage: list[Series]
    spend_by_model: list[Series]


STAGE_ORDER = list(Stage)
PRE_SUBMIT_STAGES = [Stage.shortlisted, Stage.tailoring, Stage.ready, Stage.applying]


async def _spend(session: AsyncSession, now: datetime) -> SpendMeter:
    """Month to date from the ledger, if it has rows (the LLM stream writes them); zeros otherwise."""
    tz = ZoneInfo(str(await settings_service.get_value(session, "general.timezone")))
    local = now.astimezone(tz)
    month_start = datetime.combine(local.date().replace(day=1), time.min, tzinfo=tz).astimezone(UTC)
    currency = str(await settings_service.get_value(session, "budget.currency"))
    cap = await settings_service.get_value(session, "budget.monthly_cap_minor")

    def total(*conds: object) -> object:
        return select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0)).where(
            LedgerEntry.created_at >= month_start, LedgerEntry.currency == currency, *conds)  # type: ignore[arg-type]

    billed = await session.scalar(total(LedgerEntry.kind == LedgerKind.reconciliation,  # type: ignore[arg-type]
                                        LedgerEntry.billed.is_(True)))
    unbilled = await session.scalar(total(LedgerEntry.kind == LedgerKind.reconciliation,  # type: ignore[arg-type]
                                          LedgerEntry.billed.is_(False)))
    closed = select(LedgerEntry.reservation_id).where(
        LedgerEntry.reservation_id.is_not(None),
        LedgerEntry.kind.in_([LedgerKind.reconciliation, LedgerKind.release]))
    reserved = await session.scalar(total(LedgerEntry.kind == LedgerKind.reservation,  # type: ignore[arg-type]
                                          LedgerEntry.id.not_in(closed)))
    return SpendMeter(month_to_date_minor=micros_to_minor(billed or 0), reserved_minor=micros_to_minor(reserved or 0),
                      cap_minor=int(cap) if cap is not None else None, currency=currency,
                      estimated_unbilled_minor=micros_to_minor(unbilled or 0))


def _when(item: UpcomingItem) -> datetime:
    at = item.at
    return at if isinstance(at, datetime) else datetime.combine(at, time.min, tzinfo=UTC)


async def _upcoming(session: AsyncSession, now: datetime, horizon_days: int) -> list[UpcomingItem]:
    """Deadlines of roles not yet applied to, follow-ups and next steps due, and interview rounds."""
    today, until = now.date(), now + timedelta(days=horizon_days)
    items: list[UpcomingItem] = []
    deadlines = await session.execute(
        select(Job.id, Job.title, Job.employer, Job.deadline, Application.id)
        .join(Application, Application.job_id == Job.id)
        .where(Application.stage.in_(PRE_SUBMIT_STAGES), Job.deadline >= today, Job.deadline <= until.date()))
    for job_id, title, employer, deadline, app_id in deadlines:
        items.append(UpcomingItem(kind="deadline", at=deadline, title=f"{title} at {employer} closes",
                                  job_id=job_id, application_id=app_id))
    follow = await session.execute(
        select(Application.id, Application.job_id, Application.next_step, Application.next_due, Job.title,
               Job.employer)
        .join(Job, Job.id == Application.job_id)
        .where(Application.stage.not_in(END_STAGES), Application.next_due.is_not(None),
               Application.next_due <= until.date(),
               Application.snoozed_until.is_(None) | (Application.snoozed_until <= now)))
    for app_id, job_id, step, due, title, employer in follow:
        items.append(UpcomingItem(kind="follow_up", at=due, title=f"{step or 'Next step'}: {title} at {employer}",
                                  job_id=job_id, application_id=app_id))
    rounds = await session.execute(
        select(InterviewRound.scheduled_at, InterviewRound.round_number, Job.id, Job.title, Job.employer,
               InterviewPackRow.application_id)
        .join(InterviewPackRow, InterviewPackRow.id == InterviewRound.pack_id)
        .join(Job, Job.id == InterviewPackRow.job_id)
        .where(InterviewRound.scheduled_at >= now, InterviewRound.scheduled_at <= until))
    for at, number, job_id, title, employer, app_id in rounds:
        items.append(UpcomingItem(kind="interview", at=at, title=f"Interview round {number}: {title} at {employer}",
                                  job_id=job_id, application_id=app_id))
    return sorted(items, key=_when)


@router.get("/today", response_model=TodayOut, name="today_summary")
async def today(session: SessionDep, top: int = Query(default=5, ge=1, le=20),
                horizon_days: int = Query(default=14, ge=1, le=90)) -> TodayOut:
    """Decisions first (shared blockers grouped), then the last sweep, best new matches, what is coming
    up, the funnel, source health and spend."""
    now = utcnow()
    groups = await open_decisions(session)

    run = await session.scalar(select(Run).where(Run.kind == RunKind.sweep, Run.finished_at.is_not(None))
                               .order_by(Run.finished_at.desc()).limit(1))
    last = LastSweep(run_id=run.id, status=run.status.value, started_at=run.started_at, finished_at=run.finished_at,
                     counts=run.counts, cost_minor=micros_to_minor(run.cost_micros)) if run else None

    counts = dict((await session.execute(select(Application.stage, func.count()).group_by(Application.stage))).all())
    funnel = [FunnelStage(stage=s.value, count=int(counts[s])) for s in STAGE_ORDER if counts.get(s)]

    sources = [SourceHealthRow(source_id=src.id, name=src.name, status=src.health.status,
                               last_success_at=src.last_success_at)
               for src in await session.scalars(select(Source).where(Source.enabled.is_(True)).order_by(Source.name))]

    best = func.max(Assessment.score).label("best")
    matches = (await session.execute(
        select(Job.id, Job.title, Job.employer, best).outerjoin(Assessment, Assessment.job_id == Job.id)
        .where(Job.triage.in_(["new", "shortlisted"]), Job.merged_into_id.is_(None),
               Job.id.not_in(select(Application.job_id)))
        .group_by(Job.id).order_by(best.desc().nulls_last(), Job.created_at.desc()).limit(top))).all()
    top_matches = [TopMatch(job_id=r[0], title=r[1], employer=r[2], score=r[3]) for r in matches]

    return TodayOut(
        needs_you=len(groups), needs_you_groups=groups, last_sweep_run_id=run.id if run else None, last_sweep=last,
        funnel=funnel, sources=sources, top_match_ids=[m.job_id for m in top_matches], top_matches=top_matches,
        upcoming=await _upcoming(session, now, horizon_days), spend=await _spend(session, now))


@router.get("/insights", response_model=InsightsOut, name="insights_get")
async def insights(since: date | None = None, campaign_id: uuid.UUID | None = None) -> InsightsOut:
    not_implemented(4, "insights")
