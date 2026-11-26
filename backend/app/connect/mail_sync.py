"""Inbound mail: fetch since the checkpoint, match replies to applications, classify, propose or apply.

Matching (DESIGN.md 12): by thread, by Message-ID references to what we sent, then by the employer's
address (the packet's recipients), and only when exactly one application fits. An ambiguous or weak
match goes to review (``MailThread.needs_review``) and never changes an application.

A classification proposes a stage change as a pending action. It is applied directly only for the
reply kinds the owner listed in ``mail.auto_apply_classes``. Mail text is data: nothing in it is executed.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.apply import stages
from app.apply.stages import IllegalTransition
from app.connect import mail_connections
from app.connect.mail_classify import Classification, classify, phrases_from
from app.connect.mail_common import key_from_ids, sender_matches, strip_brackets
from app.connect.mailbox import Mailbox, MailError, MailMessage
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm.client import LLMClient
from app.models.applications import (
    Application,
    ApplicationPacket,
    DispatchAttempt,
    DispatchStatus,
    MailClassification,
    MailThread,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.platform import Connection
from app.models.search import Job, Source
from app.schemas.json_types import Evidence

log = logging.getLogger(__name__)

# Webmail domains say nothing about the employer, so a domain match is not made on them.
FREE_MAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
                               "live.com", "proton.me", "protonmail.com", "aol.com"})
STAGE_FOR: dict[str, Stage] = {"rejection": Stage.rejected, "interview": Stage.interview}
PROPOSAL_KIND = "mail_stage_proposal"
_ATTEMPT_IN_TEXT = re.compile(r"nchito-([0-9a-fA-F-]{36})@")


@dataclass
class SyncResult:
    fetched: int = 0
    new: int = 0
    linked: int = 0
    review: int = 0
    proposed: int = 0
    applied: int = 0
    skipped: int = 0


@dataclass
class Match:
    application: Application | None
    confidence: float
    how: str
    ambiguous: bool = False


@dataclass
class _Candidate:
    app: Application
    recipients: set[str]
    requisition: str | None


# ----- matching ---------------------------------------------------------------------------------


async def _candidates(session: AsyncSession) -> list[_Candidate]:
    rows = await session.execute(
        select(Application, ApplicationPacket)
        .outerjoin(ApplicationPacket, ApplicationPacket.id == Application.approved_packet_id)
        .where(Application.applied_at.is_not(None)))
    out: list[_Candidate] = []
    for app, packet in rows.all():
        recipients: set[str] = set()
        requisition = None
        if packet is not None:
            requisition = packet.contents.requisition
            if packet.contents.email:
                recipients = {a.strip().lower() for a in [*packet.contents.email.to, *packet.contents.email.cc]}
        out.append(_Candidate(app, recipients, requisition))
    return out


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


async def match_message(session: AsyncSession, msg: MailMessage, connection_id: uuid.UUID | None) -> Match:
    thread = await session.scalar(select(MailThread).where(
        MailThread.connection_id == connection_id, MailThread.provider_thread_id == msg.thread_id))
    if thread is not None and thread.application_id is not None and not thread.needs_review:
        app = await session.get(Application, thread.application_id)
        if app is not None:
            return Match(app, 1.0, "thread")
    raw_refs = [*msg.headers.get("references", "").split(), msg.headers.get("in-reply-to", "")]
    refs = [strip_brackets(r) for r in raw_refs if r]
    attempt_id = key_from_ids(*refs)
    attempt: DispatchAttempt | None = None
    if attempt_id:
        try:
            attempt = await session.get(DispatchAttempt, uuid.UUID(attempt_id))
        except ValueError:
            attempt = None
    if attempt is None and refs:
        attempt = await session.scalar(select(DispatchAttempt).where(DispatchAttempt.provider_message_id.in_(refs)))
    if attempt is not None:
        app = await session.get(Application, attempt.application_id)
        if app is not None:
            return Match(app, 0.95, "reference")
    candidates = await _candidates(session)
    text = f"{msg.subject}\n{msg.body_text}".casefold()
    exact = [c for c in candidates if msg.sender in c.recipients]
    if exact:
        by_req = [c for c in exact if c.requisition and c.requisition.casefold() in text]
        if len(by_req) == 1:
            return Match(by_req[0].app, 0.95, "address+requisition")
        if len(exact) == 1:
            return Match(exact[0].app, 0.85, "address")
        return Match(None, 0.4, "address", ambiguous=True)
    domain = _domain(msg.sender)
    if domain and domain not in FREE_MAIL_DOMAINS:
        same = [c for c in candidates if any(_domain(r) == domain for r in c.recipients)]
        if len(same) == 1:
            return Match(same[0].app, 0.6, "domain")
        if len(same) > 1:
            return Match(None, 0.4, "domain", ambiguous=True)
    return Match(None, 0.0, "none")


# ----- stage proposals --------------------------------------------------------------------------


def _label(category: str) -> str:
    return {"confirmation": "an acknowledgement", "rejection": "a rejection", "interview": "an interview invitation",
            "information_request": "a request for information"}[category]


async def _open_proposal(session: AsyncSession, app_id: uuid.UUID, thread_id: uuid.UUID, category: str) -> bool:
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.application_id == app_id, PendingAction.status == PendingStatus.open))
    return any(a.detail.get("kind") == PROPOSAL_KIND and a.detail.get("thread_id") == str(thread_id)
               and a.detail.get("category") == category for a in rows)


async def _mark_attempt(session: AsyncSession, app: Application, status: DispatchStatus, now: datetime) -> None:
    attempt = await session.scalar(select(DispatchAttempt).where(
        DispatchAttempt.application_id == app.id, DispatchAttempt.status.in_([DispatchStatus.sent,
                                                                              DispatchStatus.unknown,
                                                                              DispatchStatus.acknowledged]))
        .order_by(DispatchAttempt.created_at.desc()).limit(1))
    if attempt is not None and attempt.status != status:
        attempt.status = status
        attempt.outcome_at = now


async def apply_stage_change(session: AsyncSession, app: Application, category: str, *, thread_id: uuid.UUID,
                             message_id: str, actor: str, now: datetime | None = None) -> bool:
    """Apply what a classified reply implies. Returns whether the application's stage moved."""
    now = now or utcnow()
    detail = {"thread_id": str(thread_id), "message_id": message_id}
    if category == "confirmation":
        evidence = Evidence(kind="confirmation_email", value=message_id, at=now.isoformat())
        app.confirmation_evidence = [*app.confirmation_evidence, evidence]
        await _mark_attempt(session, app, DispatchStatus.acknowledged, now)
        await stages.add_event(session, app.id, "acknowledged", actor, detail)
        if app.stage == Stage.submitted_unconfirmed:
            await stages.transition(session, app, Stage.submitted, actor=actor, why="confirmation email", via="system",
                                    now=now, detail=detail)
            return True
        return False
    target = STAGE_FOR.get(category)
    if target is None:
        return False
    try:
        await stages.transition(session, app, target, actor=actor, why=f"{category} email", via="system", now=now,
                                detail=detail)
    except IllegalTransition:
        return False
    return True


