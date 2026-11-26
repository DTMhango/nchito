"""Interview events and calendar out (DESIGN.md 12, wave 4): the schedule per job, proposals from mail, the
subscription feed, `.ics` downloads, how-did-it-go. Google Calendar connects through the connections router.

Times in requests are wall time in a named zone (``YYYY-MM-DDTHH:MM`` plus ``timezone``) so daylight-saving is
handled in one place (the server). Responses carry the UTC instant and the wall time in the employer's zone and in
the owner's zone.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import ApiModel, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.connect import calendar_records, gcalendar
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.models.applications import Application
from app.models.calendar import InterviewEvent
from app.models.search import Job
from app.pipeline import events as svc
from app.pipeline import events_feed, events_google
from app.schemas.calendar import (
    DebriefNext,
    DebriefOutcome,
    DetailLevel,
    EventCandidate,
    EventSource,
    EventStatus,
    EventType,
)

router = APIRouter(prefix="/api", tags=["calendar"], dependencies=[RequireOwner])
feed_router = APIRouter(prefix="/api/calendar", tags=["calendar"])
ROUTERS = [router, feed_router]

Wall = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", description="Wall time YYYY-MM-DDTHH:MM")]


class EventFields(BaseModel):
    round_number: int = Field(default=1, ge=1, le=20)
    type: EventType = "video"
    location: str | None = Field(default=None, max_length=300)
    meeting_link: str | None = Field(default=None, max_length=2000, description="http(s) only; never fetched")
    interviewers: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=5000, description="Private: never in the feed or Google")


class EventIn(EventFields):
    status: EventStatus = Field(default="confirmed", description="proposed or confirmed")
    starts_local: Wall | None = None
    ends_local: Wall | None = None
    timezone: str | None = Field(default=None, max_length=64, description="IANA zone of the wall times")


class EventUpdate(EventFields):
    starts_local: Wall | None = None
    ends_local: Wall | None = None
    timezone: str | None = Field(default=None, max_length=64)


class ConfirmIn(BaseModel):
    candidate_index: int | None = Field(default=None, ge=0, description="Pick one of the proposal's candidates")
    starts_local: Wall | None = None
    ends_local: Wall | None = None
    timezone: str | None = Field(default=None, max_length=64, description="Needed when the invitation named none")


class RescheduleIn(BaseModel):
    starts_local: Wall
    ends_local: Wall | None = None
    timezone: str = Field(max_length=64)


class DebriefIn(BaseModel):
    outcome: DebriefOutcome
    next_step: DebriefNext = "waiting"
    notes: str | None = Field(default=None, max_length=2000)


class ConflictOut(ApiModel):
    event_id: uuid.UUID
    employer: str
    job_title: str
    starts_at: datetime
    ends_at: datetime | None


class EventOut(Timestamps):
    application_id: uuid.UUID
    job_id: uuid.UUID
    employer: str
    job_title: str
    round_number: int
    type: EventType
    status: EventStatus
    source: EventSource
    starts_at: datetime | None
    ends_at: datetime | None
    timezone: str | None = Field(description="Zone the employer used")
    owner_timezone: str
    starts_local: str | None = Field(description="Wall time in the employer's zone")
    ends_local: str | None
    owner_starts_local: str | None = Field(description="Wall time in the owner's zone")
    owner_ends_local: str | None
    location: str | None
    meeting_link: str | None
    interviewers: list[str]
    notes: str | None
    candidates: list[EventCandidate]
    needs_input: bool = Field(description="A proposal with no settled time (or no zone): the owner must choose")
    conflicts: list[ConflictOut] = Field(description="Other events that overlap this one (a warning, not a block)")
    replaces_id: uuid.UUID | None
    google_synced: bool
    google_error: str | None
    outcome: DebriefOutcome | None
    debrief_due: bool


class DebriefOut(BaseModel):
    event: EventOut
    stage_changed_to: str | None
    follow_up_id: uuid.UUID | None


class GoogleState(BaseModel):
    configured: bool = Field(description="The server has Google sign-in credentials")
    connected: bool
    enabled: bool
    connection_id: uuid.UUID | None
    calendar_ready: bool
    health: str | None
    last_checked_at: datetime | None
    reads_description: str


class CalendarOut(BaseModel):
    feed_url: str | None
    detail_level: DetailLevel
    reminder_offsets_minutes: list[int]
    prep_nudge_minutes: int
    owner_timezone: str
    google: GoogleState


class FeedOut(BaseModel):
    url: str


# ----- helpers ----------------------------------------------------------------------------------


def _error(exc: svc.EventError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "reason": exc.reason})


def _data(body: EventFields, **times: Any) -> svc.EventData:
    return svc.EventData(round_number=body.round_number, type=body.type, location=body.location,
                         meeting_link=body.meeting_link, interviewers=tuple(body.interviewers), notes=body.notes,
                         **times)


async def _outs(session: AsyncSession, events: list[InterviewEvent]) -> list[EventOut]:
    values = await settings_service.values(session)
    owner_tz = str(values["general.timezone"])
    default = int(values["calendar.default_duration_minutes"])
    conflicts = await svc.conflicts_for(session, events)
    jobs: dict[uuid.UUID, tuple[uuid.UUID, str, str]] = {}
    out: list[EventOut] = []
    for ev in events:
        if ev.application_id not in jobs:
            app = await session.get(Application, ev.application_id)
            job = await session.get(Job, app.job_id) if app else None
            jobs[ev.application_id] = (job.id if job else uuid.UUID(int=0), job.employer if job else "",
                                       job.title if job else "")
        job_id, employer, title = jobs[ev.application_id]
        others: list[ConflictOut] = []
        for other in conflicts.get(ev.id, []):
            oapp = await session.get(Application, other.application_id)
            ojob = await session.get(Job, oapp.job_id) if oapp else None
            others.append(ConflictOut(event_id=other.id, employer=ojob.employer if ojob else "",
                                      job_title=ojob.title if ojob else "", starts_at=other.starts_at,  # type: ignore[arg-type]
                                      ends_at=svc.effective_end(other, default)))
        out.append(EventOut(
            id=ev.id, created_at=ev.created_at, updated_at=ev.updated_at, application_id=ev.application_id,
            job_id=job_id, employer=employer, job_title=title, round_number=ev.round_number,
            type=ev.type,  # type: ignore[arg-type]
            status=ev.status, source=ev.source, starts_at=ev.starts_at, ends_at=ev.ends_at,  # type: ignore[arg-type]
            timezone=ev.timezone, owner_timezone=owner_tz, starts_local=svc.local_text(ev.starts_at, ev.timezone),
            ends_local=svc.local_text(ev.ends_at, ev.timezone),
            owner_starts_local=svc.local_text(ev.starts_at, owner_tz),
            owner_ends_local=svc.local_text(ev.ends_at, owner_tz), location=ev.location,
            meeting_link=ev.meeting_link, interviewers=list(ev.interviewers), notes=ev.notes,
            candidates=list(ev.candidates),
            needs_input=ev.status == "proposed" and (ev.starts_at is None or not ev.timezone),
            conflicts=others, replaces_id=ev.replaces_id,
            google_synced=bool(ev.google_synced_hash and ev.google_synced_hash != events_google.REMOVED),
            google_error=ev.google_error, outcome=ev.outcome,  # type: ignore[arg-type]
            debrief_due=ev.status == "confirmed" and ev.debrief_asked_at is not None))
    return out


async def _one(session: AsyncSession, event: InterviewEvent) -> EventOut:
    await session.flush()
    await session.refresh(event)
    return (await _outs(session, [event]))[0]


async def _get(session: AsyncSession, event_id: uuid.UUID, *, lock: bool = False) -> InterviewEvent:
    try:
        return await svc.get(session, event_id, lock=lock)
    except svc.EventError as exc:
        raise _error(exc) from exc


# ----- events -----------------------------------------------------------------------------------


@router.get("/jobs/{job_id}/events", response_model=list[EventOut], name="job_events_list")
async def list_job_events(job_id: uuid.UUID, session: SessionDep) -> list[EventOut]:
    """Every event of the job's applications, earliest first; proposals without a time last."""
    if await session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "reason": "job not found"})
    app = await svc.application_for_job(session, job_id)
    return await _outs(session, await svc.events_for_application(session, app.id) if app else [])


