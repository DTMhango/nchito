"""Assessments: per job and campaign scores, filter results, overrides. Wave 1 (scoring stream)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.models.search import Assessment, Campaign, Job, Run, RunKind, RunStatus
from app.pipeline import conflicts, filters, scoring
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
    state: Literal["pending", "filtered_out", "scored", "parked"] = "pending"
    base_score: int | None = Field(default=None, description="Rubric score before campaign rules and overrides")


class OverrideIn(BaseModel):
    """Overrides record who and why; they never bypass filters, missing facts or permissions."""

    score: int | None = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=3)


class RescoreIn(BaseModel):
    job_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    campaign_id: uuid.UUID


class RescoreOut(BaseModel):
    run_id: uuid.UUID


async def _default_enqueue(run: Run) -> None:
    from app.worker.queue import enqueue_run

    await enqueue_run(run)


# Replaced in tests; the worker's ``run_pipeline`` calls ``scoring.rescore_handler``.
enqueue: Callable[[Run], Awaitable[None]] = _default_enqueue


def assessment_out(a: Assessment) -> AssessmentOut:
    data = {k: getattr(a, k) for k in AssessmentOut.model_fields if k not in ("state",)}
    data["state"] = getattr(a.state, "value", a.state) or "pending"
    data["is_conflict_winner"] = bool(a.is_conflict_winner)
    return AssessmentOut.model_validate(data)


@router.get("", response_model=Page[AssessmentOut], name="assessments_list")
async def list_assessments(session: SessionDep, job_id: uuid.UUID | None = None, campaign_id: uuid.UUID | None = None,
                           cursor: str | None = None, limit: int = 50) -> Page[AssessmentOut]:
    try:
        offset = filters.decode_cursor(cursor)
    except filters.QueryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    limit = max(1, min(limit, 200))
    stmt = select(Assessment)
    if job_id:
        stmt = stmt.where(Assessment.job_id == job_id)
    if campaign_id:
        stmt = stmt.where(Assessment.campaign_id == campaign_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await session.scalars(stmt.order_by(Assessment.score.desc().nulls_last(), Assessment.id)
                                  .offset(offset).limit(limit))).all()
    return Page(items=[assessment_out(a) for a in rows], total=total,
                next_cursor=filters.encode_cursor(offset + limit) if offset + limit < total else None)


@router.get("/{assessment_id}", response_model=AssessmentOut, name="assessments_get")
async def get_assessment(assessment_id: uuid.UUID, session: SessionDep) -> AssessmentOut:
    a = await session.get(Assessment, assessment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="assessment not found")
    return assessment_out(a)


@router.post("/{assessment_id}/override", response_model=AssessmentOut, name="assessments_override")
async def override(assessment_id: uuid.UUID, body: OverrideIn, session: SessionDep,
                   principal: PrincipalDep) -> AssessmentOut:
    """Record who and why. A score override replaces the rubric score at the score layer only:
    exclusions, eligibility and automation gates still apply."""
    a = await session.get(Assessment, assessment_id, with_for_update=True)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="assessment not found")
    previous = a.override.model_dump() if a.override else None
    a.override = Override(by=principal.actor, reason=body.reason, at=utcnow().isoformat(), score=body.score)
    decision = await scoring.rescore_assessment(session, a)
    await audit.record(session, actor=principal.actor, action="assessment.override", subject_type="assessment",
                       subject_id=a.id, detail={"score": body.score, "reason": body.reason, "previous": previous,
                                                "verdict": decision.verdict})
    job = await session.get(Job, a.job_id)
    if job is not None:
        await conflicts.on_job_changed(session, job)
    await session.refresh(a)
    return assessment_out(a)


@router.post("/rescore", response_model=RescoreOut, status_code=202, name="assessments_rescore")
async def rescore(body: RescoreIn, session: SessionDep, principal: PrincipalDep) -> RescoreOut:
    """Queue a rescore run. One assessment per job and campaign is updated in place, so a rescore
    never duplicates assessments or applications."""
    if await session.get(Campaign, body.campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="campaign not found")
    run = Run(kind=RunKind.rescore, trigger="api", campaign_id=body.campaign_id, status=RunStatus.queued,
              config_versions={"job_ids": [str(j) for j in body.job_ids]})
    session.add(run)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="assessment.rescore_queued", subject_type="run",
                       subject_id=run.id, detail={"jobs": len(body.job_ids)})
    await session.commit()  # the worker must find the run row
    await enqueue(run)
    return RescoreOut(run_id=run.id)
