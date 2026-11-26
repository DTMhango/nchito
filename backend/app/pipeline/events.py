"""Interview events: the owner's schedule per application. DESIGN.md 12 (Calendar), 10.3a, 14.

An event is a first-class record (round, type, time with its zone, place or link, interviewers, notes, status,
source). Rules that matter:

- **A proposal is never an event the owner has not seen.** Mail can only create ``proposed`` events (from an
  attached calendar file, wording rules, or an optional model reading the mail as untrusted data). Confirming is
  the owner's act; nothing replies to the employer and nothing is confirmed for the owner.
- **Ambiguity stays a proposal.** No zone, several dates, or a time that happens twice: the options are kept as
  ``candidates`` and ``starts_at`` stays empty until the owner picks.
- **Overlaps warn, they do not block.** Free/busy is never read from the owner's calendar.
- **Reminders** go through the notifier (quiet hours hold them); after an event passes, the owner is asked how it
  went, and the answer moves the application and sets a follow-up.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.apply.stages import IllegalTransition
from app.connect import ics
from app.connect.invite_text import extract_candidates
from app.connect.mailbox import MailMessage
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm.client import BudgetExceeded, LLMClient, LLMError, Message, TextPart
from app.llm.untrusted import data_block
from app.models.applications import (
    Application,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.calendar import InterviewEvent
from app.models.search import Job
from app.schemas.calendar import INACTIVE_STATUSES, EventCandidate

log = logging.getLogger(__name__)

PROPOSAL_KIND = "interview_event_proposal"
UPDATE_KIND = "interview_event_update"
DEBRIEF_KIND = "interview_debrief"
FOLLOW_UP_KIND = "interview_follow_up"
LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
_QUOTED = re.compile(r"^\s*>.*$", re.M)
_LINK_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
MAX_PROPOSALS_PER_MESSAGE = 6


class EventError(Exception):
    """A request the schedule cannot honour. ``code`` is stable; ``reason`` is for the owner."""

    def __init__(self, reason: str, status: int = 409, code: str = "conflict") -> None:
        super().__init__(reason)
        self.reason, self.status, self.code = reason, status, code


@dataclass(frozen=True)
class EventData:
    """Owner-entered fields. Times are wall time in ``timezone`` (``YYYY-MM-DDTHH:MM``)."""

    round_number: int = 1
    type: str = "video"
    starts_local: str | None = None
    ends_local: str | None = None
    timezone: str | None = None
    location: str | None = None
    meeting_link: str | None = None
    interviewers: tuple[str, ...] = ()
    notes: str | None = None


# ----- time -------------------------------------------------------------------------------------


def parse_local(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), LOCAL_FORMAT)
    except ValueError as exc:
        raise EventError("times are written YYYY-MM-DDTHH:MM", 422, "invalid_time") from exc


def zone_of(name: str) -> ZoneInfo:
    zone = ics.zone_for(name)
    if zone is None:
        raise EventError(f"unknown time zone: {name!r}", 422, "invalid_timezone")
    return zone


def to_utc(local: str, zone_name: str) -> datetime:
    """The UTC instant of a wall time. A time that does not exist (clocks jump forward) is refused; one that
    happens twice (clocks go back) is read as the first."""
    zone = zone_of(zone_name)
    instants = ics.resolve_local(parse_local(local), zone)
    if not instants:
        raise EventError("that wall time does not exist in that zone (clocks change that night)", 422,
                         "nonexistent_time")
    return instants[0]


def local_text(instant: datetime | None, zone_name: str | None) -> str | None:
    if instant is None or not zone_name:
        return None
    zone = ics.zone_for(zone_name)
    return instant.astimezone(zone).strftime(LOCAL_FORMAT) if zone else None


def effective_end(event: InterviewEvent, default_minutes: int) -> datetime | None:
    if event.starts_at is None:
        return None
    return event.ends_at or event.starts_at + timedelta(minutes=default_minutes)


async def owner_timezone(session: AsyncSession) -> str:
    return str(await settings_service.get_value(session, "general.timezone"))


# ----- reading ----------------------------------------------------------------------------------


async def get(session: AsyncSession, event_id: uuid.UUID, *, lock: bool = False) -> InterviewEvent:
    event = await session.get(InterviewEvent, event_id, with_for_update=lock)
    if event is None:
        raise EventError("event not found", 404, "not_found")
    return event


async def application_for_job(session: AsyncSession, job_id: uuid.UUID) -> Application | None:
    """The application a job's events belong to: the newest one that is still running, else the newest."""
    rows = list((await session.scalars(select(Application).where(Application.job_id == job_id)
                                       .order_by(Application.created_at.desc()))).all())
    return next((a for a in rows if a.ended_at is None), rows[0] if rows else None)


