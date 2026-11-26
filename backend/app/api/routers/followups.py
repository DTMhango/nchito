"""Messages about an application, the follow-up due list and the wind-down (DESIGN.md 8.2, 18.2, 18.4; wave 4).

Errors are ``{"detail": {"code", "reason", ...}}`` with codes from ``app.apply.errors``. Nothing here sends on its
own: a message is drafted, checked, approved by the owner (packet + hash), then ``/send`` asks for a single-use
permit and queues it behind the email send delay; the worker sends it in the same mail thread.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import ApiModel, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import errors as apply_errors
from app.apply import winddown
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm.deps import llm_service
from app.llm.service import LLMService
from app.models.applications import Application, ApplicationPacket
from app.models.followups import OutboundMessage, WindDown
from app.pipeline.checks import service as check_service
from app.pipeline.checks.findings import worst
from app.pipeline.followups import checks, drafting, due, sending
from app.pipeline.followups import context as ctx_mod
from app.schemas.json_types import (
    CheckResult,
    FollowupDueStatus,
    MessageKind,
    MessageSendState,
    MessageStatus,
    SpecItem,
    WindDownChoice,
)

router = APIRouter(prefix="/api", tags=["followups"], dependencies=[RequireOwner])

LLMDep = Annotated[LLMService, Depends(llm_service)]


def _err(status_code: int, code: str, reason: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code, detail=apply_errors.detail(code, reason, **extra))


# ----- shapes --------------------------------------------------------------------------------------


class MessagePacketOut(ApiModel):
    id: uuid.UUID
    version: int
    content_hash: str
    approved_at: datetime | None
    approved_by: str | None
    invalidated_at: datetime | None


class MessageDispatchOut(ApiModel):
    id: uuid.UUID
    status: str
    send_after: datetime | None
    started_at: datetime | None
    outcome_at: datetime | None
    error: str | None
    provider_message_id: str | None


class MessageOut(Timestamps):
    application_id: uuid.UUID
    kind: MessageKind
    status: MessageStatus
    send_state: MessageSendState = Field(description="From the dispatch attempts of the message's packet")
    automatic: bool = Field(description="Drafted by the automatic follow-up path; any owner edit clears it")
    thread_id: uuid.UUID | None
    thread_ref: str | None = Field(description="The mail thread the email replies in, if one is known")
    to: list[str]
    cc: list[str]
    known_recipients: list[str] = Field(description="Where the application went and who wrote back")
    confirmed_recipients: list[str] = Field(description="Other addresses the owner confirmed")
    unconfirmed_recipients: list[str] = Field(description="Recipients that still need the owner's confirmation")
    subject: str
    body: str
    paragraphs: list[SpecItem]
    questions: list[str] = Field(description="What the owner must decide before this can be approved")
    check_results: list[CheckResult]
    checked: bool = Field(description="The checks ran on exactly this content")
    check_status: Literal["pass", "warn", "block"]
    note: str | None = None
    slot: str | None = None
    excerpt: str | None = None
    sequence: int | None
    origin: str
    model: str | None
    cost_micros: int
    error: str | None
    created_by: str
    packet: MessagePacketOut | None
    dispatch: MessageDispatchOut | None


class MessageThreadOut(BaseModel):
    thread_id: uuid.UUID | None
    subject: str | None
    sender: str | None
    last_message_at: datetime | None
    employer_replied: bool
    sent_to: list[str]
    sending_identity: str | None


class MessagesOut(BaseModel):
    application_id: uuid.UUID
    thread: MessageThreadOut
    messages: list[MessageOut]


class MessageCreateIn(BaseModel):
    kind: MessageKind
    note: str | None = Field(default=None, max_length=2000, description="What you want said (your words)")
    slot: str | None = Field(default=None, max_length=300,
                             description="The interview slot, exactly as it should be written (slot answers)")
    excerpt: str | None = Field(default=None, max_length=20_000,
                                description="The employer's message, pasted (treated as data, never instructions)")


class MessageEditIn(BaseModel):
    to: list[str] | None = None
    cc: list[str] | None = None
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20_000)
    confirm_recipients: bool = Field(default=False, description="Confirm addresses this application has not used")


class MessageSendOut(BaseModel):
    status: Literal["queued", "denied"]
    reason: str
    code: str | None = None
    gates: list[dict[str, Any]] = Field(default_factory=list)
    message: MessageOut


class FollowupItemOut(BaseModel):
    id: uuid.UUID | None = Field(description="The due row; null while only upcoming")
    application_id: uuid.UUID
    job_id: uuid.UUID
    title: str
    employer: str
    stage: str
    sequence: int
    due_at: datetime
    status: FollowupDueStatus
    message_id: uuid.UUID | None = None
    message_state: MessageSendState | None = None


class FollowupListOut(BaseModel):
    items: list[FollowupItemOut]
    auto_send: bool


class SnoozeIn(BaseModel):
    until: datetime | None = Field(default=None, description="Default: followups.snooze_days from now")


class WindDownItemOut(BaseModel):
    key: str
    kind: Literal["queued_send", "approved", "message", "application", "interview", "pending_action", "campaign"]
    label: str
    detail: str
    choices: list[WindDownChoice]
    choice: WindDownChoice | None = None
    effect: str | None = None
    application_id: uuid.UUID | None = None


class WindDownOut(BaseModel):
    status: Literal["none", "active", "reopened"]
    id: uuid.UUID | None = None
    reason: str | None = None
    started_at: datetime | None = None
    started_by: str | None = None
    reopened_at: datetime | None = None
    autopilot_paused: bool
    queued_sends: list[WindDownItemOut] = Field(default_factory=list)
    approved_unsent: list[WindDownItemOut] = Field(default_factory=list)
    live_applications: dict[str, list[WindDownItemOut]] = Field(default_factory=dict)
    interviews: list[WindDownItemOut] = Field(default_factory=list)
    pending_actions: list[WindDownItemOut] = Field(default_factory=list)
    campaigns: list[WindDownItemOut] = Field(default_factory=list)


class WindDownStartIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    accepted_application_id: uuid.UUID | None = None


class WindDownChoiceIn(BaseModel):
    key: str = Field(max_length=100)
    choice: WindDownChoice


# ----- helpers -------------------------------------------------------------------------------------


async def _message(session: Any, message_id: uuid.UUID, *, lock: bool = False) -> OutboundMessage:
    msg = await session.get(OutboundMessage, message_id, with_for_update=lock)
    if msg is None:
        raise _err(404, "not_found", "message not found")
    return msg


async def _application(session: Any, application_id: uuid.UUID) -> Application:
    app = await session.get(Application, application_id)
    if app is None:
        raise _err(404, "not_found", "application not found")
    return app


async def message_out(session: Any, msg: OutboundMessage) -> MessageOut:
    await session.flush()
    await session.refresh(msg)  # server-set timestamps
    rows = await sending.attempts(session, msg)
    packet = await session.get(ApplicationPacket, msg.packet_id) if msg.packet_id else None
    known = {a.lower() for a in [*msg.known_recipients, *msg.confirmed_recipients]}
    last = rows[-1] if rows else None
    return MessageOut(
        id=msg.id, created_at=msg.created_at, updated_at=msg.updated_at, application_id=msg.application_id,
        kind=msg.kind, status=msg.status, send_state=sending.send_state(rows),  # type: ignore[arg-type]
        automatic=msg.automatic, thread_id=msg.thread_id, thread_ref=msg.thread_ref, to=msg.to, cc=msg.cc,
        known_recipients=msg.known_recipients, confirmed_recipients=msg.confirmed_recipients,
        unconfirmed_recipients=[a for a in [*msg.to, *msg.cc] if a.lower() not in known], subject=msg.subject,
        body=checks.body_of(msg.paragraphs), paragraphs=msg.paragraphs, questions=msg.questions,
        check_results=msg.check_results, checked=checks.is_checked(msg), check_status=worst(msg.check_results),
        note=msg.context.get("note"), slot=msg.context.get("slot"), excerpt=msg.context.get("excerpt"),
        sequence=msg.sequence, origin=msg.origin, model=msg.model, cost_micros=msg.cost_micros, error=msg.error,
        created_by=msg.created_by,
        packet=MessagePacketOut.model_validate(packet) if packet else None,
        dispatch=MessageDispatchOut(id=last.id, status=last.status.value, send_after=last.send_after,
                                    started_at=last.started_at, outcome_at=last.outcome_at, error=last.error,
                                    provider_message_id=last.provider_message_id) if last else None)


# ----- messages ------------------------------------------------------------------------------------


@router.get("/applications/{application_id}/messages", response_model=MessagesOut, name="messages_list")
async def list_messages(application_id: uuid.UUID, session: SessionDep) -> MessagesOut:
    """The application's mail thread (as far as it is known) and every message drafted for it."""
    app = await _application(session, application_id)
    ctx = await ctx_mod.load(session, app)
    rows = (await session.scalars(select(OutboundMessage).where(OutboundMessage.application_id == app.id)
                                  .order_by(OutboundMessage.created_at))).all()
    t = ctx.thread
    thread = MessageThreadOut(thread_id=t.id if t else None, subject=t.subject if t else ctx_mod.base_subject(ctx),
                              sender=t.sender if t else None, last_message_at=t.last_message_at if t else None,
                              employer_replied=ctx.employer_replied, sent_to=ctx.sent_to,
                              sending_identity=ctx.sending_identity)
    return MessagesOut(application_id=app.id, thread=thread, messages=[await message_out(session, m) for m in rows])