async def apply_proposal(session: AsyncSession, action: PendingAction, *, actor: str) -> bool:
    """Carry out a ``mail_stage_proposal`` pending action the owner approved (called from the resolve flow)."""
    if action.detail.get("kind") != PROPOSAL_KIND or action.application_id is None:
        return False
    app = await session.get(Application, action.application_id)
    if app is None:
        return False
    moved = await apply_stage_change(session, app, str(action.detail["category"]),
                                     thread_id=uuid.UUID(str(action.detail["thread_id"])),
                                     message_id=str(action.detail.get("message_id", "")), actor=actor)
    await audit.record(session, actor=actor, action="mail.stage_applied", subject_type="application",
                       subject_id=app.id, detail={"category": action.detail["category"], "moved": moved})
    return moved


async def act_on_thread(session: AsyncSession, thread: MailThread, app: Application, category: str, message_id: str,
                        auto_classes: list[str], res: SyncResult) -> None:
    """Propose (or, if allowed, apply) what ``category`` implies for ``app``."""
    if category == "other":
        return
    if category == "confirmation" and app.stage == Stage.submitted:
        await apply_stage_change(session, app, "confirmation", thread_id=thread.id, message_id=message_id,
                                 actor="mail")  # informational: acknowledged, evidence kept
        return
    if category == "confirmation" and app.stage != Stage.submitted_unconfirmed:
        return
    if category in STAGE_FOR and not stages.check_transition(app, STAGE_FOR[category], "system").ok:
        return
    auto = category in auto_classes and category != "information_request"
    if auto and await apply_stage_change(session, app, category, thread_id=thread.id, message_id=message_id,
                                         actor="mail"):
        res.applied += 1
        await audit.record(session, actor="mail", action="mail.stage_applied", subject_type="application",
                           subject_id=app.id, detail={"category": category, "automatic": True})
        return
    if await _open_proposal(session, app.id, thread.id, category):
        return
    job = await session.get(Job, app.job_id)
    who = f"{job.employer} ({job.title})" if job else "this application"
    if category == "information_request":
        title, ptype = f"Reply needed: {who} asks for information", PendingActionType.follow_up
    elif category == "confirmation":
        title, ptype = f"{who} acknowledged your application: mark it submitted?", PendingActionType.confirm_submission
    else:
        title = f"{who} sent {_label(category)}: move to {STAGE_FOR[category].value}?"
        ptype = PendingActionType.follow_up
    session.add(PendingAction(type=ptype, application_id=app.id, title=title, status=PendingStatus.open, detail={
        "kind": PROPOSAL_KIND, "category": category, "thread_id": str(thread.id), "message_id": message_id,
        "proposed_stage": (Stage.submitted.value if category == "confirmation" else
                           STAGE_FOR[category].value if category in STAGE_FOR else None),
        "subject": thread.subject}))
    res.proposed += 1
    await session.flush()