async def events_for_application(session: AsyncSession, application_id: uuid.UUID) -> list[InterviewEvent]:
    rows = await session.scalars(select(InterviewEvent).where(InterviewEvent.application_id == application_id))
    return sorted(rows.all(), key=lambda e: (e.starts_at is None, e.starts_at or e.created_at, e.created_at))


async def active_events(session: AsyncSession, *, around: tuple[datetime, datetime] | None = None
                        ) -> list[InterviewEvent]:
    stmt = select(InterviewEvent).where(InterviewEvent.status.not_in(INACTIVE_STATUSES),
                                        InterviewEvent.starts_at.is_not(None))
    if around is not None:
        stmt = stmt.where(InterviewEvent.starts_at >= around[0] - timedelta(days=1),
                          InterviewEvent.starts_at <= around[1] + timedelta(days=1))
    return list((await session.scalars(stmt)).all())


def overlapping(event: InterviewEvent, others: Iterable[InterviewEvent], default_minutes: int) -> list[InterviewEvent]:
    """Active events that share time with ``event``. Back-to-back (one ends as the next starts) is not an overlap."""
    end = effective_end(event, default_minutes)
    if event.starts_at is None or end is None or event.status in INACTIVE_STATUSES:
        return []
    out = []
    for other in others:
        if other.id == event.id or other.starts_at is None or other.status in INACTIVE_STATUSES:
            continue
        other_end = effective_end(other, default_minutes)
        if other_end is not None and event.starts_at < other_end and other.starts_at < end:
            out.append(other)
    return sorted(out, key=lambda e: e.starts_at or utcnow())


async def conflicts_for(session: AsyncSession, events: list[InterviewEvent]) -> dict[uuid.UUID, list[InterviewEvent]]:
    default = int(await settings_service.get_value(session, "calendar.default_duration_minutes"))
    timed = [e for e in events if e.starts_at is not None]
    if not timed:
        return {}
    window = (min(e.starts_at for e in timed if e.starts_at), max(e.starts_at for e in timed if e.starts_at))
    pool = await active_events(session, around=window)
    return {e.id: found for e in timed if (found := overlapping(e, pool, default))}


# ----- writing ----------------------------------------------------------------------------------


