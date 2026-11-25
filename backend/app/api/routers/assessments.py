"""Assessments: per job and campaign scores, filter results, overrides. Wave 1 (scoring stream)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Page, Timestamps, not_implemented
from app.api.deps import RequireOwner
from app.schemas.json_types import CriterionRating, FilterResult, Override

router = APIRouter(prefix="/api/assessments", tags=["assessments"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "scoring"


class AssessmentOut(Timestamps):
    job_id: uuid.UUID
    campaign_id: uuid.UUID
    rubric_id: uuid.UUID | None
    rubric_version: int | None
    filter_results: list[FilterResult]
    ratings: list[CriterionRating]
    score: int | None
    gaps: list[str]
    model: str | None
    cost_minor: int
    cost_currency: str | None
    override: Override | None
    is_conflict_winner: bool


class OverrideIn(BaseModel):
    """Overrides record who and why; they never bypass filters, missing facts or permissions."""

    score: int | None = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=3)


class RescoreIn(BaseModel):
    job_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    campaign_id: uuid.UUID


class RescoreOut(BaseModel):
    run_id: uuid.UUID


@router.get("", response_model=Page[AssessmentOut], name="assessments_list")
async def list_assessments(job_id: uuid.UUID | None = None, campaign_id: uuid.UUID | None = None,
                           cursor: str | None = None, limit: int = 50) -> Page[AssessmentOut]:
    not_implemented(WAVE, AREA)


@router.get("/{assessment_id}", response_model=AssessmentOut, name="assessments_get")
async def get_assessment(assessment_id: uuid.UUID) -> AssessmentOut:
    not_implemented(WAVE, AREA)


@router.post("/{assessment_id}/override", response_model=AssessmentOut, name="assessments_override")
async def override(assessment_id: uuid.UUID, body: OverrideIn) -> AssessmentOut:
    not_implemented(WAVE, AREA)


@router.post("/rescore", response_model=RescoreOut, status_code=202, name="assessments_rescore")
async def rescore(body: RescoreIn) -> RescoreOut:
    not_implemented(WAVE, AREA)