@router.post("/applications/{application_id}/messages", response_model=MessageOut,
             status_code=status.HTTP_201_CREATED, name="messages_create")
async def create_message(application_id: uuid.UUID, body: MessageCreateIn, session: SessionDep,
                         principal: PrincipalDep, llm: LLMDep) -> MessageOut:
    """Draft a message from Kit facts and the thread (one budgeted model call, then the checks). Never sent
    from here. A budget refusal returns the message as ``budget_paused``."""
    app = await _application(session, application_id)
    try:
        msg = await drafting.create(session, llm, app, body.kind, inputs=body.model_dump(exclude={"kind"}),
                                    actor=principal.actor)
    except drafting.DraftError as exc:
        raise _err(exc.status, exc.code, exc.message) from exc
    return await message_out(session, msg)


@router.get("/messages/{message_id}", response_model=MessageOut, name="messages_get")
async def get_message(message_id: uuid.UUID, session: SessionDep) -> MessageOut:
    return await message_out(session, await _message(session, message_id))


@router.put("/messages/{message_id}", response_model=MessageOut, name="messages_update")
async def update_message(message_id: uuid.UUID, body: MessageEditIn, session: SessionDep,
                         principal: PrincipalDep) -> MessageOut:
    """The owner's edit. Withdraws an approval (the old packet and its permits go), clears the automatic
    flag, and re-runs the code checks. New addresses stay unconfirmed unless ``confirm_recipients``."""
    msg = await _message(session, message_id, lock=True)
    if msg.status == "discarded":
        raise _err(409, "message_not_draft", "this message was discarded")
    why = await sending.locked(session, msg)
    if why:
        raise _err(409, "already_handed_over", why)
    now = utcnow()
    await sending.withdraw_approval(session, msg, actor=principal.actor, reason="edited by the owner", now=now)
    changed: list[str] = []
    if body.to is not None or body.cc is not None:
        to = [a.strip().lower() for a in (body.to if body.to is not None else msg.to) if a.strip()]
        cc = [a.strip().lower() for a in (body.cc if body.cc is not None else msg.cc) if a.strip()]
        known = {a.lower() for a in msg.known_recipients}
        if body.confirm_recipients:
            msg.confirmed_recipients = sorted({*msg.confirmed_recipients, *(a for a in [*to, *cc] if a not in known)})
        msg.to, msg.cc = to, cc
        changed.append("recipients")
    if body.subject is not None:
        msg.subject = body.subject.strip()
        changed.append("subject")
    if body.body is not None:
        msg.paragraphs = checks.paragraphs_from(body.body, msg.paragraphs)
        msg.context = {**msg.context, "model_questions": []}  # the owner has answered by editing
        changed.append("body")
    msg.automatic, msg.origin = False, "owner"
    if msg.status in ("budget_paused", "failed"):
        msg.status = "draft"
    await sending.recheck_message(session, msg, now=now)
    await audit.record(session, actor=principal.actor, action="message.edited", subject_type="application",
                       subject_id=msg.application_id, detail={"message_id": str(msg.id), "changed": changed,
                                                              "recipients": msg.to,
                                                              "confirmed": msg.confirmed_recipients})
    return await message_out(session, msg)