# ----- processing one message -------------------------------------------------------------------


async def _bounce(session: AsyncSession, msg: MailMessage, now: datetime) -> bool:
    found = _ATTEMPT_IN_TEXT.search(f"{msg.body_text}\n{' '.join(msg.headers.values())}")
    if not found:
        return False
    try:
        attempt = await session.get(DispatchAttempt, uuid.UUID(found.group(1)))
    except ValueError:
        return False
    if attempt is None:
        return False
    attempt.status = DispatchStatus.bounced
    attempt.outcome_at = now
    await stages.add_event(session, attempt.application_id, "bounced", "mail", {"message_id": msg.provider_message_id})
    return True


async def process_message(session: AsyncSession, conn: Connection, msg: MailMessage, llm: LLMClient | None,
                          values: dict[str, Any], res: SyncResult, now: datetime) -> None:
    threshold = float(values["mail.auto_link_confidence"])
    thread = await session.scalar(select(MailThread).where(
        MailThread.connection_id == conn.id, MailThread.provider_thread_id == msg.thread_id))
    if thread is not None and msg.provider_message_id in thread.provider_message_ids:
        res.skipped += 1
        return
    own = str(conn.config.get("from_address", "")).lower()
    if msg.sender == own:
        res.skipped += 1  # our own outgoing mail in the read label
        return
    match = await match_message(session, msg, conn.id)
    use_llm = bool(values["mail.llm_classify"]) and match.application is not None
    cls: Classification = await classify(session, llm, msg, use_llm=use_llm,
                                         max_chars=int(values["mail.llm_body_max_chars"]),
                                         phrases=phrases_from(values))
    if cls.bounce:
        await _bounce(session, msg, now)
    if thread is None:
        thread = MailThread(connection_id=conn.id, provider_thread_id=msg.thread_id, provider_message_ids=[],
                            subject=msg.subject or None, classification=MailClassification.other)
        session.add(thread)
        res.new += 1
    thread.provider_message_ids = [*thread.provider_message_ids, msg.provider_message_id]
    thread.sender = msg.sender[:320]
    thread.last_message_at = msg.received_at
    thread.classification = MailClassification(cls.category)
    thread.match_confidence = match.confidence
    confident = match.application is not None and match.confidence >= threshold
    if match.application is not None:
        thread.application_id = match.application.id
    thread.needs_review = cls.needs_review or match.ambiguous or (
        match.application is not None and not confident) or (
        match.application is None and cls.category not in ("other",))
    await session.flush()
    if thread.needs_review:
        res.review += 1
    if confident and not cls.needs_review and match.application is not None:
        res.linked += 1
        await act_on_thread(session, thread, match.application, cls.category, msg.provider_message_id,
                            list(values["mail.auto_apply_classes"]), res)


