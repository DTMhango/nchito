"""Interview pack endpoints (DESIGN.md 10.3a): the pack per job, generation, sections, practice, export, rounds.

Errors are ``{"detail": {"code", "reason"}}``. Generation is queued (202) and idempotent while a request is
open; the worker builds it section by section within the budget.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import Field
from sqlalchemy import select

from app.api.common import ApiModel, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.settings import service as settings_service
from app.llm.client import LLMError
from app.llm.deps import llm_service
from app.llm.service import LLMService
from app.models.applications import InterviewPack, InterviewPractice, InterviewRound
from app.models.search import Job
from app.pipeline.interview import export, practice, service
from app.schemas.json_types import CheckResult

router = APIRouter(prefix="/api", tags=["interview"], dependencies=[RequireOwner])

LLMDep = Annotated[LLMService, Depends(llm_service)]
PackEnqueue = Callable[[InterviewPack], Awaitable[None]]


class InterviewPackOut(Timestamps):
    job_id: uuid.UUID
    application_id: uuid.UUID | None
    sections: dict[str, Any] = Field(description="Section key -> current version: version, origin, status, "
                                                 "flagged, fact_ids, content, check_results, model")
    generated_at: datetime | None
    model: str | None
    status: Literal["idle", "queued", "running", "paused", "done", "failed"] = "idle"
    generation: int = 0
    pending_sections: list[str] = Field(default_factory=list)
    basis: dict[str, Any] | None = Field(default=None, description="What the pack was built from: the submitted "
                                                                   "packet, the latest checked spec, or none")
    notes: dict[str, str] = Field(default_factory=dict, description="Owner notes per section")
    estimate_micros: int | None = None
    cost_micros: int = 0
    error: str | None = None
    offered_at: datetime | None = None
    flagged: list[str] = Field(default_factory=list, description="Sections that failed the truth checks")


class InterviewGenerateIn(ApiModel):
    sections: list[str] | None = Field(default=None, description="Default: every section in interview.sections")


class InterviewEstimateOut(ApiModel):
    sections: dict[str, int] = Field(description="Upper-bound cost per model-built section, micros")
    total_micros: int
    currency: str


class InterviewSectionOut(Timestamps):
    section: str
    version: int
    origin: Literal["generated", "code", "owner"]
    content: dict[str, Any]
    fact_ids: list[str]
    check_results: list[CheckResult]
    status: Literal["pass", "warn", "block"]
    flagged: bool
    model: str | None
    created_by: str


class InterviewSectionIn(ApiModel):
    content: dict[str, Any]


class InterviewNoteIn(ApiModel):
    note: str | None = Field(default=None, max_length=20_000)


class FavouriteIn(ApiModel):
    favourite: bool = True


class StoryEditIn(ApiModel):
    """Only the fields given change. ``base_version``: the ``stories`` version the edit was made on."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    requirement: str | None = Field(default=None, max_length=2000)
    situation: str | None = Field(default=None, max_length=2000)
    task: str | None = Field(default=None, max_length=2000)
    action: str | None = Field(default=None, max_length=2000)
    result: str | None = Field(default=None, max_length=2000)
    base_version: int | None = None


class PracticeIn(ApiModel):
    question: str = Field(min_length=1, max_length=2000)
    category: Literal["behavioural", "technical", "role", "motivation", "logistics"] | None = None
    draft_answer: str = Field(min_length=1)


class PracticeOut(Timestamps):
    pack_id: uuid.UUID
    question: str
    category: str | None
    draft_answer: str
    status: Literal["done", "paused", "failed"]
    feedback: dict[str, Any] | None
    check_results: list[CheckResult]
    model: str | None
    cost_micros: int
    error: str | None


class InterviewRoundIn(ApiModel):
    round_number: int = Field(ge=1)
    scheduled_at: datetime | None = None
    format: str | None = None
    interviewers: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    notes: str | None = None
    learnt: str | None = None


class InterviewRoundOut(InterviewRoundIn, Timestamps):
    pack_id: uuid.UUID
    thank_you_draft: str | None