@router.post("/jobs/{job_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED,
             name="job_events_create")
async def create_job_event(job_id: uuid.UUID, body: EventIn, principal: PrincipalDep, session: SessionDep) -> EventOut:
    """Add an event by hand. It belongs to the job's application; a job with no application has no schedule yet."""
    if await session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "reason": "job not found"})
    app = await svc.application_for_job(session, job_id)
    if app is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "no_application", "reason": "start an application for this role before scheduling an interview"})
    try:
        event = await svc.create(session, app, _data(body, starts_local=body.starts_local, ends_local=body.ends_local,
                                                     timezone=body.timezone), status=body.status,
                                 actor=principal.actor)
    except svc.EventError as exc:
        raise _error(exc) from exc
    await events_google.sync_one(session, event)
    return await _one(session, event)


@router.get("/interview-events/upcoming", response_model=list[EventOut], name="interview_events_upcoming")
async def upcoming(session: SessionDep, days: int | None = Query(default=None, ge=1, le=365)) -> list[EventOut]:
    """Confirmed and proposed events from now to the window (setting ``calendar.upcoming_days``), soonest first,
    plus proposals still waiting for a time."""
    window = days or int(await settings_service.get_value(session, "calendar.upcoming_days"))
    default = int(await settings_service.get_value(session, "calendar.default_duration_minutes"))
    now = utcnow()
    horizon = now + timedelta(days=window)
    rows = [e for e in await _all_open(session)
            if (e.starts_at is None) or (e.starts_at <= horizon and (svc.effective_end(e, default) or now) >= now)]
    rows.sort(key=lambda e: (e.starts_at is None, e.starts_at or e.created_at))
    return await _outs(session, rows)


