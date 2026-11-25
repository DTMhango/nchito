"""Applications: board, Studio (spec, checks, packet, approval receipt), dispatch, manual handoff,
timeline, contacts, mail threads, interview pack, global pause. Waves 1-3."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Ok, Page, Timestamps, not_implemented
from app.api.crud import add_crud
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import autopilot
from app.apply.autopilot import AutopilotState, AutopilotWrite
from app.schemas.json_types import (
    ApplicationSpec,
    CheckResult,
    Evidence,
    GateResult,
    PacketContents,
    SubmittedSnapshot,
)

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


class ApplicationDetail(ApplicationSummary):
    spec: ApplicationSpec
    check_results: list[CheckResult]
    approved_packet_id: uuid.UUID | None
    submitted_snapshot: SubmittedSnapshot | None
    confirmation_evidence: list[Evidence]
    applied_outside: bool


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID
    campaign_id: uuid.UUID | None = None


class ApplicationPatch(BaseModel):
    next_step: str | None = None
    next_due: date | None = None
    pinned: bool | None = None
    snoozed_until: datetime | None = None
    channel: ChannelT | None = None


class StageChangeIn(BaseModel):
    """Dragging to `submitted` never creates evidence: use 'I applied myself' instead."""

    stage: StageT
    note: str | None = None


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


class MailThreadOut(Timestamps):
    application_id: uuid.UUID | None
    subject: str | None
    classification: Literal["confirmation", "rejection", "interview", "other"]
    match_confidence: float | None
    needs_review: bool


class MailThreadLink(BaseModel):
    application_id: uuid.UUID | None
    classification: Literal["confirmation", "rejection", "interview", "other"] | None = None


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


# ----- applications -----------------------------------------------------------------------


@router.get("/applications", response_model=Page[ApplicationSummary], name="applications_list")
async def list_applications(stage: StageT | None = None, campaign_id: uuid.UUID | None = None,
                            q: str | None = None, cursor: str | None = None,
                            limit: int = 100) -> Page[ApplicationSummary]:
    not_implemented(1, "applications")


@router.post("/applications", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED,
             name="applications_create")
async def create_application(body: ApplicationCreate) -> ApplicationDetail:
    not_implemented(1, "applications")


@router.get("/applications/{application_id}", response_model=ApplicationDetail, name="applications_get")
async def get_application(application_id: uuid.UUID) -> ApplicationDetail:
    not_implemented(1, "applications")


@router.patch("/applications/{application_id}", response_model=ApplicationDetail, name="applications_patch")
async def patch_application(application_id: uuid.UUID, body: ApplicationPatch) -> ApplicationDetail:
    not_implemented(1, "applications")


@router.post("/applications/{application_id}/stage", response_model=ApplicationDetail,
             name="applications_change_stage")
async def change_stage(application_id: uuid.UUID, body: StageChangeIn) -> ApplicationDetail:
    not_implemented(1, "applications")


@router.get("/applications/{application_id}/timeline", response_model=list[TimelineEvent],
            name="applications_timeline")
async def timeline(application_id: uuid.UUID) -> list[TimelineEvent]:
    not_implemented(1, "applications")


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

add_crud(router, "/contacts", "contacts", ContactIn, ContactOut, wave=1, area="applications",
         ops=("list", "create", "update", "delete"))


@router.get("/mail-threads", response_model=Page[MailThreadOut], name="mail_threads_list")
async def mail_threads(application_id: uuid.UUID | None = None, needs_review: bool | None = None,
                       cursor: str | None = None) -> Page[MailThreadOut]:
    not_implemented(2, "mail")


@router.put("/mail-threads/{thread_id}", response_model=MailThreadOut, name="mail_threads_link")
async def link_mail_thread(thread_id: uuid.UUID, body: MailThreadLink) -> MailThreadOut:
    not_implemented(2, "mail")


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
