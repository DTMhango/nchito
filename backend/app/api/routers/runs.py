"""Runs and schedules. Wave 1 (sources stream: runs, scheduler)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Page, Timestamps, not_implemented
from app.api.crud import add_crud
from app.api.deps import RequireOwner
from app.schemas.json_types import SourceRunResult

router = APIRouter(prefix="/api", tags=["runs"], dependencies=[RequireOwner], responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "runs"

RunKindT = Literal["sweep", "rescore", "expiry_check", "digest", "backup", "retention"]


class RunOut(Timestamps):
    kind: RunKindT
    trigger: str
    campaign_id: uuid.UUID | None
    schedule_id: uuid.UUID | None
    scheduled_for: datetime | None
    dry_run: bool
    counts: dict[str, int]
    source_results: list[SourceRunResult]
    cost_minor: int
    config_versions: dict[str, Any]
    status: Literal["queued", "running", "succeeded", "failed", "partial", "cancelled", "skipped"]
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class RunCreate(BaseModel):
    kind: RunKindT
    campaign_id: uuid.UUID | None = None
    dry_run: bool = False


class ScheduleIn(ApiModel):
    name: str
    kind: RunKindT
    campaign_id: uuid.UUID | None = None
    cron: str = Field(description="Five-field cron in the schedule's time zone")
    timezone: str | None = Field(default=None, description="None: general.timezone")
    enabled: bool = True
    dry_run: bool = False


class ScheduleOut(ScheduleIn, Timestamps):
    next_run_at: datetime | None
    last_enqueued_at: datetime | None
    last_run_id: uuid.UUID | None


@router.get("/runs", response_model=Page[RunOut], name="runs_list")
async def list_runs(kind: RunKindT | None = None, campaign_id: uuid.UUID | None = None,
                    cursor: str | None = None, limit: int = 50) -> Page[RunOut]:
    not_implemented(WAVE, AREA)


@router.get("/runs/{run_id}", response_model=RunOut, name="runs_get")
async def get_run(run_id: uuid.UUID) -> RunOut:
    not_implemented(WAVE, AREA)


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED, name="runs_create")
async def create_run(body: RunCreate) -> RunOut:
    not_implemented(WAVE, AREA)


@router.post("/runs/{run_id}/cancel", response_model=RunOut, name="runs_cancel")
async def cancel_run(run_id: uuid.UUID) -> RunOut:
    not_implemented(WAVE, AREA)


add_crud(router, "/schedules", "schedules", ScheduleIn, ScheduleOut, wave=WAVE, area=AREA)
