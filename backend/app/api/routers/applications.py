"""Applications: board, Studio (spec, checks, packet, approval receipt), dispatch, manual handoff,
timeline, contacts, mail threads, interview pack, global pause. Waves 1-3."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Ok, Page, Timestamps, not_implemented
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import autopilot, stages
from app.apply.autopilot import AutopilotState, AutopilotWrite
from app.connect.mail_sync import SyncResult, act_on_thread
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.events import publish
from app.core.settings import service as settings_service
from app.kit.importers import history
from app.models.applications import (
    Application,
    ApplicationEvent,
    Channel,
    Contact,
    MailClassification,
    MailThread,
    PendingAction,
    PendingStatus,
    Stage,
)
from app.models.search import Assessment, Job
from app.pipeline import corrections
from app.schemas.json_types import (
    ApplicationSpec,
    CheckResult,
    Evidence,
    GateResult,
    PacketContents,
    SubmittedSnapshot,
)

MAX_IMPORT_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api", tags=["applications"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)

StageT = Literal["shortlisted", "tailoring", "ready", "applying", "submitted_unconfirmed", "submitted",
                 "screening", "interview", "offer", "accepted", "rejected", "withdrawn", "closed", "skipped"]
ChannelT = Literal["email", "browser", "manual"]


class ApplicationSummary(Timestamps):
    job_id: uuid.UUID
    campaign_id: uuid.UUID | None
    stage: StageT
    channel: ChannelT | None
    title: str
    employer: str
    score: int | None
    next_step: str | None
    next_due: date | None
    pinned: bool
    open_pending_actions: int
    applied_at: datetime | None
    snoozed_until: datetime | None = None
    snoozed: bool = Field(default=False, description="Snoozed right now (an imminent deadline overrides a snooze)")
    deadline: date | None = Field(default=None, description="The job's closing date, when dated")
    origin: Literal["system", "owner", "import"] = "system"
    owner_attested: bool = Field(default=False, description="Applied outside Nchito, on the owner's word")
    legacy_fit: int | None = Field(default=None, ge=1, le=5, description="Imported 1-5 fit; not a rubric score")


class ApplicationDetail(ApplicationSummary):
    spec: ApplicationSpec
    check_results: list[CheckResult]
    approved_packet_id: uuid.UUID | None
    submitted_snapshot: SubmittedSnapshot | None
    confirmation_evidence: list[Evidence]
    applied_outside: bool
    notes: str | None = None
    reference: str | None = None
    apply_url: str | None = None
    ended_at: datetime | None = None
    allowed_next: list[StageT] = Field(default_factory=list, description="Stages the owner can move it to now")


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID
    campaign_id: uuid.UUID | None = None


class ApplicationPatch(BaseModel):
    """Only the fields sent change; send null to clear a date or the snooze."""

    next_step: str | None = Field(default=None, max_length=300)
    next_due: date | None = None
    pinned: bool | None = None
    snoozed_until: datetime | None = None
    channel: ChannelT | None = None
    notes: str | None = None


class StageChangeIn(BaseModel):
    """Dragging to `submitted` never creates evidence: use 'I applied myself' instead."""

    stage: StageT
    note: str | None = None


class BoardColumn(BaseModel):
    stage: StageT
    count: int
    items: list[ApplicationSummary]


class BoardOut(BaseModel):
    columns: list[BoardColumn]


class AppliedMyselfCreate(BaseModel):
    """Log an application made outside Nchito, for an existing job or one created from what is known."""

    job_id: uuid.UUID | None = None
    url: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    employer: str | None = Field(default=None, max_length=200)
    applied_on: date | None = Field(default=None, description="Defaults to today")
    channel: ChannelT = "manual"
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = None
    files: list[str] = Field(default_factory=list, description="Names of the files sent, for the record")
    campaign_id: uuid.UUID | None = None


class ImportFieldChange(BaseModel):
    field: str
    before: Any
    after: Any


class ImportRowOut(BaseModel):
    line: int
    key: str
    company: str
    role: str
    stage: StageT
    action: Literal["create", "update", "unchanged", "skip", "error"]
    job: Literal["new", "existing"] | None
    changes: list[ImportFieldChange]
    messages: list[str]
    application_id: uuid.UUID | None = None


class ImportErrorOut(BaseModel):
    line: int
    id: str | None
    message: str


class ImportPreviewOut(BaseModel):
    """What importing this file would change. Nothing is written until it is confirmed."""

    content_hash: str = Field(description="Pass back when confirming, to be sure the same file is applied")
    create: int
    update: int
    unchanged: int
    skip: int
    errors: list[ImportErrorOut]
    rows: list[ImportRowOut]


class ImportResultOut(BaseModel):
    created: int
    updated: int
    unchanged: int
    skipped: int
    errors: int
    application_ids: list[uuid.UUID]


class SpecUpdate(BaseModel):
    spec: ApplicationSpec


class TailorOut(BaseModel):
    run_id: uuid.UUID | None
    queued: bool


class PacketOut(Timestamps):
    application_id: uuid.UUID
    version: int
    content_hash: str
    contents: PacketContents
    approved_at: datetime | None
    approved_by: str | None
    invalidated_at: datetime | None
    invalidated_reason: str | None


class PacketChange(BaseModel):
    path: str
    before: Any
    after: Any
    material: bool


class ReceiptOut(BaseModel):
    """The approval receipt (18.2): the one screen the owner approves from."""

    application_id: uuid.UUID
    packet: PacketOut
    employer: str
    destination: str
    role: str
    pay_answers: list[str]
    work_rights_answers: list[str]
    attachments: list[str]
    unusual_disclosures: list[str]
    changes_since_last_look: list[PacketChange]
    action_label: str = Field(description="e.g. 'Send email to recruiter', 'Let the agent submit'")
    gates: list[GateResult]


class ApproveIn(BaseModel):
    packet_version: int
    packet_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel: ChannelT
    waivers: list[uuid.UUID] = Field(default_factory=list, description="Guardrail ids waived once, with reasons")
    waiver_reason: str | None = None


class DispatchOut(Timestamps):
    application_id: uuid.UUID
    packet_hash: str
    channel: ChannelT
    status: Literal["reserved", "handed_off", "sent", "acknowledged", "bounced", "failed", "unknown", "cancelled"]
    send_after: datetime | None
    provider_message_id: str | None
    outcome_at: datetime | None
    gate_results: list[GateResult]
    error: str | None


class ManualHandoffOut(BaseModel):
    posting_url: str | None
    files: list[str] = Field(description="Signed download URLs for the final PDFs")
    answers: list[dict[str, str]]
    remaining_steps: list[str]


class MarkSubmittedIn(BaseModel):
    reference: str | None = None
    note: str | None = None


class TimelineEvent(BaseModel):
    id: uuid.UUID
    created_at: datetime
    kind: str
    actor: str
    detail: dict[str, Any]


class ReleaseRecord(BaseModel):
    """What a runner was given and what it reports having entered (18.1)."""

    agent_task_id: uuid.UUID
    released: dict[str, Any]
    entered: dict[str, Any]


class ContactIn(ApiModel):
    job_id: uuid.UUID
    name: str
    role: str | None = None
    email: str | None = None
    link: str | None = None
    notes: str | None = None


class ContactOut(ContactIn, Timestamps):
    origin: str


MailClassT = Literal["confirmation", "rejection", "interview", "information_request", "other"]


class MailThreadOut(Timestamps):
    application_id: uuid.UUID | None
    subject: str | None
    classification: MailClassT
    match_confidence: float | None
    needs_review: bool
    sender: str | None = None
    last_message_at: datetime | None = None


class MailThreadLink(BaseModel):
    application_id: uuid.UUID | None
    classification: MailClassT | None = None


class InterviewPackOut(Timestamps):
    job_id: uuid.UUID
    application_id: uuid.UUID | None
    sections: dict[str, Any]
    generated_at: datetime | None
    model: str | None


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


# ----- helpers --------------------------------------------------------------------------------------


def _illegal(exc: stages.IllegalTransition) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={
        "code": "illegal_transition", "reason": exc.reason, "from": exc.current.value, "to": exc.target.value})


def _corrections_error(exc: corrections.CorrectionError) -> HTTPException:
    return HTTPException(exc.status, detail=exc.message)


def _score_subquery() -> Any:
    any_score = (select(func.max(Assessment.score)).where(Assessment.job_id == Application.job_id)
                 .correlate(Application).scalar_subquery())
    campaign_score = (select(func.max(Assessment.score)).where(
        Assessment.job_id == Application.job_id, Assessment.campaign_id == Application.campaign_id)
        .correlate(Application).scalar_subquery())
    return func.coalesce(campaign_score, any_score)


def _open_pending_subquery() -> Any:
    return (select(func.count()).select_from(PendingAction).where(
        PendingAction.application_id == Application.id, PendingAction.status == PendingStatus.open)
        .correlate(Application).scalar_subquery())


def _snoozed_sql(now: datetime, days: int) -> Any:
    today = now.date()
    soon = today + timedelta(days=days)
    imminent = or_(func.coalesce(and_(Job.deadline >= today, Job.deadline <= soon), False),
                   func.coalesce(Application.next_due <= soon, False))
    return and_(func.coalesce(Application.snoozed_until > now, False), not_(imminent))


def _summary_fields(app: Application, job: Job, score: int | None, open_pending: int, now: datetime,
                    days: int) -> dict[str, Any]:
    today = now.date()
    job_deadline = job.deadline if job.deadline and job.deadline >= today else None
    return {
        "id": app.id, "created_at": app.created_at, "updated_at": app.updated_at, "job_id": app.job_id,
        "campaign_id": app.campaign_id, "stage": app.stage.value,
        "channel": app.channel.value if app.channel else None,
        "title": job.title, "employer": job.employer, "score": score, "next_step": app.next_step,
        "next_due": app.next_due, "pinned": app.pinned, "open_pending_actions": open_pending,
        "applied_at": app.applied_at, "snoozed_until": app.snoozed_until,
        "snoozed": stages.is_snoozed(app.snoozed_until, now, deadlines=[job_deadline, app.next_due],
                                     imminent_days=days),
        "deadline": job.deadline, "origin": app.origin, "owner_attested": app.owner_attested,
        "legacy_fit": app.legacy_fit,
    }


async def _imminent_days(session: AsyncSession) -> int:
    return int(await settings_service.get_value(session, "tracking.imminent_deadline_days"))


def _filters(stage: str | None, campaign_id: uuid.UUID | None, channel: str | None, q: str | None,
             pinned: bool | None) -> list[Any]:
    conds: list[Any] = []
    if stage:
        conds.append(Application.stage == Stage(stage))
    if campaign_id:
        conds.append(Application.campaign_id == campaign_id)
    if channel:
        conds.append(Application.channel == Channel(channel))
    if pinned is not None:
        conds.append(Application.pinned == pinned)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(Job.title.ilike(like), Job.employer.ilike(like), Job.canonical_employer.ilike(like),
                         Application.notes.ilike(like), Application.next_step.ilike(like),
                         Application.reference.ilike(like)))
    return conds


_ORDER = (Application.pinned.desc(), Application.next_due.asc().nulls_last(), Application.updated_at.desc(),
          Application.id)


async def _select_summaries(session: AsyncSession, conds: list[Any], *, offset: int = 0,
                            limit: int | None = None) -> list[ApplicationSummary]:
    now = utcnow()
    days = await _imminent_days(session)
    stmt = (select(Application, Job, _score_subquery(), _open_pending_subquery())
            .join(Job, Job.id == Application.job_id).where(*conds).order_by(*_ORDER).offset(offset))
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    return [ApplicationSummary(**_summary_fields(a, j, s, int(n or 0), now, days)) for a, j, s, n in rows]


async def _detail(session: AsyncSession, application_id: uuid.UUID) -> ApplicationDetail:
    now = utcnow()
    days = await _imminent_days(session)
    row = (await session.execute(
        select(Application, Job, _score_subquery(), _open_pending_subquery())
        .join(Job, Job.id == Application.job_id).where(Application.id == application_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    app, job, score, pending = row
    await session.refresh(app)
    return ApplicationDetail(
        **_summary_fields(app, job, score, int(pending or 0), now, days), spec=app.spec,
        check_results=app.check_results, approved_packet_id=app.approved_packet_id,
        submitted_snapshot=app.submitted_snapshot, confirmation_evidence=app.confirmation_evidence,
        applied_outside=app.applied_outside, notes=app.notes, reference=app.reference, apply_url=job.apply_url,
        ended_at=app.ended_at, allowed_next=[s.value for s in stages.allowed_targets(app)])


async def _load(session: AsyncSession, application_id: uuid.UUID) -> Application:
    app = await session.get(Application, application_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    return app


async def _changed(session: AsyncSession, application_id: uuid.UUID) -> None:
    await publish(session, "application.updated", {"application_id": str(application_id)})


# ----- applications -----------------------------------------------------------------------


@router.get("/applications", response_model=Page[ApplicationSummary], name="applications_list")
async def list_applications(
    session: SessionDep, stage: StageT | None = None, campaign_id: uuid.UUID | None = None,
    channel: ChannelT | None = None, q: str | None = None, pinned: bool | None = None,
    hide_snoozed: bool = False, cursor: str | None = None, limit: int = Query(default=100, ge=1, le=500),
) -> Page[ApplicationSummary]:
    conds = _filters(stage, campaign_id, channel, q, pinned)
    if hide_snoozed:
        conds.append(not_(_snoozed_sql(utcnow(), await _imminent_days(session))))
    try:
        offset = int(cursor) if cursor else 0
    except ValueError as exc:
        raise HTTPException(422, detail="bad cursor") from exc
    total = await session.scalar(select(func.count()).select_from(Application)
                                 .join(Job, Job.id == Application.job_id).where(*conds))
    items = await _select_summaries(session, conds, offset=offset, limit=limit + 1)
    more = len(items) > limit
    return Page[ApplicationSummary](items=items[:limit], total=int(total or 0),
                                    next_cursor=str(offset + limit) if more else None)


@router.get("/applications/board", response_model=BoardOut, name="applications_board")
async def board(session: SessionDep, campaign_id: uuid.UUID | None = None, channel: ChannelT | None = None,
                q: str | None = None, hide_snoozed: bool = False,
                per_column: int = Query(default=50, ge=1, le=200)) -> BoardOut:
    """Applications grouped by stage, every stage present (empty columns included)."""
    base = _filters(None, campaign_id, channel, q, None)
    if hide_snoozed:
        base.append(not_(_snoozed_sql(utcnow(), await _imminent_days(session))))
    counts = dict((await session.execute(
        select(Application.stage, func.count()).join(Job, Job.id == Application.job_id).where(*base)
        .group_by(Application.stage))).all())
    columns = []
    for st in Stage:
        n = int(counts.get(st, 0))
        items = await _select_summaries(session, [*base, Application.stage == st], limit=per_column) if n else []
        columns.append(BoardColumn(stage=st.value, count=n, items=items))
    return BoardOut(columns=columns)


@router.post("/applications", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED,
             name="applications_create", responses={409: {"description": "The job already has an application"}})
async def create_application(body: ApplicationCreate, principal: PrincipalDep,
                             session: SessionDep) -> ApplicationDetail:
    job = await session.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    if job.merged_into_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="this job was merged into another; use that one")
    existing = await stages.blocking_application(session, job.id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "duplicate", "reason": f"this job already has an application ({existing.stage.value})",
            "application_id": str(existing.id)})
    app = Application(job_id=job.id, campaign_id=body.campaign_id, stage=Stage.shortlisted, origin="owner")
    session.add(app)
    await session.flush()
    await stages.add_event(session, app.id, "created", principal.actor, {"origin": "owner"})
    await _changed(session, app.id)
    return await _detail(session, app.id)


@router.post("/applications/applied-myself", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED,
             name="applications_applied_myself", responses={409: {"description": "Already applied to this job"}})
async def applied_myself(body: AppliedMyselfCreate, principal: PrincipalDep,
                         session: SessionDep) -> ApplicationDetail:
    """'I applied myself': counts at once for duplicates, employer limits and follow-ups. Creates no
    evidence; the application is marked owner-attested."""
    if body.job_id is not None:
        job = await session.get(Job, body.job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    else:
        if not (body.title and body.employer):
            raise HTTPException(422,
                                detail="give a job id, or at least a title and an employer")
        job = await corrections.find_existing_job(session, url=body.url, title=body.title, employer=body.employer)
        if job is None:
            job = await corrections.create_job(session, title=body.title, employer=body.employer, origin="owner",
                                               url=body.url)
    try:
        app = await corrections.log_applied_myself(
            session, job, corrections.AppliedMyself(
                applied_on=body.applied_on, channel=body.channel, reference=body.reference, note=body.note,
                files=body.files, campaign_id=body.campaign_id), actor=principal.actor)
    except corrections.CorrectionError as exc:
        raise _corrections_error(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


@router.post("/applications/import/preview", response_model=ImportPreviewOut, name="applications_import_preview")
async def import_preview(session: SessionDep, file: UploadFile) -> ImportPreviewOut:
    """Upload an application-history CSV and see what it would change. Writes nothing."""
    parsed = await _read_csv(file)
    return _preview_out(await history.plan(session, parsed))


@router.post("/applications/import/confirm", response_model=ImportResultOut, name="applications_import_confirm",
             responses={409: {"description": "The file differs from the one previewed"}})
async def import_confirm(principal: PrincipalDep, session: SessionDep, file: UploadFile,
                         content_hash: Annotated[str, Form()]) -> ImportResultOut:
    """Apply the previewed file in one transaction. Importing the same file again changes nothing."""
    parsed = await _read_csv(file)
    if parsed.content_hash != content_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="this file is not the one that was previewed")
    result = await history.commit(session, parsed, actor=principal.actor)
    await publish(session, "application.updated", {"imported": len(result.application_ids)})
    return ImportResultOut(created=result.created, updated=result.updated, unchanged=result.unchanged,
                           skipped=result.skipped, errors=result.errors, application_ids=result.application_ids)


async def _read_csv(file: UploadFile) -> history.ParsedCsv:
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(413, detail="the file is too large")
    try:
        return history.parse_csv(data)
    except history.HistoryFormatError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def _preview_out(plan: history.ImportPlan) -> ImportPreviewOut:
    return ImportPreviewOut(
        content_hash=plan.content_hash, create=plan.count("create"), update=plan.count("update"),
        unchanged=plan.count("unchanged"), skip=plan.count("skip"),
        errors=[ImportErrorOut(line=e.line, id=e.id, message=e.message) for e in plan.errors],
        rows=[ImportRowOut(
            line=r.line, key=r.key, company=r.company, role=r.role, stage=r.stage.value, action=r.action, job=r.job,
            changes=[ImportFieldChange(field=c.field, before=c.before, after=c.after) for c in r.changes],
            messages=r.messages, application_id=r.application_id) for r in plan.rows])


@router.get("/applications/{application_id}", response_model=ApplicationDetail, name="applications_get")
async def get_application(application_id: uuid.UUID, session: SessionDep) -> ApplicationDetail:
    return await _detail(session, application_id)


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value.value if hasattr(value, "value") else value


@router.patch("/applications/{application_id}", response_model=ApplicationDetail, name="applications_patch")
async def patch_application(application_id: uuid.UUID, body: ApplicationPatch, principal: PrincipalDep,
                            session: SessionDep) -> ApplicationDetail:
    app = await _load(session, application_id)
    changes: dict[str, Any] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if name == "pinned" and value is None:
            continue
        if name == "channel":
            value = Channel(value) if value else None
        before = getattr(app, name)
        if before == value:
            continue
        changes[name] = {"before": _plain(before), "after": _plain(value)}
        setattr(app, name, value)
    if changes:
        await stages.add_event(session, app.id, "edit", principal.actor, {"changes": changes})
        await _changed(session, app.id)
    return await _detail(session, app.id)


@router.post("/applications/{application_id}/stage", response_model=ApplicationDetail,
             name="applications_change_stage", responses={409: {"description": "That move is not allowed"}})
async def change_stage(application_id: uuid.UUID, body: StageChangeIn, principal: PrincipalDep,
                       session: SessionDep) -> ApplicationDetail:
    app = await _load(session, application_id)
    try:
        await stages.transition(session, app, Stage(body.stage), actor=principal.actor, via="owner",
                                why=(body.note or "").strip() or f"Owner moved it to {body.stage}")
    except stages.IllegalTransition as exc:
        raise _illegal(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


class AttachedFile(BaseModel):
    file_id: uuid.UUID
    name: str
    sha256: str
    size_bytes: int
    content_type: str | None = None


MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@router.post("/applications/{application_id}/files", response_model=list[AttachedFile],
             status_code=status.HTTP_201_CREATED, name="applications_attach_files")
async def attach_files(application_id: uuid.UUID, files: list[UploadFile], principal: PrincipalDep,
                       session: SessionDep) -> list[AttachedFile]:
    """Keep the files the owner sent (use after 'I applied myself'). Stored under FILES_DIR and shown on the
    timeline; they are the owner's own record, not submission evidence."""
    app = await _load(session, application_id)
    base = get_config().files_dir / "applications" / str(app.id)
    base.mkdir(parents=True, exist_ok=True)
    out: list[AttachedFile] = []
    for upload in files:
        data = await upload.read(MAX_ATTACHMENT_BYTES + 1)
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, detail=f"{upload.filename} is too large")
        file_id = uuid.uuid4()
        name = Path(upload.filename or "file").name[:200] or "file"
        digest = hashlib.sha256(data).hexdigest()
        (base / f"{file_id}.bin").write_bytes(data)
        await stages.add_event(session, app.id, "file_attached", principal.actor, {
            "file_id": str(file_id), "name": name, "sha256": digest, "size_bytes": len(data),
            "content_type": upload.content_type})
        out.append(AttachedFile(file_id=file_id, name=name, sha256=digest, size_bytes=len(data),
                                content_type=upload.content_type))
    await _changed(session, app.id)
    return out