async def get_interview_enqueue() -> PackEnqueue:
    """Defers pack generation to the worker (tests replace this dependency)."""

    async def enqueue(pack: InterviewPack) -> None:
        from app.pipeline.interview.tasks import enqueue as defer
        from app.worker.queue import queue_app

        async with queue_app.open_async():
            await defer(pack)

    return enqueue


EnqueueDep = Annotated[PackEnqueue, Depends(get_interview_enqueue)]


def _error(exc: service.InterviewError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "reason": str(exc)})


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "reason": f"{what} not found"})


async def _job(session: SessionDep, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise _not_found("job")
    return job


async def _pack(session: SessionDep, job_id: uuid.UUID, *, lock: bool = False) -> InterviewPack:
    pack = await service.pack_for_job(session, job_id, lock=lock)
    if pack is None:
        raise _not_found("interview pack")
    return pack


async def _pack_out(session: SessionDep, pack: InterviewPack) -> InterviewPackOut:
    await session.refresh(pack)
    out = InterviewPackOut.model_validate(pack)
    out.flagged = sorted(k for k, v in (pack.sections or {}).items() if v.get("flagged"))
    return out


async def _estimate(session: SessionDep, client: LLMService, job: Job, sections: list[str] | None) -> int | None:
    try:
        return sum((await service.estimate(session, client, job, sections)).values())
    except LLMError:
        return None  # no route or price yet: generation reports the problem itself


@router.get("/jobs/{job_id}/interview-pack", response_model=InterviewPackOut, name="interview_pack_get")
async def interview_pack(job_id: uuid.UUID, session: SessionDep) -> InterviewPackOut:
    return await _pack_out(session, await _pack(session, job_id))


@router.post("/jobs/{job_id}/interview-pack", response_model=InterviewPackOut,
             status_code=status.HTTP_202_ACCEPTED, name="interview_pack_generate")
async def generate_interview_pack(job_id: uuid.UUID, principal: PrincipalDep, session: SessionDep,
                                  client: LLMDep, enqueue: EnqueueDep,
                                  body: InterviewGenerateIn | None = None) -> InterviewPackOut:
    """Queue the pack (or the listed sections). Idempotent while a request is open. The estimate is
    stored on the pack; each section reserves its own spend when it is built."""
    job = await _job(session, job_id)
    sections = body.sections if body else None
    cost = await _estimate(session, client, job, sections)
    try:
        pack, needs_queue = await service.request(session, job, actor=principal.actor, sections=sections,
                                                  estimate_micros=cost)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.commit()
    if needs_queue:
        await enqueue(pack)
    return await _pack_out(session, pack)


@router.get("/jobs/{job_id}/interview-pack/estimate", response_model=InterviewEstimateOut,
            name="interview_pack_estimate")
async def estimate_interview_pack(job_id: uuid.UUID, session: SessionDep, client: LLMDep,
                                  sections: Annotated[list[str] | None, Query()] = None) -> InterviewEstimateOut:
    job = await _job(session, job_id)
    try:
        per = await service.estimate(session, client, job, sections)
    except LLMError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "refused", "reason": str(exc)}) from exc
    values = await settings_service.values(session)
    return InterviewEstimateOut(sections=per, total_micros=sum(per.values()), currency=values["budget.currency"])


@router.post("/jobs/{job_id}/interview-pack/sections/{section}/regenerate", response_model=InterviewPackOut,
             status_code=status.HTTP_202_ACCEPTED, name="interview_section_regenerate")
async def regenerate_section(job_id: uuid.UUID, section: str, principal: PrincipalDep, session: SessionDep,
                             client: LLMDep, enqueue: EnqueueDep) -> InterviewPackOut:
    """A new version of one section (the crib sheet follows); earlier versions stay."""
    job = await _job(session, job_id)
    cost = await _estimate(session, client, job, [section])
    try:
        pack, needs_queue = await service.request(session, job, actor=principal.actor, sections=[section],
                                                  estimate_micros=cost)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    if not needs_queue:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "still_queued",
                                                              "reason": "the pack is already being generated"})
    await session.commit()
    await enqueue(pack)
    return await _pack_out(session, pack)