def _clean_people(names: Iterable[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        cleaned = " ".join(str(name).split())[:120]
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out[:20]


def _check_link(link: str | None) -> str | None:
    if not link:
        return None
    value = link.strip()
    if not re.match(r"^https?://[^\s]+$", value, re.I) or len(value) > ics.MAX_LINK_CHARS:
        raise EventError("the meeting link must be an http or https address", 422, "invalid_link")
    return value


def _apply_times(event: InterviewEvent, data: EventData, *, require_start: bool) -> None:
    if data.starts_local:
        if not data.timezone:
            raise EventError("say which time zone the time is in", 422, "timezone_required")
        event.starts_at = to_utc(data.starts_local, data.timezone)
        event.timezone = zone_of(data.timezone).key
        if data.ends_local:
            event.ends_at = to_utc(data.ends_local, data.timezone)
            if event.ends_at <= event.starts_at:
                raise EventError("the end must be after the start", 422, "invalid_range")
        else:
            event.ends_at = None
    elif require_start:
        raise EventError("a confirmed event needs a start time and time zone", 422, "time_required")


def _fill(event: InterviewEvent, data: EventData) -> None:
    event.round_number = max(1, data.round_number)
    event.type = data.type
    event.location = (data.location or "").strip()[:300] or None
    event.meeting_link = _check_link(data.meeting_link)
    event.interviewers = _clean_people(data.interviewers)
    event.notes = (data.notes or "").strip()[:5000] or None


async def _timeline(session: AsyncSession, event: InterviewEvent, action: str, actor: str,
                    extra: dict[str, Any] | None = None) -> None:
    """The application timeline and the audit trail. Never the private notes."""
    detail = {"event_id": str(event.id), "action": action, "round": event.round_number, "type": event.type,
              "status": event.status, "starts_at": event.starts_at.isoformat() if event.starts_at else None,
              **(extra or {})}
    await stages.add_event(session, event.application_id, "interview_event", actor, detail)
    await audit.record(session, actor=actor, action=f"calendar.event_{action}", subject_type="interview_event",
                       subject_id=event.id, detail=detail)


async def create(session: AsyncSession, app: Application, data: EventData, *, status: str, actor: str
                 ) -> InterviewEvent:
    if status not in ("proposed", "confirmed"):
        raise EventError("an event starts as proposed or confirmed", 422, "invalid_status")
    event = InterviewEvent(application_id=app.id, status=status, source="owner")
    _fill(event, data)
    _apply_times(event, data, require_start=status == "confirmed")
    session.add(event)
    await session.flush()
    await _timeline(session, event, status if status == "confirmed" else "proposed", actor)
    return event


async def update(session: AsyncSession, event: InterviewEvent, data: EventData, *, actor: str) -> InterviewEvent:
    if event.status in INACTIVE_STATUSES or event.status == "done":
        raise EventError(f"a {event.status} event cannot be edited", 409, "not_editable")
    moved = bool(data.starts_local) and (data.starts_local, data.ends_local, data.timezone) != (
        local_text(event.starts_at, event.timezone), local_text(event.ends_at, event.timezone), event.timezone)
    if moved and event.status == "confirmed":
        raise EventError("use reschedule to move a confirmed event", 409, "use_reschedule")
    _fill(event, data)
    if data.starts_local:
        _apply_times(event, data, require_start=False)
        event.candidates = []
    await session.flush()
    await _timeline(session, event, "edited", actor)
    return event


async def _resolve_actions(session: AsyncSession, event: InterviewEvent, kinds: tuple[str, ...], how: str,
                           now: datetime) -> None:
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.application_id == event.application_id, PendingAction.status == PendingStatus.open))
    for action in rows:
        if action.detail.get("kind") in kinds and action.detail.get("event_id") == str(event.id):
            action.status, action.resolved_at, action.resolution = PendingStatus.resolved, now, {"by": how}


async def confirm(session: AsyncSession, event: InterviewEvent, *, actor: str, candidate_index: int | None = None,
                  data: EventData | None = None, now: datetime | None = None) -> InterviewEvent:
    """The owner settles a proposal: pick one of its candidates, or enter the time. Only the owner can."""
    if event.status != "proposed":
        raise EventError(f"only a proposed event can be confirmed (this one is {event.status})", 409, "not_proposed")
    now = now or utcnow()
    if candidate_index is not None:
        if not 0 <= candidate_index < len(event.candidates):
            raise EventError("no such candidate", 422, "no_such_candidate")
        pick = event.candidates[candidate_index]
        zone = (data.timezone if data and data.timezone else None) or pick.timezone
        if not zone:
            raise EventError("the invitation gave no time zone: say which one the time is in", 422,
                             "timezone_required")
        event.starts_at = to_utc(pick.starts_local, zone)
        event.ends_at = to_utc(pick.ends_local, zone) if pick.ends_local else None
        event.timezone = zone_of(zone).key
    elif data is not None and data.starts_local:
        _apply_times(event, data, require_start=True)
    if event.starts_at is None or not event.timezone:
        raise EventError("choose a time (and its time zone) before confirming", 422, "time_required")
    if data is not None:
        _fill(event, data)
    event.status, event.candidates = "confirmed", []
    await _resolve_actions(session, event, (PROPOSAL_KIND,), "confirmed", now)
    await session.flush()
    await _timeline(session, event, "confirmed", actor)
    return event