@router.get("/applications/{application_id}/files", response_model=list[AttachedFile],
            name="applications_files")
async def list_files(application_id: uuid.UUID, session: SessionDep) -> list[AttachedFile]:
    await _load(session, application_id)
    rows = await session.scalars(select(ApplicationEvent).where(
        ApplicationEvent.application_id == application_id, ApplicationEvent.kind == "file_attached")
        .order_by(ApplicationEvent.created_at))
    return [AttachedFile(**e.detail) for e in rows]


@router.get("/applications/{application_id}/timeline", response_model=list[TimelineEvent],
            name="applications_timeline")
async def timeline(application_id: uuid.UUID, session: SessionDep) -> list[TimelineEvent]:
    await _load(session, application_id)
    rows = await session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)
                                 .order_by(ApplicationEvent.created_at, ApplicationEvent.id))
    return [TimelineEvent(id=e.id, created_at=e.created_at, kind=e.kind, actor=e.actor, detail=e.detail)
            for e in rows]


@router.post("/applications/{application_id}/tailor", response_model=TailorOut,
             status_code=status.HTTP_202_ACCEPTED, name="applications_tailor")
async def tailor(application_id: uuid.UUID) -> TailorOut:
    not_implemented(2, "tailoring")


@router.put("/applications/{application_id}/spec", response_model=ApplicationDetail, name="applications_put_spec")
async def put_spec(application_id: uuid.UUID, body: SpecUpdate) -> ApplicationDetail:
    """Owner edits; re-runs the checks; invalidates an approved packet if material."""
    not_implemented(2, "tailoring")


