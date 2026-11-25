"""Insights and the Today summary. Today's widgets in wave 1; Insights in wave 4."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.common import NOT_IMPLEMENTED_RESPONSES, not_implemented
from app.api.deps import RequireOwner

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


class TodayOut(BaseModel):
    needs_you: int
    last_sweep_run_id: uuid.UUID | None
    funnel: list[FunnelStage]
    sources: list[SourceHealthRow]
    top_match_ids: list[uuid.UUID]
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


@router.get("/today", response_model=TodayOut, name="today_summary")
async def today() -> TodayOut:
    not_implemented(1, "today")


@router.get("/insights", response_model=InsightsOut, name="insights_get")
async def insights(since: date | None = None, campaign_id: uuid.UUID | None = None) -> InsightsOut:
    not_implemented(4, "insights")