async def reschedule(session: AsyncSession, event: InterviewEvent, data: EventData, *, actor: str
                     ) -> InterviewEvent:
    """Move an event: the old row becomes ``rescheduled`` (its calendar entry is removed) and a new one takes
    the new time, so the history shows both."""
    if event.status not in ("confirmed", "proposed"):
        raise EventError(f"a {event.status} event cannot be rescheduled", 409, "not_reschedulable")
    if not data.starts_local:
        raise EventError("give the new start time", 422, "time_required")
    fresh = InterviewEvent(
        application_id=event.application_id, round_number=event.round_number, type=event.type,
        status=event.status, source=event.source, location=event.location, meeting_link=event.meeting_link,
        interviewers=list(event.interviewers), notes=event.notes, replaces_id=event.id, ics_uid=event.ics_uid)
    _fill(fresh, EventData(
        round_number=data.round_number or event.round_number, type=data.type or event.type,
        location=data.location if data.location is not None else event.location,
        meeting_link=data.meeting_link if data.meeting_link is not None else event.meeting_link,
        interviewers=data.interviewers or tuple(event.interviewers),
        notes=data.notes if data.notes is not None else event.notes))
    _apply_times(fresh, data, require_start=True)
    event.status = "rescheduled"
    session.add(fresh)
    await session.flush()
    await _resolve_actions(session, event, (PROPOSAL_KIND, UPDATE_KIND), "rescheduled", utcnow())
    await _timeline(session, event, "rescheduled", actor, {"replaced_by": str(fresh.id)})
    await _timeline(session, fresh, "confirmed" if fresh.status == "confirmed" else "proposed", actor,
                    {"replaces": str(event.id)})
    return fresh


async def cancel(session: AsyncSession, event: InterviewEvent, *, actor: str) -> InterviewEvent:
    if event.status in ("cancelled", "rescheduled", "done"):
        raise EventError(f"a {event.status} event cannot be cancelled", 409, "not_cancellable")
    event.status = "cancelled"
    await _resolve_actions(session, event, (PROPOSAL_KIND, UPDATE_KIND, DEBRIEF_KIND), "cancelled", utcnow())
    await session.flush()
    await _timeline(session, event, "cancelled", actor)
    return event


@dataclass
class DebriefResult:
    event: InterviewEvent
    stage_changed_to: str | None
    follow_up_id: uuid.UUID | None


NEXT_STAGE: dict[str, Stage] = {"offer": Stage.offer, "rejected": Stage.rejected, "withdrawn": Stage.withdrawn}


async def debrief(session: AsyncSession, event: InterviewEvent, *, outcome: str, next_step: str, notes: str | None,
                  actor: str, now: datetime | None = None) -> DebriefResult:
    """'How did it go?' The event is done (or cancelled when it never happened), the application moves where the
    owner says, and a follow-up is set when they are waiting or expecting another round."""
    if event.status not in ("confirmed", "done"):
        raise EventError(f"a {event.status} event has nothing to debrief", 409, "not_debriefable")
    now = now or utcnow()
    app = await session.get(Application, event.application_id)
    assert app is not None
    event.outcome = outcome
    event.outcome_detail = {"next_step": next_step, "note": (notes or "").strip()[:2000] or None, "at": now.isoformat()}
    event.status = "cancelled" if outcome == "did_not_happen" else "done"
    changed: str | None = None
    if outcome != "did_not_happen":
        target = NEXT_STAGE.get(next_step) or (Stage.interview if app.stage != Stage.interview else None)
        if target is not None and target != app.stage and stages.check_transition(app, target, "owner").ok:
            try:
                await stages.transition(session, app, target, actor=actor, why=f"interview debrief: {next_step}",
                                        via="owner", now=now, detail={"event_id": str(event.id)})
                changed = target.value
            except IllegalTransition:
                changed = None
    await _resolve_actions(session, event, (DEBRIEF_KIND,), "debrief", now)
    follow_up_id: uuid.UUID | None = None
    if outcome != "did_not_happen" and next_step in ("waiting", "another_round"):
        follow_up_id = await _follow_up(session, event, app, next_step, now)
    await session.flush()
    await _timeline(session, event, "debriefed", actor, {"outcome": outcome, "next_step": next_step,
                                                         "stage": changed})
    return DebriefResult(event, changed, follow_up_id)