@router.post("/applications/{application_id}/check", response_model=list[CheckResult],
             name="applications_check")
async def run_checks(application_id: uuid.UUID) -> list[CheckResult]:
    not_implemented(2, "tailoring")


@router.get("/applications/{application_id}/documents/{kind}", name="applications_document",
            responses={200: {"content": {"application/pdf": {}, "text/html": {}}}})
async def document(application_id: uuid.UUID, kind: Literal["cv", "letter", "answers"],
                   fmt: Literal["pdf", "docx", "html"] = "pdf") -> None:
    not_implemented(2, "documents")


@router.get("/applications/{application_id}/packets", response_model=list[PacketOut], name="applications_packets")
async def packets(application_id: uuid.UUID) -> list[PacketOut]:
    not_implemented(2, "apply")


@router.get("/applications/{application_id}/receipt", response_model=ReceiptOut, name="applications_receipt")
async def receipt(application_id: uuid.UUID) -> ReceiptOut:
    not_implemented(2, "apply")


@router.post("/applications/{application_id}/approve", response_model=ApplicationDetail,
             name="applications_approve", responses={409: {"description": "Packet changed since it was shown"}})
async def approve(application_id: uuid.UUID, body: ApproveIn) -> ApplicationDetail:
    not_implemented(2, "apply")


