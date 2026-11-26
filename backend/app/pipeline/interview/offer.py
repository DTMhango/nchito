"""Offering a pack automatically (setting ``interview.auto_offer``).

The periodic tick looks for applications whose stage is ``interview`` and, with ``invite_or_stage``, for
applications with a reply classified as an interview invitation. Each gets one offer: a pack row with
``offered_at`` and either a pending action on Today (the owner says yes, and the resolver queues the
pack) or, with ``interview.auto_generate``, a queued generation straight away (budgeted like any other).
A pack already requested or offered is never offered again. Reading state only, it changes no stage.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    END_STAGES,
    Application,
    InterviewPack,
    MailClassification,
    MailThread,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.search import Job
from app.pipeline.interview import service

OFFER_KIND = "interview_pack_offer"


async def candidates(session: AsyncSession, mode: str) -> list[Application]:
    if mode == "off":
        return []
    rows = list((await session.scalars(select(Application).where(Application.stage == Stage.interview))).all())
    if mode == "invite_or_stage":
        invited = (await session.scalars(select(Application).join(
            MailThread, MailThread.application_id == Application.id).where(
            MailThread.classification == MailClassification.interview,
            Application.stage.not_in(END_STAGES)))).unique().all()
        rows += [a for a in invited if a.id not in {r.id for r in rows}]
    return rows


async def scan(session: AsyncSession, *, now: datetime | None = None) -> list[InterviewPack]:
    """Make the offers due now. Returns packs queued for generation (enqueue them after commit)."""
    now = now or utcnow()
    values = await settings_service.values(session)
    queued: list[InterviewPack] = []
    for app in await candidates(session, str(values["interview.auto_offer"])):
        pack = await service.pack_for_job(session, app.job_id, lock=True)
        if pack is not None and (pack.offered_at is not None or pack.generation > 0):
            continue
        job = await session.get(Job, app.job_id)
        assert job is not None
        pack = await service.get_or_create(session, job)
        pack.application_id = app.id
        pack.offered_at = now
        why = "interview stage" if app.stage == Stage.interview else "interview invitation"
        if values["interview.auto_generate"]:
            pack, _ = await service.request(session, job, actor="system")
            queued.append(pack)
        else:
            session.add(PendingAction(
                type=PendingActionType.follow_up, application_id=app.id, status=PendingStatus.open,
                group_key=f"interview_pack:{job.id}",
                title=f"Interview with {job.employer} ({job.title}): build the interview pack?",
                detail={"kind": OFFER_KIND, "job_id": str(job.id), "pack_id": str(pack.id), "reason": why}))
        await audit.record(session, actor="system", action="interview.offered", subject_type="interview_pack",
                           subject_id=pack.id, detail={"job_id": str(job.id), "reason": why,
                                                       "generated": bool(values["interview.auto_generate"])})
        await session.flush()
    return queued


async def accept_offer(session: AsyncSession, action: PendingAction, *, actor: str) -> None:
    """Resolver for an approved offer: queue the pack (the tick defers queued packs to the worker)."""
    job = await session.get(Job, uuid.UUID(str(action.detail["job_id"])))
    if job is None:
        raise service.InterviewError("the role no longer exists", 404, "not_found")
    await service.request(session, job, actor=actor)
