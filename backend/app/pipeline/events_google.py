"""Mirror confirmed events to the owner's dedicated Google calendar, with permission only. DESIGN.md 12.

Off until the owner has connected Google Calendar **and** switched it on. Only confirmed (and done) events are
written; cancelled and rescheduled ones are removed. Each event is written under an id derived from its own id, so
a retry never duplicates and nothing else in the calendar is touched. What is written follows
``calendar.detail_level`` and never includes the private notes. Failures are recorded on the event and retried by
the periodic pass; they never fail the caller.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import calendar_records, gcalendar
from app.connect.http_transport import HttpTransport
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import Application
from app.models.calendar import InterviewEvent
from app.models.search import Job
from app.pipeline import events as events_service
from app.pipeline.events_feed import describe

log = logging.getLogger(__name__)
REMOVED = "removed"
PRESENT = ("confirmed", "done")
GONE = ("cancelled", "rescheduled")


def payload_for(event: InterviewEvent, employer: str, role: str, *, level: str, default_minutes: int,
                owner_timezone: str) -> dict[str, Any]:
    text = describe(event, employer, role, level)
    ends = events_service.effective_end(event, default_minutes)
    assert event.starts_at is not None and ends is not None
    zone = event.timezone or owner_timezone
    body: dict[str, Any] = {
        "summary": text.summary,
        "start": {"dateTime": event.starts_at.isoformat(), "timeZone": zone},
        "end": {"dateTime": ends.isoformat(), "timeZone": zone},
        "extendedProperties": {"private": {"nchito_event": str(event.id)}},
    }
    if text.location:
        body["location"] = text.location
    if text.url:
        body["source"] = {"title": "Meeting link", "url": text.url}
    if text.description:
        body["description"] = text.description
    return body


def _hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


async def _active_client(session: AsyncSession, transport: HttpTransport | None
                         ) -> gcalendar.GoogleCalendarClient | None:
    conn = await calendar_records.first(session, enabled_only=True)
    if conn is None or not conn.config.get("calendar_id"):
        return None
    return calendar_records.client(session, conn, transport=transport)


async def sync_event(session: AsyncSession, event: InterviewEvent, gclient: gcalendar.GoogleCalendarClient,
                     *, values: dict[str, Any]) -> bool:
    """Bring one event's Google copy in line. Returns whether a call was made."""
    if event.status in PRESENT and event.starts_at is not None:
        app = await session.get(Application, event.application_id)
        job = await session.get(Job, app.job_id) if app else None
        body = payload_for(event, job.employer if job else "", job.title if job else "",
                           level=str(values["calendar.detail_level"]),
                           default_minutes=int(values["calendar.default_duration_minutes"]),
                           owner_timezone=str(values["general.timezone"]))
        digest = _hash(body)
        if event.google_synced_hash == digest:
            return False
        try:
            event.google_event_id = await gclient.upsert(event.id, body)
        except gcalendar.CalendarError as exc:
            event.google_error = str(exc)[:300]
            return True
        event.google_synced_hash, event.google_synced_at, event.google_error = digest, utcnow(), None
        return True
    if event.status in GONE and event.google_event_id and event.google_synced_hash != REMOVED:
        try:
            await gclient.remove(event.google_event_id)
        except gcalendar.CalendarError as exc:
            event.google_error = str(exc)[:300]
            return True
        event.google_synced_hash, event.google_synced_at, event.google_error = REMOVED, utcnow(), None
        return True
    return False


async def sync_one(session: AsyncSession, event: InterviewEvent, *, transport: HttpTransport | None = None) -> None:
    """Best effort after a change; never raises."""
    try:
        gclient = await _active_client(session, transport)
        if gclient is not None:
            await sync_event(session, event, gclient, values=await settings_service.values(session))
    except Exception:
        log.warning("google calendar sync failed for event %s", event.id)
        event.google_error = "sync failed"


async def sync_pending(session: AsyncSession, *, transport: HttpTransport | None = None) -> int:
    """The periodic pass: events whose Google copy is missing, stale, or needs removing (retries failures)."""
    try:
        gclient = await _active_client(session, transport)
    except gcalendar.CalendarError:
        return 0
    if gclient is None:
        return 0
    values = await settings_service.values(session)
    rows = await session.scalars(select(InterviewEvent).where(
        or_(InterviewEvent.status.in_(PRESENT),
            (InterviewEvent.status.in_(GONE)) & InterviewEvent.google_event_id.is_not(None))
    ).order_by(InterviewEvent.updated_at.desc()).limit(200))
    calls = 0
    for event in rows:
        try:
            calls += int(await sync_event(session, event, gclient, values=values))
        except Exception:
            log.warning("google calendar sync failed for event %s", event.id)
    return calls
