"""Applications: board, Studio (spec, checks, packet, approval receipt), dispatch, manual handoff,
timeline, contacts, mail threads, interview pack, global pause. Waves 1-3."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Ok, Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import approval, autopilot, stages
from app.apply import dispatch as apply_dispatch
from app.apply import errors as apply_errors
from app.apply import handoff as apply_handoff
from app.apply import outcomes as apply_outcomes
from app.apply import packets as apply_packets
from app.apply import receipt as apply_receipt
from app.apply import reconcile as apply_reconcile
from app.apply import restore as apply_restore
from app.apply.autopilot import AutopilotState, AutopilotWrite
from app.connect.mail_sync import SyncResult, act_on_thread
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.events import publish
from app.core.settings import service as settings_service
from app.docs.api import StoreDep as DocStoreDep
from app.docs.api import router as documents_router
from app.kit.importers import history
from app.llm.deps import llm_service
from app.llm.service import LLMService
from app.models.applications import (
    Application,
    ApplicationEvent,
    ApplicationPacket,
    Channel,
    Contact,
    DispatchAttempt,
    MailClassification,
    MailThread,
    PendingAction,
    PendingStatus,
    Stage,
    TailoringRequest,
)
from app.models.search import Assessment, Job
from app.pipeline import bulk, corrections
from app.pipeline.checks import findings as checks_findings
from app.pipeline.tailoring import service as tailoring_service
from app.pipeline.tailoring import studio
from app.schemas.json_types import (
    ApplicationSpec,
    CheckResult,
    DraftAnswer,
    Evidence,
    GateResult,
    PacketContents,
    PacketEmail,
    PacketFile,
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


class SpecVersionSummary(BaseModel):
    version: int
    origin: Literal["tailor", "owner"]
    content_hash: str
    created_at: datetime
    created_by: str
    status: Literal["pass", "warn", "block"]


class SpecStateOut(BaseModel):
    """The Studio's view of the documents: the spec, its checks and whether they still apply."""

    application_id: uuid.UUID
    version: int | None = Field(description="Spec version shown; null before the first draft")
    origin: Literal["tailor", "owner"] | None = None
    content_hash: str | None = None
    spec: ApplicationSpec
    check_results: list[CheckResult]
    checked: bool = Field(description="The stored checks ran on exactly this content and these Kit facts")
    status: Literal["pass", "warn", "block"] | None = Field(
        default=None, description="Worst stored result (an unwaived block is block)")
    stale_reasons: list[str] = Field(default_factory=list)
    answers: list[DraftAnswer] = Field(default_factory=list,
                                       description="Screening questions and what the answer bank says")
    tailoring: Literal["queued", "running", "paused", "done", "failed"] | None = None
    tailoring_error: str | None = None
    versions: list[SpecVersionSummary] = Field(default_factory=list)


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


class PacketAnswerIn(BaseModel):
    """An answer from the bank (``answer_id``: value and materiality are read from the bank) or typed for
    this packet only (``value``; counted as material)."""

    question: str = Field(min_length=1)
    answer_id: uuid.UUID | None = None
    value: str | None = None


class PacketBuildIn(BaseModel):
    """What would be sent. The server sets the destination domain, ``verified`` and ``trusted``, the
    requisition (from the job unless given) and the job version."""

    channel: ChannelT
    destination_url: str | None = Field(default=None, description="Apply URL (browser, manual)")
    sending_identity: str = Field(min_length=1, description="Mailbox or name the application is sent as")
    answers: list[PacketAnswerIn] = Field(default_factory=list)
    email: PacketEmail | None = None
    files: list[PacketFile] = Field(default_factory=list)
    link_permissions: list[str] = Field(default_factory=list)
    requisition: str | None = None