async def _all_open(session: AsyncSession) -> list[InterviewEvent]:
    from sqlalchemy import select

    rows = await session.scalars(select(InterviewEvent).where(InterviewEvent.status.in_(("proposed", "confirmed"))))
    return list(rows.all())


@router.get("/interview-events/{event_id}", response_model=EventOut, name="interview_events_get")
async def get_event(event_id: uuid.UUID, session: SessionDep) -> EventOut:
    return await _one(session, await _get(session, event_id))


@router.put("/interview-events/{event_id}", response_model=EventOut, name="interview_events_update")
async def update_event(event_id: uuid.UUID, body: EventUpdate, principal: PrincipalDep, session: SessionDep
                       ) -> EventOut:
    event = await _get(session, event_id, lock=True)
    try:
        await svc.update(session, event, _data(body, starts_local=body.starts_local, ends_local=body.ends_local,
                                               timezone=body.timezone), actor=principal.actor)
    except svc.EventError as exc:
        raise _error(exc) from exc
    await events_google.sync_one(session, event)
    return await _one(session, event)


@router.post("/interview-events/{event_id}/confirm", response_model=EventOut, name="interview_events_confirm")
async def confirm_event(event_id: uuid.UUID, body: ConfirmIn, principal: PrincipalDep, session: SessionDep
                        ) -> EventOut:
    """The owner settles a proposal (from mail or entered by hand). Pick a candidate or give the time."""
    event = await _get(session, event_id, lock=True)
    data = svc.EventData(round_number=event.round_number, type=event.type, location=event.location,
                         meeting_link=event.meeting_link, interviewers=tuple(event.interviewers), notes=event.notes,
                         starts_local=body.starts_local, ends_local=body.ends_local, timezone=body.timezone)
    try:
        await svc.confirm(session, event, actor=principal.actor, candidate_index=body.candidate_index, data=data)
    except svc.EventError as exc:
        raise _error(exc) from exc
    await events_google.sync_one(session, event)
    return await _one(session, event)


@router.post("/interview-events/{event_id}/reschedule", response_model=EventOut, name="interview_events_reschedule")
async def reschedule_event(event_id: uuid.UUID, body: RescheduleIn, principal: PrincipalDep, session: SessionDep
                           ) -> EventOut:
    """Move an event. Returns the new event; the old one is kept as ``rescheduled``."""
    event = await _get(session, event_id, lock=True)
    try:
        fresh = await svc.reschedule(session, event, svc.EventData(
            round_number=event.round_number, type=event.type, starts_local=body.starts_local,
            ends_local=body.ends_local, timezone=body.timezone), actor=principal.actor)
    except svc.EventError as exc:
        raise _error(exc) from exc
    await events_google.sync_one(session, event)
    await events_google.sync_one(session, fresh)
    return await _one(session, fresh)


