"""Applications aggregate (DESIGN.md 4, 8, 18.2, 18.3)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity, IdMixin, PydanticJSON, str_enum
from app.schemas.json_types import (
    AgentTaskState,
    ApplicationSpec,
    CheckResult,
    DraftAnswer,
    Evidence,
    GateResult,
    PacketContents,
    SubmittedSnapshot,
)


class Stage(enum.StrEnum):
    shortlisted = "shortlisted"
    tailoring = "tailoring"
    ready = "ready"
    applying = "applying"
    submitted_unconfirmed = "submitted_unconfirmed"
    submitted = "submitted"
    screening = "screening"
    interview = "interview"
    offer = "offer"
    accepted = "accepted"
    rejected = "rejected"
    withdrawn = "withdrawn"
    closed = "closed"
    skipped = "skipped"


END_STAGES = frozenset({Stage.accepted, Stage.rejected, Stage.withdrawn, Stage.closed, Stage.skipped})
LIVE_STAGES = frozenset(
    {Stage.applying, Stage.submitted_unconfirmed, Stage.submitted, Stage.screening, Stage.interview, Stage.offer}
)


class Channel(enum.StrEnum):
    email = "email"
    browser = "browser"
    manual = "manual"


class Application(Base, Entity):
    __tablename__ = "application"
    __table_args__ = (Index("ix_application_stage", "stage"),)

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="RESTRICT"), nullable=False, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign.id", ondelete="SET NULL"))
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assessment.id", ondelete="SET NULL"))
    stage: Mapped[Stage] = mapped_column(str_enum(Stage), nullable=False, default=Stage.shortlisted)
    channel: Mapped[Channel | None] = mapped_column(str_enum(Channel))
    spec: Mapped[ApplicationSpec] = mapped_column(PydanticJSON(ApplicationSpec), nullable=False,
                                                  default=ApplicationSpec)
    check_results: Mapped[list[CheckResult]] = mapped_column(PydanticJSON(list[CheckResult]), nullable=False,
                                                             default=list)
    approved_packet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_packet.id", ondelete="SET NULL", use_alter=True,
                   name="fk_application_approved_packet_id_application_packet"))
    submitted_snapshot: Mapped[SubmittedSnapshot | None] = mapped_column(PydanticJSON(SubmittedSnapshot))
    confirmation_evidence: Mapped[list[Evidence]] = mapped_column(PydanticJSON(list[Evidence]), nullable=False,
                                                                  default=list)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_outside: Mapped[bool] = mapped_column(Boolean, default=False, doc="'I applied myself'")
    next_step: Mapped[str | None] = mapped_column(String(300))
    next_due: Mapped[date | None] = mapped_column(Date)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="system", server_default="system",
                                        doc="system, owner (logged by hand) or import (history CSV)")
    owner_attested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false",
                                                 doc="Submission known only from the owner's word; no evidence")
    reference: Mapped[str | None] = mapped_column(String(200), doc="Reference number given by the employer")
    notes: Mapped[str | None] = mapped_column(Text)
    legacy_fit: Mapped[int | None] = mapped_column(Integer, doc="Imported 1-5 fit; never a rubric score")
    import_key: Mapped[str | None] = mapped_column(String(200), unique=True,
                                                   doc="Stable key of an imported history row (re-import updates)")
    import_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}",
                                                        doc="Imported columns with no home of their own")


class ApplicationEvent(Base, IdMixin):
    """Append-only timeline (a trigger rejects UPDATE and DELETE)."""

    __tablename__ = "application_event"
    __table_args__ = (Index("ix_application_event_app_created", "application_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=func.now())
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(
        String(60), nullable=False,
        doc="stage_change, edit, approval, agent_step, email, sent, acknowledged, bounced")
    actor: Mapped[str] = mapped_column(String(120), nullable=False, doc="owner, system, or runner name")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TailoringStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"  # refused by the budget; resumes when the cap allows
    done = "done"
    failed = "failed"


class TailoringRequest(Base, Entity):
    """One request to tailor an application, idempotent per (application, spec version, Kit facts)."""

    __tablename__ = "tailoring_request"
    __table_args__ = (UniqueConstraint("application_id", "request_key", name="application_request_key"),
                      Index("ix_tailoring_request_status", "status"))

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    request_key: Mapped[str] = mapped_column(String(64), nullable=False,
                                             doc="sha256 of the spec version it starts from and the Kit facts")
    from_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    status: Mapped[TailoringStatus] = mapped_column(str_enum(TailoringStatus), nullable=False,
                                                    default=TailoringStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_version: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    paused_mark: Mapped[dict[str, Any] | None] = mapped_column(JSONB, doc="Budget state when it paused")
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")


class ApplicationSpecVersion(Base, Entity):
    """Every version of an application's document spec, with the checks run on its exact content."""

    __tablename__ = "application_spec_version"
    __table_args__ = (UniqueConstraint("application_id", "version", name="application_spec_version_number"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, doc="tailor or owner")
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tailoring_request.id", ondelete="SET NULL"), unique=True,
        doc="The tailoring request that produced it: one version per request")
    parent_version: Mapped[int | None] = mapped_column(Integer)
    spec: Mapped[ApplicationSpec] = mapped_column(PydanticJSON(ApplicationSpec), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    answers: Mapped[list[DraftAnswer]] = mapped_column(PydanticJSON(list[DraftAnswer]), nullable=False,
                                                       default=list)
    check_results: Mapped[list[CheckResult]] = mapped_column(PydanticJSON(list[CheckResult]), nullable=False,
                                                             default=list)
    checked_hash: Mapped[str | None] = mapped_column(String(64), doc="content_hash the checks ran on")
    checked_facts: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict,
                                                          doc="fact code -> fact hash at check time")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)