class ApprovalStatusOut(BaseModel):
    approved: bool
    status: Literal["granted", "wait_for_owner", "denied"]
    reason: str
    pending_action_id: uuid.UUID | None = None
    code: str | None = Field(default=None, description="Why not approved: a machine code (CONTRACTS, wave 2 "
                                                       "send-flow); None when approved")


class PacketBuildOut(BaseModel):
    packet: PacketOut
    created: bool = Field(description="False when the contents were identical to the current packet")
    changes: list[PacketChange] = Field(default_factory=list,
                                        description="What changed from the previous version")
    approval: ApprovalStatusOut | None = Field(
        default=None, description="What the automation policy did with the new packet (None: nothing to do)")


class PacketPrepareIn(BaseModel):
    """Prepare the packet the way the pipeline does. ``auto``: email when the role's application address is
    usable (confirmed, or a trusted domain) and a mailbox is connected, else manual. ``manual``: the owner
    applies. Template keys override the track and documents settings (``GET /api/document-templates``)."""

    channel: Literal["auto", "manual"] = "auto"
    cv_template: str | None = Field(default=None, max_length=60)
    letter_template: str | None = Field(default=None, max_length=60)


class PacketPrepareOut(BaseModel):
    channel: Literal["email", "manual"]
    packet: PacketOut
    created: bool = Field(description="False when the contents were identical to the current packet")
    changes: list[PacketChange] = Field(default_factory=list)
    approval: ApprovalStatusOut | None = Field(
        default=None, description="What the automation policy did with the new packet (None: nothing to do)")


class RejectIn(BaseModel):
    reason: str | None = None


class RequestChangesIn(BaseModel):
    note: str = Field(min_length=1)


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
    started_at: datetime | None = Field(default=None, description="Handed to the channel (in flight from here)")
    evidence: Evidence | None = None
    uncertain: bool = Field(default=False, description="Handed over with no final outcome: reconcile, never resend")
    reconcile_attempts: int = 0
    last_reconciled_at: datetime | None = None
    deferred_reason: Literal["quiet_hours"] | None = Field(
        default=None, description="Queued but postponed by the send-time check (quiet hours); null otherwise")
    deferred_until: datetime | None = Field(default=None, description="When a deferred send becomes due again")


class DispatchCreateIn(BaseModel):
    """Queue the current approved packet now (permit, then the attempt; email waits the send delay)."""


class DispatchCreateOut(BaseModel):
    status: Literal["queued", "wait_for_owner", "denied"]
    reason: str
    dispatch: DispatchOut | None = None
    gates: list[GateResult] = Field(default_factory=list)
    pending_action_id: uuid.UUID | None = None
    code: str | None = Field(default=None, description="Why not queued: a machine code (CONTRACTS, wave 2 send-flow)")


class ReconcileIn(BaseModel):
    decision: Literal["check", "sent", "not_sent"] = Field(
        description="check: ask the channel now; sent: it went out (reference kept as evidence); not_sent: it never "
                    "left (the role goes back to ready; nothing is resent automatically)")
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class ReconcileOut(BaseModel):
    result: Literal["sent", "not_sent", "waiting"]
    dispatch: DispatchOut


class RestoreStateOut(BaseModel):
    active: bool
    entered_at: datetime | None = None
    backup_taken_at: str | None = None
    outstanding: list[DispatchOut] = Field(default_factory=list,
                                           description="Sends from before the backup still to reconcile")
    held_application_ids: list[uuid.UUID] = Field(default_factory=list,
                                                  description="Approvals withdrawn at restore, to approve again")


class ManualHandoffOut(BaseModel):
    posting_url: str | None
    files: list[str] = Field(description="Download links for the final files (behind the owner's session), or "
                                         "the share links the packet records")
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
    try:  # the one function behind this endpoint and the bulk "assign to campaign" / "queue tailoring"
        app = await bulk.create_application(session, job, body.campaign_id, actor=principal.actor)
    except bulk.Refuse as exc:
        if exc.code == "merged":
            raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
        existing = await stages.blocking_application(session, job.id)
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "duplicate", "reason": exc.reason,
            "application_id": str(existing.id) if existing else None}) from exc
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