async def _follow_up(session: AsyncSession, event: InterviewEvent, app: Application, next_step: str,
                     now: datetime) -> uuid.UUID:
    days = int(await settings_service.get_value(session, "calendar.followup_days"))
    job = await session.get(Job, app.job_id)
    who = f"{job.employer} ({job.title})" if job else "this application"
    title = (f"Follow up with {who}: thank them or ask for news" if next_step == "waiting"
             else f"Next round at {who}: ask for the date and add it to your schedule")
    action = PendingAction(type=PendingActionType.follow_up, application_id=app.id, status=PendingStatus.open,
                           title=title[:300], deadline=now + timedelta(days=days),
                           detail={"kind": FOLLOW_UP_KIND, "event_id": str(event.id), "next_step": next_step})
    session.add(action)
    await session.flush()
    return action.id


# ----- proposals from mail ----------------------------------------------------------------------


class _Slot(BaseModel):
    date: str
    start: str
    end: str | None = None
    timezone: str | None = None


class _Extract(BaseModel):
    """What the model may return: wall times and optional zone names. Nothing here is trusted until validated."""

    slots: list[_Slot] = []


LLM_INSTRUCTIONS = (
    "Find the interview date and time options the employer offers in this email. Return each as a date "
    "(YYYY-MM-DD), a start time (HH:MM, 24 hours), an optional end time and the time zone only if the email names "
    "one (an IANA name such as Africa/Lusaka). Return no slots if there are none. Reply in the JSON format requested.")


def _candidate(start_local: datetime, end_local: datetime | None, zone_name: str | None, label: str
               ) -> list[EventCandidate]:
    """One candidate, or two when the wall time happens twice. With no known zone the instant stays empty."""
    zone = ics.zone_for(zone_name)
    base = {"starts_local": start_local.strftime(LOCAL_FORMAT),
            "ends_local": end_local.strftime(LOCAL_FORMAT) if end_local else None, "label": label}
    if zone is None:
        return [EventCandidate(timezone=None, **base)]
    instants = ics.resolve_local(start_local, zone)
    if not instants:
        return []  # the clocks skip that time: it cannot be right
    out = []
    for instant in instants:
        end = None
        if end_local is not None:
            ends = ics.resolve_local(end_local, zone)
            end = ends[0].isoformat() if ends else None
        out.append(EventCandidate(starts_at=instant.isoformat(), ends_at=end, timezone=zone.key, **base))
    return out


def _from_ics(blobs: Iterable[bytes]) -> tuple[list[ics.IcsEvent], list[EventCandidate]]:
    parsed: list[ics.IcsEvent] = []
    for blob in blobs:
        try:
            parsed.extend(ics.parse_ics(blob))
        except ics.IcsError:
            continue
        if len(parsed) >= ics.MAX_EVENTS:
            break
    cands: list[EventCandidate] = []
    for ev in parsed:
        if ev.start is None or ev.status == "CANCELLED" or ev.method == "CANCEL":
            continue
        end = ev.end
        end_local = end.local if end is not None and end.tzid == ev.start.tzid and end.utc == ev.start.utc else None
        if end_local is None and ev.duration is not None:
            end_local = ev.start.local + ev.duration
        if ev.start.utc:
            cands.append(EventCandidate(
                starts_at=ev.start.local.replace(tzinfo=UTC).isoformat(),
                ends_at=end_local.replace(tzinfo=UTC).isoformat() if end_local else None,
                starts_local=ev.start.local.strftime(LOCAL_FORMAT),
                ends_local=end_local.strftime(LOCAL_FORMAT) if end_local else None, timezone="UTC",
                label=ev.summary[:80]))
            continue
        cands.extend(_candidate(ev.start.local, end_local, ev.start.tzid, ev.summary[:80]))
    return parsed, _dedupe(cands)