async def _ignored_senders(session: AsyncSession) -> list[str]:
    rows = await session.scalars(select(Source).where(Source.connector == "alert_email"))
    out: list[str] = []
    for src in rows:
        out.extend(str(s) for s in (src.config or {}).get("senders", []))
    return out


def has_read_target(conn: Connection) -> bool:
    keys = ("read_label", "read_query") if conn.provider.value == "gmail" else ("read_folder",)
    return any(conn.config.get(k) for k in keys)


async def sync_connection(session: AsyncSession, conn: Connection, mailbox: Mailbox, llm: LLMClient | None, *,
                          now: datetime | None = None) -> SyncResult:
    """Read what arrived since the checkpoint and process it. The caller commits."""
    now = now or utcnow()
    values = await settings_service.values(session)
    checkpoint = conn.config.get("checkpoint_at")
    since = datetime.fromisoformat(checkpoint) if checkpoint else now - timedelta(
        days=int(values["mail.initial_lookback_days"]))
    page_size = int(values["mail.max_messages_per_check"])
    res = SyncResult()
    ignore = await _ignored_senders(session)
    newest = since
    seen: set[str] = set()
    cursor = since
    while True:  # a full page means more may be waiting: page forward until a page is not full
        messages = await mailbox.list_messages(cursor, limit=page_size)
        fresh = [m for m in messages if m.provider_message_id not in seen]
        res.fetched += len(fresh)
        for msg in sorted(fresh, key=lambda m: m.received_at):
            seen.add(msg.provider_message_id)
            newest = max(newest, msg.received_at)
            if sender_matches(msg.sender, ignore):
                res.skipped += 1  # job-alert mail belongs to the alert source, not to an application
                continue
            await process_message(session, conn, msg, llm, values, res, now)
        if len(messages) < page_size or not fresh:
            break
        cursor = max(m.received_at for m in messages)
    conn.config = {**conn.config, "checkpoint_at": newest.isoformat(), "last_sync_at": now.isoformat(),
                   "last_error": None}
    conn.health, conn.last_checked_at = "ok", now
    return res


# ----- the periodic check -----------------------------------------------------------------------

MailboxBuilder = Callable[[Connection], Mailbox]


@dataclass
class CheckSummary:
    checked: int = 0
    failed: int = 0
    results: dict[str, SyncResult] = field(default_factory=dict)


async def run_due_checks(sessionmaker: async_sessionmaker[AsyncSession], llm: LLMClient | None, *,
                         builder: MailboxBuilder = mail_connections.build_mailbox,
                         now: datetime | None = None) -> CheckSummary:
    """Check every enabled mailbox whose interval has passed. One failing mailbox never stops the rest."""
    now = now or utcnow()
    summary = CheckSummary()
    async with sessionmaker() as s:
        interval = int(await settings_service.get_value(s, "mail.check_interval_minutes"))
        ids = [c.id for c in await mail_connections.mail_connections(s)]
    for conn_id in ids:
        async with sessionmaker() as s:
            conn = await s.get(Connection, conn_id)
            if conn is None or not conn.enabled or not has_read_target(conn):
                continue
            last = conn.config.get("last_sync_at")
            if last and now - datetime.fromisoformat(last) < timedelta(minutes=interval):
                continue
            try:
                result = await sync_connection(s, conn, builder(conn), llm, now=now)
                summary.results[str(conn_id)] = result
                summary.checked += 1
            except (MailError, OSError, TimeoutError) as exc:
                await s.rollback()
                conn = await s.get(Connection, conn_id)
                assert conn is not None
                conn.health, conn.last_checked_at = "failing", now
                conn.config = {**conn.config, "last_sync_at": now.isoformat(), "last_error": type(exc).__name__}
                summary.failed += 1
                log.warning("mail check failed for connection %s: %s", conn_id, type(exc).__name__)
            await s.commit()
    return summary