@router.get("/applications/{application_id}/dispatches", response_model=list[DispatchOut],
            name="applications_dispatches")
async def dispatches(application_id: uuid.UUID) -> list[DispatchOut]:
    not_implemented(2, "apply")


@router.post("/applications/{application_id}/dispatches/{dispatch_id}/cancel", response_model=DispatchOut,
             name="applications_cancel_dispatch")
async def cancel_dispatch(application_id: uuid.UUID, dispatch_id: uuid.UUID) -> DispatchOut:
    not_implemented(2, "apply")


@router.get("/applications/{application_id}/handoff", response_model=ManualHandoffOut,
            name="applications_manual_handoff")
async def manual_handoff(application_id: uuid.UUID) -> ManualHandoffOut:
    not_implemented(2, "apply")


@router.post("/applications/{application_id}/mark-submitted", response_model=ApplicationDetail,
             name="applications_mark_submitted")
async def mark_submitted(application_id: uuid.UUID, body: MarkSubmittedIn) -> ApplicationDetail:
    not_implemented(2, "apply")


@router.get("/applications/{application_id}/releases", response_model=list[ReleaseRecord],
            name="applications_releases")
async def releases(application_id: uuid.UUID) -> list[ReleaseRecord]:
    not_implemented(3, "gateway")


