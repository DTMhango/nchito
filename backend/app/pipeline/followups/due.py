"""The follow-up due list: when a follow-up after no reply falls due, the reminder, snooze and "not needed",
and the automatic follow-up when the owner has switched it on.

A follow-up is due ``followups.due_days[stage]`` days after the last contact (the application going out, the
last message sent, the employer's last message, or the last stage change), at most
``followups.max_per_application`` times per application. A due follow-up opens one ``follow_up`` pending action
(the notifier tells the owner); new contact after it fell due closes it as not needed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.llm.client import LLMClient
from app.models.applications import (
    Application,
    ApplicationEvent,
    DispatchAttempt,
    DispatchStatus,
    MailThread,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.followups import FollowupDue, OutboundMessage
from app.models.search import Job
from app.pipeline.checks.findings import worst
from app.pipeline.followups import drafting, sending

log = logging.getLogger(__name__)

OPEN_DUE = ("due", "snoozed", "drafted")


class DueError(ValueError):
    def __init__(self, message: str, code: str = "not_found", status: int = 404) -> None:
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def stage_days(lines: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in lines:
        stage, _, days = str(line).partition("|")
        out[stage.strip()] = int(days)
    return out


async def last_contact(session: AsyncSession, app: Application) -> datetime | None:
    """The latest of: the application going out, a message sent, the employer's last message, a stage change."""
    stamps: list[datetime] = [t for t in (app.applied_at,) if t is not None]
    sent = await session.scalar(
        select(func.max(DispatchAttempt.outcome_at)).join(OutboundMessage, OutboundMessage.packet_id
                                                          == DispatchAttempt.packet_id)
        .where(DispatchAttempt.application_id == app.id,
               DispatchAttempt.status.in_((DispatchStatus.sent, DispatchStatus.acknowledged))))
    inbound = await session.scalar(select(func.max(MailThread.last_message_at)).where(MailThread.application_id
                                                                                      == app.id))
    moved = await session.scalar(select(func.max(ApplicationEvent.created_at)).where(
        ApplicationEvent.application_id == app.id, ApplicationEvent.kind == "stage_change"))
    stamps += [t for t in (sent, inbound, moved) if t is not None]
    return max(stamps) if stamps else None


@dataclass
class DueItem:
    application_id: uuid.UUID
    job_id: uuid.UUID
    title: str
    employer: str
    stage: str
    sequence: int
    due_at: datetime
    status: str
    row: FollowupDue | None = None
    message_id: uuid.UUID | None = None


async def _rows(session: AsyncSession, app_id: uuid.UUID) -> list[FollowupDue]:
    return list((await session.scalars(select(FollowupDue).where(FollowupDue.application_id == app_id)
                                       .order_by(FollowupDue.sequence))).all())


async def next_due(session: AsyncSession, app: Application, values: dict[str, Any]
                   ) -> tuple[int, datetime] | None:
    """The next follow-up for ``app`` (number, when), or None (stage not followed up, cap reached, not sent)."""
    days = stage_days(values["followups.due_days"]).get(app.stage.value)
    if days is None or app.applied_at is None:
        return None
    rows = await _rows(session, app.id)
    if len(rows) >= int(values["followups.max_per_application"]):
        return None
    last = await last_contact(session, app)
    if last is None:
        return None
    if rows and rows[-1].updated_at is not None and rows[-1].status in ("not_needed", "sent"):
        last = max(last, rows[-1].updated_at)
    return len(rows) + 1, last + timedelta(days=days)


async def _candidates(session: AsyncSession, stages_followed: set[str]) -> list[tuple[Application, Job]]:
    wanted = [Stage(s) for s in stages_followed if s in Stage.__members__]
    return list((await session.execute(select(Application, Job).join(Job, Job.id == Application.job_id).where(
        Application.stage.in_(wanted), Application.applied_at.is_not(None)))).tuples().all())


async def due_list(session: AsyncSession, *, now: datetime | None = None, horizon_days: int = 30) -> list[DueItem]:
    """Open follow-ups (due, snoozed, drafted) and those coming up within ``horizon_days``, soonest first."""
    now = now or utcnow()
    values = await settings_service.values(session)
    items: list[DueItem] = []
    for app, job in await _candidates(session, set(stage_days(values["followups.due_days"]))):
        rows = await _rows(session, app.id)
        open_row = next((r for r in reversed(rows) if r.status in OPEN_DUE), None)
        if open_row is not None:
            items.append(DueItem(app.id, job.id, job.title, job.employer, app.stage.value, open_row.sequence,
                                 open_row.snoozed_until if open_row.status == "snoozed" and open_row.snoozed_until
                                 else open_row.due_at, open_row.status, open_row, open_row.message_id))
            continue
        nxt = await next_due(session, app, values)
        if nxt is not None and nxt[1] <= now + timedelta(days=horizon_days):
            items.append(DueItem(app.id, job.id, job.title, job.employer, app.stage.value, nxt[0], nxt[1],
                                 "upcoming"))
    return sorted(items, key=lambda i: i.due_at)