@router.post("/messages/{message_id}/regenerate", response_model=MessageOut, name="messages_regenerate")
async def regenerate_message(message_id: uuid.UUID, session: SessionDep, principal: PrincipalDep,
                             llm: LLMDep) -> MessageOut:
    """Write the draft again (one budgeted model call)."""
    msg = await _message(session, message_id, lock=True)
    if msg.status not in ("draft", "budget_paused", "failed", "approved") or await sending.locked(session, msg):
        raise _err(409, "message_not_draft", f"a {msg.status} message cannot be redrafted")
    await sending.withdraw_approval(session, msg, actor=principal.actor, reason="redrafted", now=utcnow())
    await drafting.generate(session, llm, msg)
    await audit.record(session, actor=principal.actor, action="message.redrafted", subject_type="application",
                       subject_id=msg.application_id, detail={"message_id": str(msg.id), "status": msg.status})
    return await message_out(session, msg)


@router.post("/messages/{message_id}/check", response_model=MessageOut, name="messages_check")
async def check_message(message_id: uuid.UUID, session: SessionDep, llm: LLMDep) -> MessageOut:
    """Run the code checks again, plus the model claim check when ``tailoring.claim_check_enabled``."""
    msg = await _message(session, message_id, lock=True)
    app = await _application(session, msg.application_id)
    ctx = await ctx_mod.load(session, app)
    _, kit = await check_service.context(session, app)
    _, cost = await checks.run(session, msg, ctx, kit, await settings_service.values(session), today=utcnow().date(),
                               client=llm)
    msg.cost_micros += cost
    return await message_out(session, msg)