# ----- contacts, mail, interview --------------------------------------------------------------

# ----- contacts (people per job) ----------------------------------------------------------------


async def _contact(session: AsyncSession, item_id: uuid.UUID) -> Contact:
    contact = await session.get(Contact, item_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="contact not found")
    return contact


async def _require_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    if await session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")


@router.get("/contacts", response_model=Page[ContactOut], name="contacts_list")
async def contacts_list(session: SessionDep, job_id: uuid.UUID | None = None, cursor: str | None = None,
                        limit: int = Query(default=50, ge=1, le=200)) -> Page[ContactOut]:
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    stmt = select(Contact).order_by(Contact.created_at, Contact.id)
    if job_id:
        stmt = stmt.where(Contact.job_id == job_id)
    rows = list(await session.scalars(stmt.offset(offset).limit(limit + 1)))
    return Page[ContactOut](items=[ContactOut.model_validate(c) for c in rows[:limit]],
                            next_cursor=str(offset + limit) if len(rows) > limit else None)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED, name="contacts_create")
async def contacts_create(body: ContactIn, principal: PrincipalDep, session: SessionDep) -> ContactOut:
    await _require_job(session, body.job_id)
    contact = Contact(**body.model_dump(), origin="owner")
    session.add(contact)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="contact.created", subject_type="contact",
                       subject_id=contact.id, detail={"job_id": str(body.job_id)})
    await session.refresh(contact)
    return ContactOut.model_validate(contact)