class PendingActionType(enum.StrEnum):
    approve = "approve"
    sign_in = "sign_in"
    create_account = "create_account"
    captcha = "captcha"
    unknown_question = "unknown_question"
    assessment = "assessment"
    declaration = "declaration"
    confirm_submission = "confirm_submission"
    review_import = "review_import"
    conflict_choice = "conflict_choice"
    answer_review_due = "answer_review_due"
    follow_up = "follow_up"


class PendingStatus(enum.StrEnum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"
    expired = "expired"


class PendingAction(Base, Entity):
    __tablename__ = "pending_action"
    __table_args__ = (Index("ix_pending_action_status", "status", "deadline"),)

    type: Mapped[PendingActionType] = mapped_column(str_enum(PendingActionType), nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    agent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_task.id", ondelete="SET NULL"))
    group_key: Mapped[str | None] = mapped_column(String(200), doc="Shared blocker grouping on Today (18.4)")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    checkpoint: Mapped[AgentTaskState | None] = mapped_column(PydanticJSON(AgentTaskState))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[PendingStatus] = mapped_column(str_enum(PendingStatus), nullable=False,
                                                  default=PendingStatus.open)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationPacket(Base, Entity):
    """A versioned, hashed packet. Approvals and permits bind to (application, version, hash)."""

    __tablename__ = "application_packet"
    __table_args__ = (UniqueConstraint("application_id", "version", name="application_version"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, doc="sha256 of canonical JSON contents")
    contents: Mapped[PacketContents] = mapped_column(PydanticJSON(PacketContents), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_reason: Mapped[str | None] = mapped_column(Text)


class SubmitPermit(Base, Entity):
    __tablename__ = "submit_permit"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    packet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application_packet.id", ondelete="RESTRICT"))
    packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_task.id", ondelete="SET NULL"))
    runner_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_token.id", ondelete="SET NULL"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checks: Mapped[list[GateResult]] = mapped_column(PydanticJSON(list[GateResult]), nullable=False, default=list)


class DispatchStatus(enum.StrEnum):
    reserved = "reserved"
    handed_off = "handed_off"
    sent = "sent"
    acknowledged = "acknowledged"
    bounced = "bounced"
    failed = "failed"
    unknown = "unknown"
    cancelled = "cancelled"


class DispatchAttempt(Base, Entity):
    """Written, with caps reserved, in one transaction before anything is sent (18.3).
    An attempt with no recorded outcome is never resent automatically."""

    __tablename__ = "dispatch_attempt"
    __table_args__ = (Index("ix_dispatch_attempt_status", "status"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="RESTRICT"))
    packet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application_packet.id", ondelete="RESTRICT"))
    packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel), nullable=False)
    permit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("submit_permit.id", ondelete="SET NULL"))
    status: Mapped[DispatchStatus] = mapped_column(str_enum(DispatchStatus), nullable=False,
                                                   default=DispatchStatus.reserved)
    send_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(300))
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gate_results: Mapped[list[GateResult]] = mapped_column(PydanticJSON(list[GateResult]), nullable=False,
                                                           default=list)
    error: Mapped[str | None] = mapped_column(Text)


