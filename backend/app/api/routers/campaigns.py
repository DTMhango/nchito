"""Campaigns and rubrics (criteria, automation policy, backtest). Wave 1 (filters/scoring stream)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Timestamps, not_implemented
from app.api.crud import add_crud
from app.api.deps import RequireOwner
from app.core.conditions import CampaignRule, ConditionSet
from app.schemas.json_types import (
    AutomationPolicy,
    CampaignBudget,
    CampaignCriteria,
    RubricBody,
    UnknownDataPolicy,
)

router = APIRouter(prefix="/api", tags=["campaigns"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "campaigns"


class CampaignIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    track_id: uuid.UUID | None = None
    priority: int = 0
    criteria: CampaignCriteria = Field(default_factory=CampaignCriteria)
    unknown_data_policy: UnknownDataPolicy = Field(default_factory=UnknownDataPolicy)
    rubric_id: uuid.UUID | None = None
    automation: AutomationPolicy = Field(default_factory=AutomationPolicy)
    budget: CampaignBudget = Field(default_factory=CampaignBudget)
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    schedule_cron: str | None = Field(default=None, description="None: schedule.sweep_cron")
    preferred_seniority: str | None = None


class CampaignOut(CampaignIn, Timestamps):
    status: Literal["draft", "active", "paused", "archived"]
    review_state: Literal["needs_review", "confirmed"]
    confirmed_at: datetime | None = None
    paused_until: date | None = None
    last_sweep_checkpoint: datetime | None = None
    mode_ceiling: Literal["save_only", "prepare", "ask_then_apply", "auto_apply"] = Field(
        description="Highest mode allowed now: 'prepare' until criteria and answers are confirmed")


class CampaignStatusChange(BaseModel):
    status: Literal["active", "paused", "archived"]
    paused_until: date | None = None


class RulePreviewIn(BaseModel):
    conditions: ConditionSet
    limit: int = Field(default=50, ge=1, le=500)


class RulePreviewOut(BaseModel):
    matched: int
    total: int
    sample_job_ids: list[uuid.UUID]


class RubricIn(ApiModel):
    name: str
    body: RubricBody


class RubricOut(RubricIn, Timestamps):
    family: uuid.UUID
    version: int
    status: Literal["draft", "active", "retired"]


class BacktestIn(BaseModel):
    rubric_id: uuid.UUID = Field(description="Draft rubric to test")
    job_ids: list[uuid.UUID] | None = Field(default=None, description="None: recent saved roles")
    campaign_id: uuid.UUID


class BacktestRow(BaseModel):
    job_id: uuid.UUID
    title: str
    employer: str
    old_score: int | None
    new_score: int | None
    old_rank: int | None
    new_rank: int | None
    crossed: list[Literal["shortlist_up", "shortlist_down", "tailor_up", "tailor_down", "auto_up", "auto_down"]]


class BacktestOut(BaseModel):
    rows: list[BacktestRow]
    estimated_cost_minor: int
    cost_currency: str


class DryRunOut(BaseModel):
    run_id: uuid.UUID


add_crud(router, "/campaigns", "campaigns", CampaignIn, CampaignOut, wave=WAVE, area=AREA)
add_crud(router, "/rubrics", "rubrics", RubricIn, RubricOut, wave=WAVE, area=AREA, ops=("list", "get", "create",
                                                                                        "update"))


@router.post("/campaigns/{item_id}/status", response_model=CampaignOut, name="campaigns_set_status")
async def set_campaign_status(item_id: uuid.UUID, body: CampaignStatusChange) -> CampaignOut:
    not_implemented(WAVE, AREA)


@router.post("/campaigns/{item_id}/confirm", response_model=CampaignOut, name="campaigns_confirm")
async def confirm_campaign(item_id: uuid.UUID) -> CampaignOut:
    """Confirm criteria (principle 2). Required before the mode can go above Prepare."""
    not_implemented(WAVE, AREA)


@router.post("/campaigns/{item_id}/clone", response_model=CampaignOut, status_code=status.HTTP_201_CREATED,
             name="campaigns_clone")
async def clone_campaign(item_id: uuid.UUID) -> CampaignOut:
    not_implemented(WAVE, AREA)


@router.post("/campaigns/{item_id}/rules", response_model=CampaignOut, name="campaigns_add_rule")
async def add_campaign_rule(item_id: uuid.UUID, body: CampaignRule) -> CampaignOut:
    """"Use as campaign rule": copies a view's conditions into the campaign as a rule."""
    not_implemented(WAVE, AREA)


@router.post("/campaigns/{item_id}/preview", response_model=RulePreviewOut, name="campaigns_preview_rule")
async def preview_rule(item_id: uuid.UUID, body: RulePreviewIn) -> RulePreviewOut:
    not_implemented(WAVE, AREA)


@router.post("/campaigns/{item_id}/dry-run", response_model=DryRunOut, status_code=status.HTTP_202_ACCEPTED,
             name="campaigns_dry_run")
async def dry_run(item_id: uuid.UUID) -> DryRunOut:
    not_implemented(WAVE, AREA)


@router.post("/rubrics/{item_id}/activate", response_model=RubricOut, name="rubrics_activate")
async def activate_rubric(item_id: uuid.UUID) -> RubricOut:
    """Activating creates a new version; earlier assessments keep their version."""
    not_implemented(WAVE, AREA)


@router.post("/rubrics/backtest", response_model=BacktestOut, name="rubrics_backtest")
async def backtest(body: BacktestIn) -> BacktestOut:
    not_implemented(WAVE, AREA)