@router.put("/contacts/{item_id}", response_model=ContactOut, name="contacts_update")
async def contacts_update(item_id: uuid.UUID, body: ContactIn, principal: PrincipalDep,
                          session: SessionDep) -> ContactOut:
    contact = await _contact(session, item_id)
    await _require_job(session, body.job_id)
    for name, value in body.model_dump().items():
        setattr(contact, name, value)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="contact.updated", subject_type="contact",
                       subject_id=contact.id, detail={"job_id": str(body.job_id)})
    await session.refresh(contact)
    return ContactOut.model_validate(contact)


@router.delete("/contacts/{item_id}", status_code=status.HTTP_204_NO_CONTENT, name="contacts_delete",
               response_class=Response)
async def contacts_delete(item_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> Response:
    contact = await _contact(session, item_id)
    await audit.record(session, actor=principal.actor, action="contact.deleted", subject_type="contact",
                       subject_id=contact.id, detail={"job_id": str(contact.job_id)})
    await session.delete(contact)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mail-threads", response_model=Page[MailThreadOut], name="mail_threads_list")
async def mail_threads(session: SessionDep, application_id: uuid.UUID | None = None,
                       needs_review: bool | None = None, cursor: str | None = None,
                       limit: int = Query(default=50, ge=1, le=200)) -> Page[MailThreadOut]:
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    stmt = select(MailThread).order_by(MailThread.last_message_at.desc().nulls_last(), MailThread.id)
    if application_id is not None:
        stmt = stmt.where(MailThread.application_id == application_id)
    if needs_review is not None:
        stmt = stmt.where(MailThread.needs_review.is_(needs_review))
    rows = list(await session.scalars(stmt.offset(offset).limit(limit + 1)))
    return Page[MailThreadOut](items=[MailThreadOut.model_validate(t) for t in rows[:limit]],
                               next_cursor=str(offset + limit) if len(rows) > limit else None)


@router.put("/mail-threads/{thread_id}", response_model=MailThreadOut, name="mail_threads_link")
async def link_mail_thread(thread_id: uuid.UUID, body: MailThreadLink, session: SessionDep,
                           principal: PrincipalDep) -> MailThreadOut:
    """The owner settles a review: link the thread to an application (or unlink it) and/or fix its kind.
    Linking applies the same proposal rules as an automatic match, but never silently changes a stage."""
    thread = await session.get(MailThread, thread_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="mail thread not found")
    app = None
    if body.application_id is not None:
        app = await session.get(Application, body.application_id)
        if app is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    thread.application_id = body.application_id
    if body.classification is not None:
        thread.classification = MailClassification(body.classification)
    thread.match_confidence = 1.0 if app is not None else None
    thread.needs_review = False
    await audit.record(session, actor=principal.actor, action="mail_thread.linked", subject_type="mail_thread",
                       subject_id=thread.id, detail={"application_id": str(body.application_id) if app else None,
                                                     "classification": thread.classification.value})
    if app is not None and thread.provider_message_ids:
        res = SyncResult()
        values = await settings_service.values(session)
        await act_on_thread(session, thread, app, thread.classification.value, thread.provider_message_ids[-1],
                            list(values["mail.auto_apply_classes"]), res)
    await session.flush()
    await session.refresh(thread)
    return MailThreadOut.model_validate(thread)


@router.get("/jobs/{job_id}/interview-pack", response_model=InterviewPackOut, name="interview_pack_get")
async def interview_pack(job_id: uuid.UUID) -> InterviewPackOut:
    not_implemented(3, "interview")


@router.post("/jobs/{job_id}/interview-pack", response_model=InterviewPackOut,
             status_code=status.HTTP_202_ACCEPTED, name="interview_pack_generate")
async def generate_interview_pack(job_id: uuid.UUID) -> InterviewPackOut:
    not_implemented(3, "interview")


@router.post("/jobs/{job_id}/interview-pack/rounds", response_model=InterviewRoundOut,
             status_code=status.HTTP_201_CREATED, name="interview_rounds_create")
async def create_round(job_id: uuid.UUID, body: InterviewRoundIn) -> InterviewRoundOut:
    not_implemented(3, "interview")


@router.put("/interview-rounds/{round_id}", response_model=InterviewRoundOut, name="interview_rounds_update")
async def update_round(round_id: uuid.UUID, body: InterviewRoundIn) -> InterviewRoundOut:
    not_implemented(3, "interview")


# ----- global pause (top bar) -----------------------------------------------------------------


@router.get("/autopilot", response_model=AutopilotState, name="autopilot_get")
async def autopilot_state(session: SessionDep) -> AutopilotState:
    """Global Running / Paused state (top bar)."""
    return await autopilot.read_state(session)


@router.put("/autopilot", response_model=AutopilotState, name="autopilot_set")
async def autopilot_set(body: AutopilotWrite, principal: PrincipalDep, session: SessionDep) -> AutopilotState:
    """Pause stops every new outward action at once and cancels queued sends; the response
    lists what was cancelled, paused, and already out. Resume clears the pause. Audited."""
    return await autopilot.set_paused(session, body.paused, actor=principal.actor)


@router.post("/autopilot/resume-after-restore", response_model=Ok, name="autopilot_resume_after_restore")
async def resume_after_restore() -> Ok:
    """A restored instance starts paused and reconciles its outbox first (18.3)."""
    not_implemented(2, "apply")