def _dedupe(cands: list[EventCandidate]) -> list[EventCandidate]:
    seen: set[tuple[str, str | None, str | None]] = set()
    out = []
    for c in cands:
        key = (c.starts_local, c.timezone, c.starts_at)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:MAX_PROPOSALS_PER_MESSAGE]


def _from_text(msg: MailMessage) -> list[EventCandidate]:
    body = _QUOTED.sub("", msg.body_text or "")
    found = extract_candidates(f"{msg.subject}\n{body}", today=msg.received_at.date())
    cands: list[EventCandidate] = []
    for item in found:
        cands.extend(_candidate(item.start, item.end, item.zone, "from the email"))
    return _dedupe(cands)


async def _from_model(session: AsyncSession, llm: LLMClient, msg: MailMessage, max_chars: int
                      ) -> list[EventCandidate]:
    """Optional. The mail is a DataBlock; the answer is validated like any other input and is only a proposal."""
    text = f"From: {msg.sender}\nSubject: {msg.subject}\n\n{msg.body_text}"[:max_chars]
    messages = [Message("system", [TextPart(LLM_INSTRUCTIONS)]),
                Message("user", [TextPart("Find the interview times."), data_block(text, "email")])]
    try:
        ceiling = await llm.estimate_cost_micros("classify_email", messages, schema=_Extract)
        out, _ = await llm.complete("classify_email", messages, _Extract, max_cost_micros=ceiling)
    except (BudgetExceeded, LLMError):
        return []
    except Exception:
        log.warning("invitation extraction reply unusable")
        return []
    cands: list[EventCandidate] = []
    for slot in out.slots[:MAX_PROPOSALS_PER_MESSAGE]:
        try:
            start = datetime.strptime(f"{slot.date} {slot.start}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{slot.date} {slot.end}", "%Y-%m-%d %H:%M") if slot.end else None
        except ValueError:
            continue
        if end is not None and end <= start:
            end = None
        cands.extend(_candidate(start, end, slot.timezone, "read by the model"))
    return _dedupe(cands)


def _guess_type(subject: str, body: str, link: str | None, location: str) -> str:
    text = f"{subject} {body[:2000]}".lower()
    if re.search(r"\b(assessment|coding test|online test|take-home|aptitude)\b", text):
        return "assessment"
    if link:
        return "video"
    if re.search(r"\b(phone|call|telephone)\b", text):
        return "phone"
    return "onsite" if location else "video"


async def _existing_by_uid(session: AsyncSession, app_id: uuid.UUID, uid: str) -> InterviewEvent | None:
    if not uid:
        return None
    rows = await session.scalars(select(InterviewEvent).where(
        InterviewEvent.application_id == app_id, InterviewEvent.ics_uid == uid).order_by(
        InterviewEvent.created_at.desc()))
    return next((e for e in rows if e.status not in INACTIVE_STATUSES), None)


async def _flag_update(session: AsyncSession, app: Application, event: InterviewEvent, why: str, msg: MailMessage
                       ) -> None:
    """An employer update to something the owner already confirmed: tell them, change nothing."""
    job = await session.get(Job, app.job_id)
    who = f"{job.employer} ({job.title})" if job else "an application"
    session.add(PendingAction(
        type=PendingActionType.follow_up, application_id=app.id, status=PendingStatus.open,
        group_key=f"interview_event:{event.id}", title=f"{who} sent an update to a confirmed interview: {why}"[:300],
        detail={"kind": UPDATE_KIND, "event_id": str(event.id), "message_id": msg.provider_message_id}))
    await session.flush()


