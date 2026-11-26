"""Job corrections: "I applied myself", merge duplicates, split a wrong merge, fix a wrong employer
match (DESIGN.md 18.4, wave 1). Kept apart from ``jobs.py``; the logic is in ``pipeline/corrections.py``."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Ok
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.api.routers.jobs import DeadlineOut, JobDetail, PayOut, SightingOut
from app.core.events import publish
from app.models.applications import Application
from app.models.search import Assessment, Job
from app.pipeline import corrections

router = APIRouter(prefix="/api", tags=["jobs"], dependencies=[RequireOwner], responses=NOT_IMPLEMENTED_RESPONSES)


class AppliedMyselfIn(BaseModel):
    """"I applied myself": counts at once for duplicates, employer limits and follow-ups. No evidence is
    created; the application is marked owner-attested."""

    applied_on: date | None = Field(default=None, description="Defaults to today")
    channel: Literal["email", "browser", "manual"] = "manual"
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = None
    files: list[str] = Field(default_factory=list, description="Names of the files sent, for the record")


class MergeIn(BaseModel):
    duplicate_ids: list[uuid.UUID] = Field(min_length=1)


class SplitIn(BaseModel):
    sighting_urls: list[str] = Field(min_length=1, description="Sightings to move to a new job")


class EmployerFixIn(BaseModel):
    canonical_employer: str = Field(min_length=1, max_length=200)
    remember_alias: bool = True


async def job_detail(session: AsyncSession, job: Job) -> JobDetail:
    """The job as the job page shows it (corrections answer with the fresh job)."""
    await session.refresh(job)
    best = await session.scalar(select(func.max(Assessment.score)).where(Assessment.job_id == job.id))
    app_id = await session.scalar(select(Application.id).where(Application.job_id == job.id)
                                  .order_by(Application.created_at.desc()).limit(1))
    sightings = await corrections.sightings_of(session, job.id)
    return JobDetail(
        id=job.id, created_at=job.created_at, updated_at=job.updated_at, title=job.title, employer=job.employer,
        canonical_employer=job.canonical_employer, location=job.location, triage=job.triage,  # type: ignore[arg-type]
        best_score=best, conflict_state=job.conflict_state.value, conflict_note=job.conflict_note,
        pay=PayOut(state=job.pay_state.value, min_minor=job.pay_min_minor, max_minor=job.pay_max_minor,
                   currency=job.pay_currency, period=job.pay_period),
        deadline=DeadlineOut(state=job.deadline_state.value, on=job.deadline),
        availability=job.availability.value, tags=list(job.tags), pinned=job.pinned, posted_at=job.posted_at,
        recruiter=job.recruiter, requisition_id=job.requisition_id, function=job.function, level=job.level,
        facets=job.facets, custom_facets=job.custom_facets, apply_url=job.apply_url, apply_method=job.apply_method,
        requirements=job.requirements, raw_text=job.raw_text,
        sightings=[SightingOut(source_id=s.source_id, url=s.url, first_seen_at=s.first_seen_at,
                               last_seen_at=s.last_seen_at) for s in sightings],
        notes=job.notes, last_checked_at=job.last_checked_at, repost_of_id=job.repost_of_id, application_id=app_id)


def _error(exc: corrections.CorrectionError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.message)


async def _job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    return job


@router.post("/jobs/{job_id}/applied-myself", response_model=Ok, name="jobs_applied_myself",
             responses={409: {"description": "Already applied to this job"}})
async def applied_myself(job_id: uuid.UUID, body: AppliedMyselfIn, principal: PrincipalDep,
                         session: SessionDep) -> Ok:
    job = await _job(session, job_id)
    try:
        app = await corrections.log_applied_myself(
            session, job, corrections.AppliedMyself(applied_on=body.applied_on, channel=body.channel,
                                                    reference=body.reference, note=body.note, files=body.files),
            actor=principal.actor)
    except corrections.CorrectionError as exc:
        raise _error(exc) from exc
    await publish(session, "application.updated", {"application_id": str(app.id)})
    return Ok()


@router.post("/jobs/{job_id}/merge", response_model=JobDetail, name="jobs_merge")
async def merge(job_id: uuid.UUID, body: MergeIn, principal: PrincipalDep, session: SessionDep) -> JobDetail:
    """Merge duplicates into this job. Sightings, tags, contacts and application history are kept."""
    try:
        result = await corrections.merge_jobs(session, job_id, body.duplicate_ids, actor=principal.actor)
    except corrections.CorrectionError as exc:
        raise _error(exc) from exc
    await publish(session, "job.updated", {"job_id": str(job_id)})
    return await job_detail(session, result.winner)


@router.post("/jobs/{job_id}/split", response_model=JobDetail, name="jobs_split")
async def split(job_id: uuid.UUID, body: SplitIn, principal: PrincipalDep, session: SessionDep) -> JobDetail:
    """Move wrongly merged sightings into their own job (or back to the job they were merged away from).
    Answers with the new job."""
    try:
        result = await corrections.split_job(session, job_id, body.sighting_urls, actor=principal.actor)
    except corrections.CorrectionError as exc:
        raise _error(exc) from exc
    await publish(session, "job.created", {"job_id": str(result.job.id)})
    return await job_detail(session, result.job)


@router.post("/jobs/{job_id}/employer", response_model=JobDetail, name="jobs_fix_employer")
async def fix_employer(job_id: uuid.UUID, body: EmployerFixIn, principal: PrincipalDep,
                       session: SessionDep) -> JobDetail:
    """Set the right canonical employer (for every job posted under the same name), optionally remembering
    it as an alias, then re-evaluate the conflict groups involved."""
    try:
        await corrections.fix_employer(session, job_id, body.canonical_employer,
                                       remember_alias=body.remember_alias, actor=principal.actor)
    except corrections.CorrectionError as exc:
        raise _error(exc) from exc
    await publish(session, "job.updated", {"job_id": str(job_id)})
    return await job_detail(session, await _job(session, job_id))