TailorEnqueue = Callable[[TailoringRequest], Awaitable[None]]


async def get_tailor_enqueue() -> TailorEnqueue:
    """Defers a tailoring request to the worker (tests replace this dependency)."""

    async def enqueue(req: TailoringRequest) -> None:
        from app.pipeline.tailoring.tasks import enqueue as defer
        from app.worker.queue import queue_app

        async with queue_app.open_async():
            await defer(req)

    return enqueue


def _tailoring_error(exc: tailoring_service.TailoringError) -> HTTPException:
    return HTTPException(exc.status_code, detail=str(exc))


@router.post("/applications/{application_id}/tailor", response_model=TailorOut,
             status_code=status.HTTP_202_ACCEPTED, name="applications_tailor",
             responses={409: {"description": "The application can no longer be tailored"}})
async def tailor(application_id: uuid.UUID, principal: PrincipalDep, session: SessionDep,
                 enqueue: Annotated[TailorEnqueue, Depends(get_tailor_enqueue)]) -> TailorOut:
    """Queue a tailored draft. Idempotent per spec version and Kit facts: asking again returns the same
    request (``queued`` is false once it is done)."""
    app = await session.get(Application, application_id, with_for_update=True)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    try:
        req, needs_queue = await tailoring_service.request(session, app, actor=principal.actor)
    except tailoring_service.TailoringError as exc:
        raise _tailoring_error(exc) from exc
    await _changed(session, app.id)
    await session.commit()
    if needs_queue:
        await enqueue(req)
    return TailorOut(run_id=req.tailoring_run_id, queued=req.status in tailoring_service.OPEN)


@router.get("/applications/{application_id}/spec", response_model=SpecStateOut, name="applications_get_spec")
async def get_spec(application_id: uuid.UUID, session: SessionDep,
                   version: Annotated[int | None, Query(ge=1)] = None) -> SpecStateOut:
    app = await _load(session, application_id)
    try:
        got = await studio.spec_state(session, app, version)
    except tailoring_service.TailoringError as exc:
        raise _tailoring_error(exc) from exc
    v, st, req = got.version, got.state, got.request
    return SpecStateOut(
        application_id=app.id, version=v.version if v else None, origin=v.origin if v else None,  # type: ignore[arg-type]
        content_hash=v.content_hash if v else None, spec=v.spec if v else app.spec,
        check_results=v.check_results if v else [], checked=bool(st and st.checked),
        status=st.status if st and v and v.checked_hash else None, stale_reasons=st.stale_reasons if st else [],
        answers=v.answers if v else [], tailoring=req.status.value if req else None,
        tailoring_error=req.error if req else None,
        versions=[SpecVersionSummary(version=r.version, origin=r.origin, content_hash=r.content_hash,  # type: ignore[arg-type]
                                     created_at=r.created_at, created_by=r.created_by,
                                     status=checks_findings.worst(r.check_results)) for r in got.versions])


@router.put("/applications/{application_id}/spec", response_model=ApplicationDetail, name="applications_put_spec",
            responses={409: {"description": "The documents can no longer be edited"}})