@router.post("/messages/{message_id}/approve", response_model=MessageOut, name="messages_approve")
async def approve_message(message_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> MessageOut:
    """The owner's approval: the checks run again, then the message is snapshotted as a hashed packet.
    409 ``check_blocking`` / ``message_questions`` / ``no_recipient`` / ``no_identity`` with the results."""
    msg = await _message(session, message_id, lock=True)
    try:
        await sending.approve(session, msg, actor=principal.actor)
    except sending.SendError as exc:
        raise _err(exc.status, exc.code, exc.message, **exc.extra) from exc
    return await message_out(session, msg)


@router.post("/messages/{message_id}/send", response_model=MessageSendOut, name="messages_send")
async def send_message(message_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> MessageSendOut:
    """Ask for the single-use permit (every message gate) and queue the approved message behind the email
    send delay. ``denied`` carries the first blocking gate's code and every gate."""
    msg = await _message(session, message_id, lock=True)
    result = await sending.queue(session, msg, actor=principal.actor)
    return MessageSendOut(status="queued" if result.status == "queued" else "denied", reason=result.reason,
                          code=result.code, gates=result.gates, message=await message_out(session, msg))


@router.post("/messages/{message_id}/cancel", response_model=MessageOut, name="messages_cancel")
async def cancel_message(message_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> MessageOut:
    """Cancel a queued send during the delay. 409 ``already_handed_over`` once the mailbox has it."""
    msg = await _message(session, message_id, lock=True)
    try:
        await sending.cancel(session, msg, actor=principal.actor)
    except sending.SendError as exc:
        raise _err(exc.status, exc.code, exc.message) from exc
    return await message_out(session, msg)


@router.post("/messages/{message_id}/discard", response_model=MessageOut, name="messages_discard")
async def discard_message(message_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> MessageOut:
    msg = await _message(session, message_id, lock=True)
    why = await sending.locked(session, msg)
    if why:
        raise _err(409, "already_handed_over", why)
    await sending.withdraw_approval(session, msg, actor=principal.actor, reason="discarded", now=utcnow())
    msg.status = "discarded"
    await audit.record(session, actor=principal.actor, action="message.discarded", subject_type="application",
                       subject_id=msg.application_id, detail={"message_id": str(msg.id)})
    return await message_out(session, msg)


# ----- follow-ups ----------------------------------------------------------------------------------


async def _item(session: Any, item: due.DueItem) -> FollowupItemOut:
    state = None
    if item.message_id is not None:
        msg = await session.get(OutboundMessage, item.message_id)
        state = sending.send_state(await sending.attempts(session, msg)) if msg else None
    return FollowupItemOut(id=item.row.id if item.row else None, application_id=item.application_id,
                           job_id=item.job_id, title=item.title, employer=item.employer, stage=item.stage,
                           sequence=item.sequence, due_at=item.due_at, status=item.status,  # type: ignore[arg-type]
                           message_id=item.message_id, message_state=state)  # type: ignore[arg-type]


@router.get("/follow-ups", response_model=FollowupListOut, name="followups_list")
async def list_followups(session: SessionDep) -> FollowupListOut:
    """Follow-ups due, snoozed or drafted, and those coming up in the next 30 days, soonest first."""
    items = await due.due_list(session)
    return FollowupListOut(items=[await _item(session, i) for i in items],
                           auto_send=bool(await settings_service.get_value(session, "followups.auto_send")))


async def _row_item(session: Any, row: Any) -> FollowupItemOut:
    app = await _application(session, row.application_id)
    from app.models.search import Job

    job = await session.get(Job, app.job_id)
    return await _item(session, due.DueItem(app.id, job.id, job.title, job.employer, app.stage.value, row.sequence,
                                            row.snoozed_until or row.due_at, row.status, row, row.message_id))


@router.post("/follow-ups/{application_id}/draft", response_model=MessageOut, status_code=status.HTTP_201_CREATED,
             name="followups_draft")
async def draft_followup(application_id: uuid.UUID, session: SessionDep, principal: PrincipalDep,
                         llm: LLMDep) -> MessageOut:
    """Draft the follow-up that is due (or the next one, early). For your approval: never sent from here."""
    app = await _application(session, application_id)
    now = utcnow()
    try:
        row = await due.ensure_row(session, app, now=now)
    except due.DueError as exc:
        raise _err(exc.status, exc.code, exc.message) from exc
    if row.message_id is not None:
        existing = await session.get(OutboundMessage, row.message_id)
        if existing is not None and existing.status != "discarded":
            return await message_out(session, existing)
    msg = await drafting.create(session, llm, app, "follow_up", actor=principal.actor, sequence=row.sequence, now=now)
    row.message_id, row.status = msg.id, "drafted"
    return await message_out(session, msg)


@router.post("/follow-ups/{application_id}/snooze", response_model=FollowupItemOut, name="followups_snooze")
async def snooze_followup(application_id: uuid.UUID, body: SnoozeIn, session: SessionDep,
                          principal: PrincipalDep) -> FollowupItemOut:
    app = await _application(session, application_id)
    try:
        row = await due.snooze(session, await due.ensure_row(session, app, now=utcnow()), actor=principal.actor,
                               until=body.until)
    except due.DueError as exc:
        raise _err(exc.status, exc.code, exc.message) from exc
    return await _row_item(session, row)


@router.post("/follow-ups/{application_id}/not-needed", response_model=FollowupItemOut, name="followups_not_needed")
async def followup_not_needed(application_id: uuid.UUID, session: SessionDep,
                              principal: PrincipalDep) -> FollowupItemOut:
    app = await _application(session, application_id)
    try:
        row = await due.not_needed(session, await due.ensure_row(session, app, now=utcnow()), actor=principal.actor)
    except due.DueError as exc:
        raise _err(exc.status, exc.code, exc.message) from exc
    return await _row_item(session, row)


# ----- wind-down -----------------------------------------------------------------------------------


def _items(items: list[winddown.Item]) -> list[WindDownItemOut]:
    return [WindDownItemOut(key=i.key, kind=i.kind, label=i.label, detail=i.detail, choices=i.choices,  # type: ignore
                            choice=i.choice, effect=i.effect, application_id=i.application_id) for i in items]


async def wind_down_out(session: Any, wd: WindDown | None) -> WindDownOut:
    from app.apply import dispatch

    paused = await dispatch.is_paused(session)
    if wd is None:
        return WindDownOut(status="none", autopilot_paused=paused)
    await session.flush()
    await session.refresh(wd)
    v = await winddown.view(session, wd)
    return WindDownOut(status=wd.status, id=wd.id, reason=wd.reason, started_at=wd.created_at,  # type: ignore
                       started_by=wd.started_by, reopened_at=wd.reopened_at, autopilot_paused=paused,
                       queued_sends=_items(v.queued_sends), approved_unsent=_items(v.approved_unsent),
                       live_applications={k: _items(x) for k, x in v.live_applications.items()},
                       interviews=_items(v.interviews), pending_actions=_items(v.pending_actions),
                       campaigns=_items(v.campaigns))


@router.get("/wind-down", response_model=WindDownOut, name="winddown_get")
async def get_wind_down(session: SessionDep) -> WindDownOut:
    """The latest wind-down with what is still in motion (``status: none`` before the first)."""
    return await wind_down_out(session, await winddown.latest(session))


@router.post("/wind-down", response_model=WindDownOut, name="winddown_start")
async def start_wind_down(body: WindDownStartIn, session: SessionDep, principal: PrincipalDep) -> WindDownOut:
    """"I've accepted an offer": the master pause goes on at once (queued sends cancelled, permits revoked),
    then the view is listed. Sends nothing. Starting again while one is active returns it."""
    if body.accepted_application_id is not None:
        await _application(session, body.accepted_application_id)
    wd = await winddown.start(session, actor=principal.actor, reason=body.reason,
                              accepted_application_id=body.accepted_application_id)
    return await wind_down_out(session, wd)


@router.post("/wind-down/choices", response_model=WindDownOut, name="winddown_choose")
async def choose_wind_down(body: WindDownChoiceIn, session: SessionDep, principal: PrincipalDep,
                           llm: LLMDep) -> WindDownOut:
    """Keep, pause or withdraw one item. Withdrawing a sent application drafts an email for your approval."""
    wd = await winddown.active(session)
    if wd is None:
        raise _err(409, "no_winddown", "no wind-down is active")
    try:
        await winddown.choose(session, wd, body.key, body.choice, actor=principal.actor, client=llm)
    except winddown.WindDownError as exc:
        raise _err(exc.status, exc.code, exc.message) from exc
    return await wind_down_out(session, wd)


@router.post("/wind-down/reopen", response_model=WindDownOut, name="winddown_reopen")
async def reopen_wind_down(session: SessionDep, principal: PrincipalDep) -> WindDownOut:
    """"Reopen my search": everything comes back paused, never deleted; the master pause stays on."""
    wd = await winddown.active(session)
    if wd is None:
        raise _err(409, "no_winddown", "no wind-down is active")
    await winddown.reopen(session, wd, actor=principal.actor)
    return await wind_down_out(session, wd)


@router.get("/wind-down/summary", response_class=PlainTextResponse, name="winddown_summary",
            responses={200: {"content": {"text/markdown": {}}}})
async def wind_down_summary(session: SessionDep) -> PlainTextResponse:
    """The final summary as Markdown (download)."""
    wd = await winddown.latest(session)
    if wd is None:
        raise _err(404, "no_winddown", "there has been no wind-down")
    now = utcnow()
    text = winddown.summary_text(await winddown.view(session, wd, now=now),
                                 str(await settings_service.get_value(session, "general.app_name")), now)
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="wind-down-{now:%Y%m%d}.md"'})
