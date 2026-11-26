"""Posting change alerts (DESIGN.md 18.4, 10.3a): what changed in a posting, at field level, and what it did.
Detection runs in the scheduled scan and in ``POST /api/jobs/{id}/recheck`` (``pipeline/changes.py``); these
endpoints only read changes and let the owner acknowledge them. A failed fetch is ``unknown``, never ``closed``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import NOT_IMPLEMENTED_RESPONSES
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.models.changes import JobChange, JobWatch
from app.models.search import Job
from app.pipeline import changes

router = APIRouter(prefix="/api", tags=["jobs"], dependencies=[RequireOwner], responses=NOT_IMPLEMENTED_RESPONSES)

ChangeKind = Literal["closed", "reopened", "deadline_moved", "pay_changed", "requirements_changed",
                     "apply_method_changed", "eligibility_changed", "location_changed", "wording"]


class FieldChange(BaseModel):
    kind: ChangeKind
    field: str
    before: Any = None
    after: Any = None
    material: bool
    summary: str = Field(description='e.g. "Work model: remote -> on site"')


class JobChangeOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    employer: str
    detected_at: datetime
    source: str
    material: bool = Field(description="Material changes reassess the role and flag an approved packet")
    kinds: list[str]
    changes: list[FieldChange]
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    application_ids: list[uuid.UUID] = Field(default_factory=list)
    invalidated_packet_ids: list[uuid.UUID] = Field(default_factory=list)
    pending_action_ids: list[uuid.UUID] = Field(default_factory=list)


class WatchOut(BaseModel):
    last_scanned_at: datetime
    last_result: Literal["unchanged", "changed", "closed", "unknown"]
    note: str | None = None


class JobChangesOut(BaseModel):
    job_id: uuid.UUID
    watch: WatchOut | None = Field(default=None, description="When the scheduled scan last looked at this role")
    changes: list[JobChangeOut]


def _out(row: JobChange, job: Job) -> JobChangeOut:
    fx = row.effects or {}
    return JobChangeOut(
        id=row.id, job_id=row.job_id, job_title=job.title, employer=job.employer, detected_at=row.detected_at,
        source=row.source, material=row.material, kinds=list(row.kinds),
        changes=[FieldChange.model_validate(c) for c in row.changes], acknowledged_at=row.acknowledged_at,
        acknowledged_by=row.acknowledged_by, application_ids=[uuid.UUID(i) for i in fx.get("applications", [])],
        invalidated_packet_ids=[uuid.UUID(i) for i in fx.get("invalidated_packets", [])],
        pending_action_ids=[uuid.UUID(i) for i in fx.get("pending_actions", [])])


@router.get("/jobs/{job_id}/changes", response_model=JobChangesOut, name="jobs_changes")
async def job_changes(job_id: uuid.UUID, session: SessionDep) -> JobChangesOut:
    """The change history of one posting, newest first, and when it was last scanned."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    rows = (await session.scalars(select(JobChange).where(JobChange.job_id == job_id)
                                  .order_by(JobChange.detected_at.desc(), JobChange.created_at.desc()))).all()
    watch = await session.scalar(select(JobWatch).where(JobWatch.job_id == job_id))
    return JobChangesOut(
        job_id=job_id, changes=[_out(r, job) for r in rows],
        watch=WatchOut(last_scanned_at=watch.last_scanned_at, last_result=watch.last_result,  # type: ignore[arg-type]
                       note=watch.note) if watch else None)


@router.get("/job-changes", response_model=list[JobChangeOut], name="job_changes_list")
async def list_changes(session: SessionDep, unacknowledged: bool = True, material_only: bool = False,
                       limit: int = Query(default=50, ge=1, le=200)) -> list[JobChangeOut]:
    """Posting changes across all roles, newest first (the alert feed)."""
    stmt = select(JobChange, Job).join(Job, Job.id == JobChange.job_id)
    if unacknowledged:
        stmt = stmt.where(JobChange.acknowledged_at.is_(None))
    if material_only:
        stmt = stmt.where(JobChange.material.is_(True))
    rows = (await session.execute(stmt.order_by(JobChange.detected_at.desc(), JobChange.created_at.desc())
                                  .limit(limit))).all()
    return [_out(c, j) for c, j in rows]


@router.post("/job-changes/{change_id}/acknowledge", response_model=JobChangeOut, name="job_changes_acknowledge")
async def acknowledge_change(change_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> JobChangeOut:
    """"Seen": clears the alert. Pending actions the change opened stay until the owner resolves them."""
    row = await session.get(JobChange, change_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="change not found")
    await changes.acknowledge(session, row, actor=principal.actor)
    job = await session.get(Job, row.job_id)
    assert job is not None
    return _out(row, job)
