"""Job corrections: "I applied myself", merge duplicates, split a wrong merge, fix a wrong employer
match (DESIGN.md 18.4, wave 1). Kept apart from ``jobs.py``; the logic is in ``pipeline/corrections.py``."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Ok
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.api.routers.jobs import JobDetail, job_detail
from app.core.events import publish
from app.models.search import Job
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