async def put_spec(application_id: uuid.UUID, body: SpecUpdate, principal: PrincipalDep,
                   session: SessionDep) -> ApplicationDetail:
    """Owner edits; re-runs the checks; invalidates an approved packet if material."""
    app = await session.get(Application, application_id, with_for_update=True)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    try:
        await studio.owner_edit(session, app, body.spec, actor=principal.actor)
    except tailoring_service.TailoringError as exc:
        raise _tailoring_error(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


@router.post("/applications/{application_id}/check", response_model=list[CheckResult],
             name="applications_check", responses={409: {"description": "There is no draft to check"}})
async def run_checks(application_id: uuid.UUID, principal: PrincipalDep, session: SessionDep,
                     service: Annotated[LLMService, Depends(llm_service)]) -> list[CheckResult]:
    """Re-run every check on the latest spec version, including the model claim check when enabled."""
    app = await _load(session, application_id)
    try:
        results = await studio.recheck(session, app, service, actor=principal.actor)
    except tailoring_service.TailoringError as exc:
        raise _tailoring_error(exc) from exc
    await _changed(session, app.id)
    return results


# Documents (list, render, download): app/docs/api.py
router.include_router(documents_router)


def _packet_out(p: ApplicationPacket) -> PacketOut:
    return PacketOut(id=p.id, created_at=p.created_at, updated_at=p.updated_at, application_id=p.application_id,
                     version=p.version, content_hash=p.content_hash, contents=p.contents, approved_at=p.approved_at,
                     approved_by=p.approved_by, invalidated_at=p.invalidated_at,
                     invalidated_reason=p.invalidated_reason)


def _approval_error(exc: approval.ApprovalError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "reason": exc.message, **exc.detail})


def _coded(exc: Any) -> HTTPException:
    """``{code, reason}`` for an apply-layer refusal (``app.apply.errors``)."""
    return HTTPException(exc.status, detail=apply_errors.detail(exc.code, exc.message))


def _approval_status(outcome: approval.ApprovalOutcome) -> ApprovalStatusOut:
    code = None if outcome.approved else apply_errors.for_permit_reason(
        outcome.reason, (str(g.get("gate")) for g in outcome.gates))
    return ApprovalStatusOut(approved=outcome.approved, status=outcome.status, reason=outcome.reason,  # type: ignore[arg-type]
                             pending_action_id=outcome.pending_action_id, code=code)


@router.get("/applications/{application_id}/packets", response_model=list[PacketOut], name="applications_packets")
async def packets(application_id: uuid.UUID, session: SessionDep) -> list[PacketOut]:
    """Every packet version, newest first (invalidated ones say why)."""
    await _load(session, application_id)
    return [_packet_out(p) for p in await apply_packets.history(session, application_id)]


@router.get("/applications/{application_id}/packet", response_model=PacketOut, name="applications_packet_get",
            responses={404: {"description": "No current packet"}})
async def current_packet(application_id: uuid.UUID, session: SessionDep) -> PacketOut:
    """The current packet: exactly what would be sent."""
    await _load(session, application_id)
    packet = await apply_packets.current(session, application_id)
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no packet has been built")
    return _packet_out(packet)


@router.post("/applications/{application_id}/packet", response_model=PacketBuildOut,
             name="applications_packet_build", responses={409: {"description": "The application has gone out"}})
async def build_packet(application_id: uuid.UUID, body: PacketBuildIn, principal: PrincipalDep,
                       session: SessionDep) -> PacketBuildOut:
    """Snapshot what would be sent. Identical contents return the current packet; any change makes a new
    version and invalidates the old one and its approval. Then the automation policy runs: automatic
    approval when every gate passes, an approval request when the mode lets the system apply."""
    app = await _load(session, application_id)
    if app.stage not in approval.APPROVABLE_STAGES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=apply_errors.detail(
            "illegal_stage", f"an application in {app.stage.value} cannot be repacked"))
    draft = apply_packets.PacketDraft(
        channel=body.channel, destination_url=body.destination_url or "", sending_identity=body.sending_identity,
        answers=[apply_packets.DraftAnswer(question=a.question, value=a.value, answer_id=a.answer_id)
                 for a in body.answers],
        email=body.email, files=list(body.files), link_permissions=list(body.link_permissions),
        requisition=body.requisition)
    try:
        built = await apply_packets.build(session, app, draft, actor=principal.actor)
    except apply_packets.PacketError as exc:
        raise _coded(exc) from exc
    outcome = await approval.after_packet_built(session, app, built.packet) if built.created else None
    await _changed(session, app.id)
    await session.refresh(built.packet)
    return PacketBuildOut(
        packet=_packet_out(built.packet), created=built.created,
        changes=[PacketChange(**c) for c in built.changes] if built.previous else [],
        approval=None if outcome is None else _approval_status(outcome))