# Open actions that already ask the owner to follow up with the employer: the follow-up due reminder and the
# calendar's after-interview follow-up are the same thing, so one is never added beside the other. (The
# calendar's debrief question and event proposals are other things and do not count.)
EMPLOYER_FOLLOW_UP_KINDS = ("followup_due", "interview_follow_up")


async def open_employer_follow_up(session: AsyncSession, app_id: uuid.UUID) -> PendingAction | None:
    """The open 'follow up with the employer' action of an application, from either source, or None."""
    rows = (await session.scalars(select(PendingAction).where(
        PendingAction.application_id == app_id, PendingAction.type == PendingActionType.follow_up,
        PendingAction.status == PendingStatus.open).order_by(PendingAction.created_at))).all()
    return next((a for a in rows if (a.detail or {}).get("kind") in EMPLOYER_FOLLOW_UP_KINDS), None)


async def _open_action(session: AsyncSession, app: Application, job: Job, row: FollowupDue) -> PendingAction:
    existing = await open_employer_follow_up(session, app.id)
    if existing is not None:
        return existing
    action = PendingAction(type=PendingActionType.follow_up, application_id=app.id, group_key="follow_up_due",
                           title=f"Follow up with {job.employer} about {job.title}"[:300], status=PendingStatus.open,
                           detail={"kind": "followup_due", "followup_due_id": str(row.id), "sequence": row.sequence,
                                   "stage": row.stage, "due_at": row.due_at.isoformat()})
    session.add(action)
    await session.flush()
    await publish(session, "pending_action.created", {"pending_action_id": str(action.id)})
    return action


async def _close_action(session: AsyncSession, row: FollowupDue, resolution: str, actor: str, now: datetime) -> None:
    action = await session.get(PendingAction, row.pending_action_id) if row.pending_action_id else None
    if action is not None and action.status == PendingStatus.open:
        action.status, action.resolved_at = PendingStatus.resolved, now
        action.resolution = {"resolution": resolution, "by": actor}


async def tick(session: AsyncSession, client: LLMClient | None, *, now: datetime | None = None) -> dict[str, int]:
    """One pass (worker, every few minutes): settle drafted rows whose message went, wake snoozed rows, close
    rows overtaken by new contact, open newly due rows with their reminder, and (when on) the automatic
    follow-up. The caller commits."""
    now = now or utcnow()
    values = await settings_service.values(session)
    report = {"opened": 0, "woken": 0, "closed": 0, "sent": 0, "auto_drafted": 0, "auto_queued": 0}
    from app.apply import winddown

    wd = await winddown.active(session)
    kept = winddown.kept_applications(wd) if wd is not None else None
    for app, job in await _candidates(session, set(stage_days(values["followups.due_days"]))):
        if kept is not None and app.id not in kept:
            continue  # winding down: only applications the owner kept are followed up
        rows = await _rows(session, app.id)
        row = next((r for r in reversed(rows) if r.status in OPEN_DUE), None)
        if row is not None:
            report_key = await _advance(session, app, row, now)
            if report_key:
                report[report_key] += 1
            row = row if row.status in OPEN_DUE else None
        if row is None:
            nxt = await next_due(session, app, values)
            if nxt is None or nxt[1] > now:
                continue
            row = FollowupDue(application_id=app.id, sequence=nxt[0], stage=app.stage.value, due_at=nxt[1],
                              status="due")
            session.add(row)
            await session.flush()
            row.pending_action_id = (await _open_action(session, app, job, row)).id
            await stages.add_event(session, app.id, "follow_up_due", "system",
                                   {"followup_due_id": str(row.id), "sequence": row.sequence})
            report["opened"] += 1
        if values["followups.auto_send"] and client is not None:
            await _automatic(session, client, app, row, now, report)
    await session.flush()
    return report


async def _advance(session: AsyncSession, app: Application, row: FollowupDue, now: datetime) -> str | None:
    if row.status == "drafted" and row.message_id is not None:
        msg = await session.get(OutboundMessage, row.message_id)
        if msg is not None and sending.send_state(await sending.attempts(session, msg)) == "sent":
            row.status = "sent"
            await _close_action(session, row, "sent", "system", now)
            return "sent"
        return None
    if row.status == "snoozed" and row.snoozed_until is not None and row.snoozed_until <= now:
        row.status, row.snoozed_until = "due", None
        action = await session.get(PendingAction, row.pending_action_id) if row.pending_action_id else None
        if action is not None:
            action.snoozed_until = None
        return "woken"
    last = await last_contact(session, app)
    if row.status == "due" and last is not None and last > row.created_at:
        row.status, row.decided_by = "not_needed", "system: new contact after it fell due"
        await _close_action(session, row, "not_needed", "system", now)
        return "closed"
    return None