class AgentTaskType(enum.StrEnum):
    apply = "apply"
    sweep_site = "sweep_site"
    check_posting = "check_posting"


class AgentTaskStatus(enum.StrEnum):
    queued = "queued"
    claimed = "claimed"
    blocked = "blocked"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class AgentTask(Base, Entity):
    __tablename__ = "agent_task"
    __table_args__ = (Index("ix_agent_task_status", "status", "created_at"),)

    type: Mapped[AgentTaskType] = mapped_column(str_enum(AgentTaskType), nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    preferred_runner: Mapped[str | None] = mapped_column(String(20), doc="pc or server")
    claimed_by_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_token.id", ondelete="SET NULL"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint: Mapped[AgentTaskState | None] = mapped_column(PydanticJSON(AgentTaskState))
    status: Mapped[AgentTaskStatus] = mapped_column(str_enum(AgentTaskStatus), nullable=False,
                                                    default=AgentTaskStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    released: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                     doc="Record of what the runner was given (18.1)")


class PortalAccountStatus(enum.StrEnum):
    none = "none"
    created = "created"
    signed_in = "signed_in"


class PortalAccount(Base, Entity):
    """One row per portal tenant. Never a password."""

    __tablename__ = "portal_account"

    portal: Mapped[str] = mapped_column(String(60), nullable=False, doc="workday, icims, taleo, ...")
    tenant: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PortalAccountStatus] = mapped_column(str_enum(PortalAccountStatus), nullable=False,
                                                        default=PortalAccountStatus.none)
    signed_in_runner: Mapped[str | None] = mapped_column(String(120))
    email_used: Mapped[str | None] = mapped_column(String(320))
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("portal", "tenant", name="portal_tenant"),)


class Contact(Base, Entity):
    __tablename__ = "contact"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    link: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")


class InterviewPack(Base, Entity):
    __tablename__ = "interview_pack"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), unique=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("application.id", ondelete="SET NULL"))
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                     doc="section key -> {content, fact_ids, sources}")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(String(128))


class InterviewRound(Base, Entity):
    __tablename__ = "interview_round"

    pack_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interview_pack.id", ondelete="CASCADE"), index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    format: Mapped[str | None] = mapped_column(String(60))
    interviewers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    checklist: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    thank_you_draft: Mapped[str | None] = mapped_column(Text)
    learnt: Mapped[str | None] = mapped_column(Text)


class MailClassification(enum.StrEnum):
    confirmation = "confirmation"
    rejection = "rejection"
    interview = "interview"
    other = "other"


class MailThread(Base, Entity):
    __tablename__ = "mail_thread"
    __table_args__ = (UniqueConstraint("connection_id", "provider_thread_id", name="connection_thread"),)

    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connection.id", ondelete="SET NULL"))
    provider_thread_id: Mapped[str] = mapped_column(String(300), nullable=False)
    provider_message_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("application.id", ondelete="SET NULL"))
    subject: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[MailClassification] = mapped_column(str_enum(MailClassification), nullable=False,
                                                               default=MailClassification.other)
    match_confidence: Mapped[float | None] = mapped_column()
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
