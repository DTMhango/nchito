"""Small factories for the tracking tests (fictional employers only)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application, PendingAction, PendingActionType, Stage
from app.models.search import Job, JobSighting
from app.schemas.json_types import StructuredLocation


async def make_job(session: AsyncSession, title: str = "Data Analyst", employer: str = "Acme Ltd", *,
                   url: str | None = None, deadline: date | None = None, country: str | None = None,
                   canonical: str | None = None, tags: list[str] | None = None) -> Job:
    job = Job(title=title, employer=employer, canonical_employer=canonical or employer,
              content_hash=uuid.uuid4().hex.ljust(64, "0"), deadline=deadline, tags=tags or [],
              location=StructuredLocation(country=country) if country else StructuredLocation())
    session.add(job)
    await session.flush()
    if url:
        seen = datetime(2026, 11, 1, tzinfo=UTC)
        session.add(JobSighting(job_id=job.id, url=url, first_seen_at=seen, last_seen_at=seen))
        await session.flush()
    return job


async def make_app(session: AsyncSession, job: Job, stage: Stage = Stage.shortlisted, **kw) -> Application:
    app = Application(job_id=job.id, stage=stage, **kw)
    session.add(app)
    await session.flush()
    return app


async def make_pending(session: AsyncSession, app: Application | None = None, *,
                       type_: PendingActionType = PendingActionType.sign_in, title: str = "Sign in",
                       group_key: str | None = None, deadline: datetime | None = None,
                       detail: dict | None = None, **kw) -> PendingAction:
    action = PendingAction(type=type_, application_id=app.id if app else None, title=title, group_key=group_key,
                           deadline=deadline, detail=detail or {}, **kw)
    session.add(action)
    await session.flush()
    return action