@router.put("/jobs/{job_id}/interview-pack/sections/{section}", response_model=InterviewSectionOut,
            name="interview_section_edit")
async def edit_section(job_id: uuid.UUID, section: str, body: InterviewSectionIn, principal: PrincipalDep,
                       session: SessionDep) -> InterviewSectionOut:
    """An owner edit: stored as a new version and checked like a generated one."""
    pack = await _pack(session, job_id, lock=True)
    try:
        row = await service.edit(session, pack, section, body.content, actor=principal.actor)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.refresh(row)
    return InterviewSectionOut.model_validate(row)


@router.get("/jobs/{job_id}/interview-pack/sections/{section}/versions", response_model=list[InterviewSectionOut],
            name="interview_section_versions")
async def section_versions(job_id: uuid.UUID, section: str, session: SessionDep) -> list[InterviewSectionOut]:
    pack = await _pack(session, job_id)
    return [InterviewSectionOut.model_validate(r) for r in await service.versions_of(session, pack.id, section)]


@router.put("/jobs/{job_id}/interview-pack/sections/{section}/note", response_model=InterviewPackOut,
            name="interview_section_note")
async def section_note(job_id: uuid.UUID, section: str, body: InterviewNoteIn, principal: PrincipalDep,
                       session: SessionDep) -> InterviewPackOut:
    pack = await _pack(session, job_id, lock=True)
    try:
        await service.set_note(session, pack, section, body.note, actor=principal.actor)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.flush()
    return await _pack_out(session, pack)


@router.put("/jobs/{job_id}/interview-pack/stories/{story_id}/favourite", response_model=InterviewSectionOut,
            name="interview_story_favourite")
async def story_favourite(job_id: uuid.UUID, story_id: str, body: FavouriteIn, principal: PrincipalDep,
                          session: SessionDep) -> InterviewSectionOut:
    pack = await _pack(session, job_id, lock=True)
    try:
        row = await service.set_favourite(session, pack, story_id, body.favourite, actor=principal.actor)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.refresh(row)
    return InterviewSectionOut.model_validate(row)


@router.put("/jobs/{job_id}/interview-pack/stories/{story_id}", response_model=InterviewSectionOut,
            name="interview_story_edit")
async def story_edit(job_id: uuid.UUID, story_id: str, body: StoryEditIn, principal: PrincipalDep,
                     session: SessionDep) -> InterviewSectionOut:
    """Rewrite one story (STAR text, title): stored as a new ``stories`` version and checked like any edit. 409
    ``version_conflict`` when ``base_version`` is not the current version."""
    pack = await _pack(session, job_id, lock=True)
    changes = body.model_dump(exclude={"base_version"}, exclude_none=True)
    try:
        row = await service.edit_story(session, pack, story_id, changes, actor=principal.actor,
                                       base_version=body.base_version)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.refresh(row)
    return InterviewSectionOut.model_validate(row)


@router.get("/jobs/{job_id}/interview-pack/practice", response_model=list[PracticeOut],
            name="interview_practice_list")
async def practice_list(job_id: uuid.UUID, session: SessionDep) -> list[PracticeOut]:
    pack = await _pack(session, job_id)
    rows = await session.scalars(select(InterviewPractice).where(InterviewPractice.pack_id == pack.id)
                                 .order_by(InterviewPractice.created_at.desc()))
    return [PracticeOut.model_validate(r) for r in rows]


@router.post("/jobs/{job_id}/interview-pack/practice", response_model=PracticeOut,
             status_code=status.HTTP_201_CREATED, name="interview_practice_create")
async def practice_create(job_id: uuid.UUID, body: PracticeIn, principal: PrincipalDep, session: SessionDep,
                          client: LLMDep) -> PracticeOut:
    """Feedback on a draft answer (one budgeted call). A budget refusal stores the attempt ``paused``."""
    job = await _job(session, job_id)
    pack = await service.get_or_create(session, job)
    try:
        row = await practice.attempt(session, client, pack, question=body.question, draft=body.draft_answer,
                                     category=body.category, actor=principal.actor)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.refresh(row)
    return PracticeOut.model_validate(row)