@router.post("/applications/{application_id}/packet/prepare", response_model=PacketPrepareOut,
             name="applications_packet_prepare",
             responses={409: {"description": "Nothing built: {code, reason} (spec not checked, answers waiting, "
                                             "nowhere to apply, or the application has gone out)"}})
async def prepare_packet(application_id: uuid.UUID, body: PacketPrepareIn, principal: PrincipalDep,
                         session: SessionDep, store: DocStoreDep) -> PacketPrepareOut:
    """Prepare the packet exactly as the pipeline does (``app.apply.prepare.prepare_packet``): render the
    checked spec's CV and letter, pick the channel (email to a usable application address when a mailbox is
    connected, else manual; ``channel: manual`` always hands it to the owner), build, then let the automation
    policy act (an approval request, or automatic approval)."""
    from app.apply import prepare as apply_prepare

    app = await _load(session, application_id)
    if app.stage not in approval.APPROVABLE_STAGES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=apply_errors.detail(
            "illegal_stage", f"an application in {app.stage.value} cannot be repacked"))
    templates = {k: v for k, v in (("cv", body.cv_template), ("letter", body.letter_template)) if v}
    prepared = await apply_prepare.prepare_packet(session, store, app, actor=principal.actor, channel=body.channel,
                                                  templates=templates)
    if not prepared.built or prepared.packet_id is None:
        await session.commit()  # keep the audited reason
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=apply_errors.detail(prepared.code or "refused", prepared.reason))
    await _changed(session, app.id)
    packet = await session.get(ApplicationPacket, prepared.packet_id, populate_existing=True)
    assert packet is not None
    return PacketPrepareOut(
        channel=prepared.channel, packet=_packet_out(packet), created=prepared.created,  # type: ignore[arg-type]
        changes=[PacketChange(**c) for c in prepared.changes],
        approval=None if prepared.approval is None else _approval_status(prepared.approval))


@router.get("/applications/{application_id}/receipt", response_model=ReceiptOut, name="applications_receipt")
async def receipt(application_id: uuid.UUID, session: SessionDep) -> ReceiptOut:
    """The approval receipt for the current packet, with the gates an approval would check."""
    app = await _load(session, application_id)
    built = await apply_receipt.build(session, app)
    if built is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no packet has been built")
    return ReceiptOut(
        application_id=app.id, packet=_packet_out(built.packet), employer=built.employer,
        destination=built.destination, role=built.role, pay_answers=built.pay_answers,
        work_rights_answers=built.work_rights_answers, attachments=built.attachments,
        unusual_disclosures=built.unusual_disclosures,
        changes_since_last_look=[PacketChange(**c) for c in built.changes_since_last_look],
        action_label=built.action_label, gates=[GateResult(**g) for g in built.gates])


@router.post("/applications/{application_id}/approve", response_model=ApplicationDetail,
             name="applications_approve", responses={409: {"description": "Packet changed since it was shown"}})