async def propose_from_message(session: AsyncSession, app: Application, msg: MailMessage, *,
                               values: dict[str, Any], llm: LLMClient | None = None) -> InterviewEvent | None:
    """Turn an interview invitation into a proposed event. Never confirms, never replies. Returns the proposal,
    or ``None`` when one already exists for this message, the feature is off, or the mail only updates an
    event the owner confirmed (that becomes a pending action)."""
    if not values["calendar.propose_from_mail"]:
        return None
    already = await session.scalar(select(InterviewEvent.id).where(
        InterviewEvent.application_id == app.id, InterviewEvent.source_ref == msg.provider_message_id))
    if already is not None:
        return None
    parsed, candidates = _from_ics(msg.calendars)
    for ev in parsed:
        existing = await _existing_by_uid(session, app.id, ev.uid)
        if existing is None:
            continue
        if ev.method == "CANCEL" or ev.status == "CANCELLED":
            if existing.status == "proposed":
                existing.status = "cancelled"
                await _resolve_actions(session, existing, (PROPOSAL_KIND,), "employer cancelled", utcnow())
            else:
                await _flag_update(session, app, existing, "they cancelled it", msg)
            await _timeline(session, existing, "employer_update", "mail", {"change": "cancelled"})
            return None
        if candidates and not any(c.starts_at == (existing.starts_at.isoformat() if existing.starts_at else None)
                                  for c in candidates):
            if existing.status == "proposed":
                existing.candidates, existing.starts_at, existing.ends_at = candidates, None, None
                if len(candidates) == 1 and candidates[0].starts_at:
                    _adopt(existing, candidates[0])
                existing.source_ref = msg.provider_message_id
                await _timeline(session, existing, "employer_update", "mail", {"change": "time"})
            else:
                await _flag_update(session, app, existing, "they changed the time", msg)
            return None
        return None  # same time again: nothing to add
    if not candidates:
        candidates = _from_text(msg)
    if not candidates and values["calendar.llm_extract"] and llm is not None:
        candidates = await _from_model(session, llm, msg, int(values["mail.llm_body_max_chars"]))
    first = parsed[0] if parsed else None
    link = (first.meeting_link if first else None) or _link_in(msg.body_text)
    location = (first.location if first and not first.location.lower().startswith("http") else "") or ""
    count = len([e for e in await events_for_application(session, app.id) if e.status not in INACTIVE_STATUSES])
    event = InterviewEvent(
        application_id=app.id, status="proposed", source="mail", round_number=count + 1,
        type=_guess_type(msg.subject, msg.body_text, link, location), location=location[:300] or None,
        meeting_link=link, interviewers=_clean_people([first.organizer] if first and first.organizer else []),
        candidates=candidates, source_ref=msg.provider_message_id[:300], ics_uid=(first.uid if first else None) or None)
    if len(candidates) == 1 and candidates[0].starts_at and candidates[0].timezone:
        _adopt(event, candidates[0])
    session.add(event)
    await session.flush()
    job = await session.get(Job, app.job_id)
    who = f"{job.employer} ({job.title})" if job else "this application"
    session.add(PendingAction(
        type=PendingActionType.follow_up, application_id=app.id, status=PendingStatus.open,
        group_key=f"interview_event:{event.id}", title=f"Interview invitation from {who}: confirm the time"[:300],
        detail={"kind": PROPOSAL_KIND, "event_id": str(event.id), "message_id": msg.provider_message_id,
                "ambiguous": event.starts_at is None}))
    await _timeline(session, event, "proposed", "mail", {"candidates": len(candidates),
                                                          "ambiguous": event.starts_at is None})
    return event


def _adopt(event: InterviewEvent, cand: EventCandidate) -> None:
    event.starts_at = datetime.fromisoformat(cand.starts_at) if cand.starts_at else None
    event.ends_at = datetime.fromisoformat(cand.ends_at) if cand.ends_at else None
    event.timezone = cand.timezone


def _link_in(text: str) -> str | None:
    found = _LINK_IN_TEXT.search(_QUOTED.sub("", text or "")[:ics.MAX_VALUE_CHARS * 5])
    if not found:
        return None
    link = found.group(0).rstrip(".,;")
    return link if len(link) <= ics.MAX_LINK_CHARS else None