async def _automatic(session: AsyncSession, client: LLMClient, app: Application, row: FollowupDue, now: datetime,
                     report: dict[str, int]) -> None:
    """The automatic follow-up: draft once per due row, approve only a clean plain follow-up, then queue (the
    gates decide; a refusal for timing is tried again next tick, any other leaves it for the owner)."""
    if row.status == "due" and row.message_id is None:
        if not await _worth_drafting(session, app, now):
            return
        msg = await drafting.create(session, client, app, "follow_up", actor=sending.AUTO_ACTOR,
                                    sequence=row.sequence, automatic=True, now=now)
        row.message_id, row.status = msg.id, "drafted"
        report["auto_drafted"] += 1
        if msg.status != "draft" or worst(msg.check_results) != "pass":
            return  # anything to look at: the owner decides
        try:
            await sending.approve(session, msg, actor=sending.AUTO_ACTOR, now=now)
        except sending.SendError:
            return
    msg = await session.get(OutboundMessage, row.message_id) if row.message_id else None
    if msg is None or not msg.automatic or msg.status != "approved" or await sending.locked(session, msg):
        return
    result = await sending.queue(session, msg, actor=sending.AUTO_ACTOR, now=now)
    if result.status == "queued":
        report["auto_queued"] += 1
        return
    timing = {"quiet_hours", "followup_cap", "global_pause", "campaign_paused"}
    if not {g.get("gate") for g in result.gates if g.get("outcome") != "pass"} <= timing:
        await sending.withdraw_approval(session, msg, actor="system", reason=f"not sent automatically: {result.reason}",
                                        now=now)
        msg.automatic = False
        await audit.record(session, actor="system", action="message.auto_declined", subject_type="application",
                           subject_id=app.id, detail={"message_id": str(msg.id), "reason": result.reason[:500]})


async def _worth_drafting(session: AsyncSession, app: Application, now: datetime) -> bool:
    """Cheap preconditions before spending on a draft that could never go automatically."""
    from app.pipeline.followups import context as ctx_mod

    ctx = await ctx_mod.load(session, app)
    if not ctx.sent_to or ctx.employer_replied or app.stage != Stage.submitted:
        return False
    values = await settings_service.values(session)
    return await sending.automatic_sends_today(session, now) < int(values["followups.auto_daily_cap"])


# ----- owner decisions -----------------------------------------------------------------------------


async def get_row(session: AsyncSession, row_id: uuid.UUID) -> FollowupDue:
    row = await session.get(FollowupDue, row_id, with_for_update=True)
    if row is None:
        raise DueError("follow-up not found")
    return row


async def ensure_row(session: AsyncSession, app: Application, *, now: datetime) -> FollowupDue:
    """The open row for ``app``, opening the next one now if none is open (the owner acts early)."""
    rows = await _rows(session, app.id)
    row = next((r for r in reversed(rows) if r.status in OPEN_DUE), None)
    if row is not None:
        return row
    values = await settings_service.values(session)
    nxt = await next_due(session, app, values)
    if nxt is None:
        raise DueError("no follow-up is due for this application (stage, cap or not sent yet)", "refused", 409)
    row = FollowupDue(application_id=app.id, sequence=nxt[0], stage=app.stage.value, due_at=min(nxt[1], now),
                      status="due")
    session.add(row)
    await session.flush()
    return row


async def snooze(session: AsyncSession, row: FollowupDue, *, actor: str, until: datetime | None = None,
                 now: datetime | None = None) -> FollowupDue:
    now = now or utcnow()
    if row.status not in ("due", "snoozed"):
        raise DueError(f"a {row.status} follow-up cannot be snoozed", "refused", 409)
    days = int(await settings_service.get_value(session, "followups.snooze_days"))
    row.status, row.snoozed_until, row.decided_by = "snoozed", until or now + timedelta(days=days), actor
    action = await session.get(PendingAction, row.pending_action_id) if row.pending_action_id else None
    if action is not None:
        action.snoozed_until = row.snoozed_until
    await audit.record(session, actor=actor, action="follow_up.snoozed", subject_type="application",
                       subject_id=row.application_id, detail={"sequence": row.sequence,
                                                              "until": row.snoozed_until.isoformat()})
    return row


async def not_needed(session: AsyncSession, row: FollowupDue, *, actor: str,
                     now: datetime | None = None) -> FollowupDue:
    now = now or utcnow()
    if row.status not in OPEN_DUE:
        raise DueError(f"this follow-up is already {row.status}", "refused", 409)
    row.status, row.decided_by, row.snoozed_until = "not_needed", actor, None
    await _close_action(session, row, "not_needed", actor, now)
    await audit.record(session, actor=actor, action="follow_up.not_needed", subject_type="application",
                       subject_id=row.application_id, detail={"sequence": row.sequence})
    return row