async def approve(application_id: uuid.UUID, body: ApproveIn, principal: PrincipalDep,
                  session: SessionDep) -> ApplicationDetail:
    """Approve exactly this packet (version and hash) for this channel. Refused (409, with the gates) when
    the packet changed, the role is excluded or held in its employer group, a document check blocks, or
    the mode does not let the system apply."""
    app = await _load(session, application_id)
    try:
        await approval.approve(session, app, packet_version=body.packet_version, packet_hash=body.packet_hash,
                               channel=body.channel, actor=principal.actor, waiver_ids=body.waivers,
                               waiver_reason=body.waiver_reason)
    except approval.ApprovalError as exc:
        raise _approval_error(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


@router.post("/applications/{application_id}/reject", response_model=ApplicationDetail,
             name="applications_reject", responses={409: {"description": "Cannot be rejected now"}})
async def reject(application_id: uuid.UUID, body: RejectIn, principal: PrincipalDep,
                 session: SessionDep) -> ApplicationDetail:
    """Say no at approval: the role is skipped and the next role in its employer group is promoted."""
    app = await _load(session, application_id)
    try:
        await approval.reject(session, app, actor=principal.actor, reason=body.reason)
    except approval.ApprovalError as exc:
        raise _approval_error(exc) from exc
    except stages.IllegalTransition as exc:
        raise _illegal(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


@router.post("/applications/{application_id}/request-changes", response_model=ApplicationDetail,
             name="applications_request_changes", responses={409: {"description": "Cannot be changed now"}})
async def request_changes(application_id: uuid.UUID, body: RequestChangesIn, principal: PrincipalDep,
                          session: SessionDep) -> ApplicationDetail:
    """Retire the packet and send the application back to tailoring with a note."""
    app = await _load(session, application_id)
    try:
        await approval.request_changes(session, app, actor=principal.actor, note=body.note)
    except approval.ApprovalError as exc:
        raise _approval_error(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


async def _deferrals(session: AsyncSession, attempts: list[DispatchAttempt]) -> dict[str, str]:
    """Attempts still waiting after a send-time deferral, and why (from their ``dispatch_deferred`` events)."""
    waiting = {str(a.id): a for a in attempts if a.status.value == "reserved" and a.started_at is None}
    if not waiting:
        return {}
    events = await session.scalars(select(ApplicationEvent).where(
        ApplicationEvent.application_id.in_({a.application_id for a in waiting.values()}),
        ApplicationEvent.kind == "dispatch_deferred"))
    return {str(e.detail.get("attempt_id")): str(e.detail.get("code") or "quiet_hours") for e in events
            if str(e.detail.get("attempt_id")) in waiting}


def _dispatch_out(a: DispatchAttempt, deferred: dict[str, str] | None = None) -> DispatchOut:
    reason = (deferred or {}).get(str(a.id))
    return DispatchOut(deferred_reason=reason, deferred_until=a.send_after if reason else None,  # type: ignore[arg-type]
                       id=a.id, created_at=a.created_at, updated_at=a.updated_at, application_id=a.application_id,
                       packet_hash=a.packet_hash, channel=a.channel.value, status=a.status.value,
                       send_after=a.send_after, provider_message_id=a.provider_message_id, outcome_at=a.outcome_at,
                       gate_results=a.gate_results, error=a.error, started_at=a.started_at, evidence=a.evidence,
                       uncertain=apply_outcomes.is_uncertain(a), reconcile_attempts=a.reconcile_attempts,
                       last_reconciled_at=a.last_reconciled_at)


async def _attempt(session: AsyncSession, application_id: uuid.UUID, dispatch_id: uuid.UUID) -> DispatchAttempt:
    attempt = await session.get(DispatchAttempt, dispatch_id, with_for_update=True)
    if attempt is None or attempt.application_id != application_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="dispatch not found")
    return attempt


@router.get("/applications/{application_id}/dispatches", response_model=list[DispatchOut],
            name="applications_dispatches")
async def dispatches(application_id: uuid.UUID, session: SessionDep) -> list[DispatchOut]:
    """Every dispatch attempt, newest first: what was reserved, handed over, sent (with evidence), failed,
    cancelled or is uncertain."""
    await _load(session, application_id)
    rows = await session.scalars(select(DispatchAttempt).where(DispatchAttempt.application_id == application_id)
                                 .order_by(DispatchAttempt.created_at.desc()))
    attempts = list(rows)
    deferred = await _deferrals(session, attempts)
    return [_dispatch_out(a, deferred) for a in attempts]


@router.post("/applications/{application_id}/dispatches", response_model=DispatchCreateOut,
             name="applications_dispatch_create")
async def create_dispatch(application_id: uuid.UUID, body: DispatchCreateIn, principal: PrincipalDep,
                          session: SessionDep) -> DispatchCreateOut:
    """Send the current approved packet: a submit permit (every gate), then the attempt, in one transaction.
    Email waits ``automation.email_send_delay_minutes`` (cancellable) and is sent by the worker; the manual
    channel hands the kit to the owner at once."""
    await _load(session, application_id)
    try:
        result = await apply_dispatch.queue(session, application_id, actor=principal.actor)
    except apply_dispatch.DispatchError as exc:
        raise _coded(exc) from exc
    attempt = result.attempt
    if attempt is not None and attempt.channel == Channel.manual:
        attempt_id = attempt.id
        await session.commit()
        await apply_dispatch.run(session, attempt_id)
        attempt = await session.get(DispatchAttempt, attempt_id, populate_existing=True)
    elif attempt is not None:
        await session.refresh(attempt)
    await _changed(session, application_id)
    return DispatchCreateOut(status=result.status, reason=result.reason,  # type: ignore[arg-type]
                             dispatch=_dispatch_out(attempt) if attempt else None,
                             gates=[GateResult(**g) for g in result.gates], pending_action_id=result.pending_action_id,
                             code=result.code)


@router.post("/applications/{application_id}/dispatches/{dispatch_id}/cancel", response_model=DispatchOut,
             name="applications_cancel_dispatch", responses={409: {"description": "Already handed over"}})
async def cancel_dispatch(application_id: uuid.UUID, dispatch_id: uuid.UUID, principal: PrincipalDep,
                          session: SessionDep) -> DispatchOut:
    """Cancel a queued send before it is handed to its channel (during the send delay)."""
    attempt = await _attempt(session, application_id, dispatch_id)
    app = await apply_outcomes.lock_application(session, application_id)
    try:
        await apply_outcomes.cancel(session, attempt, app, "cancelled by the owner", actor=principal.actor,
                                    now=utcnow())
    except apply_outcomes.OutcomeError as exc:
        raise _coded(exc) from exc
    await _changed(session, application_id)
    await session.refresh(attempt)
    return _dispatch_out(attempt)


@router.post("/applications/{application_id}/dispatches/{dispatch_id}/reconcile", response_model=ReconcileOut,
             name="applications_reconcile_dispatch", responses={409: {"description": "Not uncertain"}})
async def reconcile_dispatch(application_id: uuid.UUID, dispatch_id: uuid.UUID, body: ReconcileIn,
                             principal: PrincipalDep, session: SessionDep) -> ReconcileOut:
    """Settle an uncertain send: ask its channel now, or say it went out (with the reference) or did not.
    An uncertain send is never resent automatically."""
    attempt = await _attempt(session, application_id, dispatch_id)
    try:
        result = await apply_reconcile.decide(session, attempt, body.decision, actor=principal.actor,
                                              reference=body.reference, note=body.note)
    except apply_outcomes.OutcomeError as exc:
        raise _coded(exc) from exc
    await _changed(session, application_id)
    await session.refresh(attempt)
    return ReconcileOut(result=result, dispatch=_dispatch_out(attempt))  # type: ignore[arg-type]


@router.get("/applications/{application_id}/handoff", response_model=ManualHandoffOut,
            name="applications_manual_handoff")
async def manual_handoff(application_id: uuid.UUID, session: SessionDep) -> ManualHandoffOut:
    """The manual handoff kit for the current packet: posting link, files, answers sheet, remaining steps."""
    app = await _load(session, application_id)
    try:
        built = await apply_handoff.kit(session, app)
    except apply_handoff.HandoffError as exc:
        raise _coded(exc) from exc
    return ManualHandoffOut(posting_url=built.posting_url, files=built.files, answers=built.answers,
                            remaining_steps=built.remaining_steps)


@router.post("/applications/{application_id}/mark-submitted", response_model=ApplicationDetail,
             name="applications_mark_submitted", responses={409: {"description": "Nothing approved to submit"}})
async def mark_submitted(application_id: uuid.UUID, body: MarkSubmittedIn, principal: PrincipalDep,
                         session: SessionDep) -> ApplicationDetail:
    """The owner submitted it: closes the open send (manual hand-off, or an uncertain one) as sent with the
    owner's evidence, or sends the approved manual packet through permit and attempt first. Duplicate
    protection then holds exactly as after an automatic send."""
    app = await _load(session, application_id)
    try:
        await apply_handoff.mark_submitted(session, app, reference=body.reference, note=body.note,
                                           actor=principal.actor)
    except apply_handoff.HandoffError as exc:
        raise _coded(exc) from exc
    except apply_outcomes.OutcomeError as exc:
        raise _coded(exc) from exc
    await _changed(session, app.id)
    return await _detail(session, app.id)


@router.get("/applications/{application_id}/releases", response_model=list[ReleaseRecord],
            name="applications_releases")
async def releases(application_id: uuid.UUID, session: SessionDep) -> list[ReleaseRecord]:
    """What each runner task was given (packet, answers, files) and what it reports having entered (18.1)."""
    from app.models.applications import AgentTask

    await _load(session, application_id)
    tasks = (await session.scalars(select(AgentTask).where(AgentTask.application_id == application_id)
                                   .order_by(AgentTask.created_at))).all()
    return [ReleaseRecord(agent_task_id=t.id, released={"given": (t.released or {}).get("given") or []},
                          entered=(t.released or {}).get("entered") or {}) for t in tasks if t.released]


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


# ----- global pause (top bar) -----------------------------------------------------------------


@router.get("/autopilot", response_model=AutopilotState, name="autopilot_get")
async def autopilot_state(session: SessionDep) -> AutopilotState:
    """Global Running / Paused state (top bar)."""
    return await autopilot.read_state(session)


@router.put("/autopilot", response_model=AutopilotState, name="autopilot_set")
async def autopilot_set(body: AutopilotWrite, principal: PrincipalDep, session: SessionDep) -> AutopilotState:
    """Pause stops every new outward action at once and cancels queued sends; the response
    lists what was cancelled, paused, and already out. Resume clears the pause (409 while paused for a
    restore: use resume-after-restore). Audited."""
    try:
        return await autopilot.set_paused(session, body.paused, actor=principal.actor, reason=body.reason)
    except autopilot.ResumeRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "restore_paused", "reason": str(exc)}) from exc


@router.get("/autopilot/restore", response_model=RestoreStateOut, name="autopilot_restore_state")
async def restore_state(session: SessionDep) -> RestoreStateOut:
    """Paused for a restore from backup: what is still to reconcile before sending can resume (18.3)."""
    st = await apply_restore.state(session)
    return RestoreStateOut(active=st.active, entered_at=st.entered_at, backup_taken_at=st.backup_taken_at,
                           outstanding=[_dispatch_out(a) for a in st.outstanding],
                           held_application_ids=st.held_application_ids)


@router.post("/autopilot/resume-after-restore", response_model=Ok, name="autopilot_resume_after_restore",
             responses={409: {"description": "Sends from before the backup are not reconciled yet"}})
async def resume_after_restore(principal: PrincipalDep, session: SessionDep) -> Ok:
    """A restored instance starts paused and reconciles its outbox first (18.3). Refused (409, with the
    outstanding dispatch ids) until every send in flight at backup time is settled."""
    try:
        await apply_restore.resume(session, actor=principal.actor)
    except apply_restore.RestoreError as exc:
        raise HTTPException(exc.status, detail={"code": "restore_unreconciled", "reason": exc.message,
                                                "outstanding": [str(i) for i in exc.outstanding]}) from exc
    return Ok()