# ----- the periodic pass: reminders, debrief prompts --------------------------------------------


def humanise(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minutes"


def when_text(event: InterviewEvent, owner_tz: str) -> str:
    """'Thu 3 Dec 14:30 (Africa/Lusaka)' and, if the employer's zone differs, the employer's time too."""
    if event.starts_at is None:
        return "time to be set"
    mine = event.starts_at.astimezone(ics.zone_for(owner_tz) or UTC)
    text = f"{mine.strftime('%a %d %b %H:%M')} ({owner_tz})"
    if event.timezone and event.timezone != owner_tz and (zone := ics.zone_for(event.timezone)) is not None:
        text += f", {event.starts_at.astimezone(zone).strftime('%H:%M')} in {event.timezone}"
    return text


@dataclass
class TickResult:
    reminders: int = 0
    debriefs: int = 0


async def run_due(session: AsyncSession, now: datetime | None = None) -> TickResult:
    """Create the reminder notifications and debrief questions that are due. Safe to run every minute: every
    notification has a key, and a debrief is asked once per event."""
    from app.ops import notifications

    now = now or utcnow()
    values = await settings_service.values(session)
    result = TickResult()
    default = int(values["calendar.default_duration_minutes"])
    owner_tz = str(values["general.timezone"])
    can_notify = bool(values["notifications.channels"]) and "interview_reminder" in values["notifications.events"]
    offsets = sorted(int(o) for o in values["calendar.reminder_offsets_minutes"])
    prep = int(values["calendar.prep_nudge_minutes"])
    delay = timedelta(minutes=int(values["calendar.debrief_delay_minutes"]))
    horizon = max([*offsets, prep, 0])
    rows = (await session.execute(select(InterviewEvent, Application, Job).join(
        Application, Application.id == InterviewEvent.application_id).join(Job, Job.id == Application.job_id).where(
        InterviewEvent.status == "confirmed", InterviewEvent.starts_at.is_not(None)))).all()
    for event, app, job in rows:
        assert event.starts_at is not None
        link = f"/jobs/{job.id}?tab=schedule"
        stamp = int(event.starts_at.timestamp())
        if can_notify and now < event.starts_at <= now + timedelta(minutes=horizon):
            due = [o for o in offsets if event.starts_at - timedelta(minutes=o) <= now]
            if due:  # only the nearest due offset speaks: a late worker sends one reminder, not three
                nearest = min(due)
                body = f"Round {event.round_number}, {event.type}. {when_text(event, owner_tz)}."
                if await notifications.notify(
                        session, kind="interview_reminder", key=f"ivw:{event.id}:{stamp}:{nearest}",
                        title=f"Interview in {humanise(nearest)}: {job.employer}", body=body, link=link,
                        payload={"event_id": str(event.id), "application_id": str(app.id)}):
                    result.reminders += 1
            nudge_due = prep > 0 and event.starts_at - timedelta(minutes=prep) <= now
            if nudge_due and await notifications.notify(
                    session, kind="interview_reminder", key=f"ivw:{event.id}:{stamp}:prep",
                    title=f"Prepare for your interview: {job.employer}",
                    body="Open the interview pack: questions, stories and your pay sheet.",
                    link=f"/jobs/{job.id}?tab=interview",
                    payload={"event_id": str(event.id), "application_id": str(app.id), "nudge": "prep"}):
                result.reminders += 1
        end = effective_end(event, default)
        if end is not None and event.debrief_asked_at is None and end + delay <= now:
            event.debrief_asked_at = now
            session.add(PendingAction(
                type=PendingActionType.follow_up, application_id=app.id, status=PendingStatus.open,
                group_key=f"interview_event:{event.id}",
                title=f"How did your interview with {job.employer} ({job.title}) go?"[:300],
                detail={"kind": DEBRIEF_KIND, "event_id": str(event.id), "job_id": str(job.id)}))
            result.debriefs += 1
    await session.flush()
    return result