@router.post("/interview-practice/{practice_id}/retry", response_model=PracticeOut, name="interview_practice_retry")
async def practice_retry(practice_id: uuid.UUID, principal: PrincipalDep, session: SessionDep,
                         client: LLMDep) -> PracticeOut:
    row = await session.get(InterviewPractice, practice_id, with_for_update=True)
    if row is None:
        raise _not_found("practice answer")
    if row.status == "done":
        await session.refresh(row)
    return PracticeOut.model_validate(row)
    pack = await session.get(InterviewPack, row.pack_id)
    assert pack is not None
    try:
        row = await practice.attempt(session, client, pack, question=row.question, draft=row.draft_answer,
                                     category=row.category, actor=principal.actor, row=row)
    except service.InterviewError as exc:
        raise _error(exc) from exc
    await session.refresh(row)
    return PracticeOut.model_validate(row)


@router.get("/jobs/{job_id}/interview-pack/export", name="interview_pack_export",
            responses={200: {"content": {m: {} for m in export.MIME.values()}}})
async def export_pack(job_id: uuid.UUID, session: SessionDep,
                      fmt: Annotated[export.ExportFmt, Query()] = "pdf") -> Response:
    job = await _job(session, job_id)
    pack = await _pack(session, job_id)
    values = await settings_service.values(session)
    current = await service.current_versions(session, pack.id)
    if not current:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "empty", "reason": "nothing generated yet"})
    order = [*service.configured_sections(values), *sorted(k for k in current
                                                           if k not in service.configured_sections(values))]
    data = export.render(export.build(job, order, current, pack.notes or {}), fmt)
    return Response(content=data, media_type=export.MIME[fmt], headers={
        "Content-Disposition": f'attachment; filename="interview-pack-{job.id}.{fmt}"',
        "X-Flagged-Sections": ",".join(sorted(k for k, v in current.items() if v.flagged))})


@router.get("/jobs/{job_id}/interview-pack/rounds", response_model=list[InterviewRoundOut],
            name="interview_rounds_list")
async def list_rounds(job_id: uuid.UUID, session: SessionDep) -> list[InterviewRoundOut]:
    pack = await _pack(session, job_id)
    rows = await session.scalars(select(InterviewRound).where(InterviewRound.pack_id == pack.id)
                                 .order_by(InterviewRound.round_number, InterviewRound.created_at))
    return [InterviewRoundOut.model_validate(r) for r in rows]


@router.post("/jobs/{job_id}/interview-pack/rounds", response_model=InterviewRoundOut,
             status_code=status.HTTP_201_CREATED, name="interview_rounds_create")
async def create_round(job_id: uuid.UUID, body: InterviewRoundIn, principal: PrincipalDep,
                       session: SessionDep) -> InterviewRoundOut:
    pack = await service.get_or_create(session, await _job(session, job_id))
    row = InterviewRound(pack_id=pack.id, **body.model_dump())
    session.add(row)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="interview.round_added", subject_type="interview_pack",
                       subject_id=pack.id, detail={"round_id": str(row.id), "round_number": row.round_number})
    await session.refresh(row)
    return InterviewRoundOut.model_validate(row)


@router.put("/interview-rounds/{round_id}", response_model=InterviewRoundOut, name="interview_rounds_update")
async def update_round(round_id: uuid.UUID, body: InterviewRoundIn, principal: PrincipalDep,
                       session: SessionDep) -> InterviewRoundOut:
    row = await session.get(InterviewRound, round_id, with_for_update=True)
    if row is None:
        raise _not_found("interview round")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="interview.round_updated",
                       subject_type="interview_pack", subject_id=row.pack_id, detail={"round_id": str(row.id)})
    await session.refresh(row)
    return InterviewRoundOut.model_validate(row)