@router.post("/interview-events/{event_id}/cancel", response_model=EventOut, name="interview_events_cancel")
async def cancel_event(event_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> EventOut:
    event = await _get(session, event_id, lock=True)
    try:
        await svc.cancel(session, event, actor=principal.actor)
    except svc.EventError as exc:
        raise _error(exc) from exc
    await events_google.sync_one(session, event)
    return await _one(session, event)


@router.post("/interview-events/{event_id}/debrief", response_model=DebriefOut, name="interview_events_debrief")
async def debrief_event(event_id: uuid.UUID, body: DebriefIn, principal: PrincipalDep, session: SessionDep
                        ) -> DebriefOut:
    """'How did it go?': updates the event, moves the application where you say, sets a follow-up."""
    event = await _get(session, event_id, lock=True)
    try:
        result = await svc.debrief(session, event, outcome=body.outcome, next_step=body.next_step, notes=body.notes,
                                   actor=principal.actor)
    except svc.EventError as exc:
        raise _error(exc) from exc
    await events_google.sync_one(session, event)
    return DebriefOut(event=await _one(session, event), stage_changed_to=result.stage_changed_to,
                      follow_up_id=result.follow_up_id)


@router.get("/interview-events/{event_id}/ics", name="interview_events_ics", response_class=Response,
            responses={200: {"content": {"text/calendar": {}}, "description": "One event as an .ics file"}})
async def download_ics(event_id: uuid.UUID, session: SessionDep) -> Response:
    """The event as a calendar file for the owner's own calendar app (place, link and interviewers; no notes)."""
    event = await _get(session, event_id)
    try:
        data = await events_feed.render_one(session, event_id)
    except svc.EventError as exc:
        raise _error(exc) from exc
    app = await session.get(Application, event.application_id)
    job = await session.get(Job, app.job_id) if app else None
    slug = re.sub(r"[^a-z0-9]+", "-", (job.employer if job else "interview").lower()).strip("-")[:40] or "interview"
    return Response(data, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="interview-{slug}.ics"'})


# ----- calendar out -----------------------------------------------------------------------------


async def _state(session: AsyncSession) -> CalendarOut:
    values = await settings_service.values(session)
    cfg = get_config()
    conn = await calendar_records.first(session)
    return CalendarOut(
        feed_url=await events_feed.current_url(session), detail_level=values["calendar.detail_level"],
        reminder_offsets_minutes=sorted(values["calendar.reminder_offsets_minutes"], reverse=True),
        prep_nudge_minutes=int(values["calendar.prep_nudge_minutes"]), owner_timezone=str(values["general.timezone"]),
        google=GoogleState(
            configured=bool(cfg.google_oauth_client_id and cfg.google_oauth_client_secret),
            connected=conn is not None, enabled=bool(conn and conn.enabled), connection_id=conn.id if conn else None,
            calendar_ready=bool(conn and conn.config.get("calendar_id")), health=conn.health if conn else None,
            last_checked_at=conn.last_checked_at if conn else None, reads_description=gcalendar.READS_DESCRIPTION))


@router.get("/calendar", response_model=CalendarOut, name="calendar_get")
async def calendar_state(session: SessionDep) -> CalendarOut:
    """Feed URL, detail level, reminder settings and the Google Calendar state, for Settings > Connections."""
    return await _state(session)


@router.post("/calendar/feed", response_model=FeedOut, name="calendar_feed_rotate")
async def rotate_feed(principal: PrincipalDep, session: SessionDep) -> FeedOut:
    """Create the subscription URL, or replace it: the old URL stops working at once."""
    return FeedOut(url=await events_feed.rotate(session, actor=principal.actor))


@router.delete("/calendar/feed", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               name="calendar_feed_revoke")
async def revoke_feed(principal: PrincipalDep, session: SessionDep) -> None:
    await events_feed.revoke(session, actor=principal.actor)


@feed_router.get("/feed/{token}.ics", name="calendar_feed_get", response_class=Response, include_in_schema=False)
async def feed(token: str, session: SessionDep) -> Response:
    """The private subscription feed. The token is the credential; an unknown or revoked one is a plain 404."""
    found = await events_feed.feed_for_token(session, token)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    found.last_fetched_at = utcnow()
    data = await events_feed.render_feed(session)
    return Response(data, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300", "Referrer-Policy": "no-referrer"})
