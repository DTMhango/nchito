"""Calendar out, always available: per-event ``.ics`` and the private subscription feed. DESIGN.md 12, 14.

- **The feed URL is a secret.** An unguessable token (``secrets.token_urlsafe``), stored hashed for lookup and
  Fernet-encrypted so the owner can copy the URL again. Rotating revokes the old token at once (its URL 404s).
- **What leaves is the owner's choice** (setting ``calendar.detail_level``): ``employer`` is
  "Interview: <employer>" and nothing else; ``role`` adds the role title; ``full`` adds place or link,
  interviewers, round and type. The private notes are never included at any level.
- Only confirmed events (and done ones, so history stays) are published; cancelled and rescheduled events are sent
  as ``CANCELLED`` for the feed window so subscribers drop them; proposals are never published.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import ics
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.crypto import decrypt, encrypt
from app.core.settings import service as settings_service
from app.models.applications import Application
from app.models.calendar import CalendarFeed, InterviewEvent
from app.models.search import Job
from app.pipeline import events as events_service

FEED_PATH = "/api/calendar/feed/{token}.ics"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def feed_url(token: str) -> str:
    return get_config().base_url.rstrip("/") + FEED_PATH.format(token=token)


# ----- the token --------------------------------------------------------------------------------


async def active_feed(session: AsyncSession) -> CalendarFeed | None:
    return await session.scalar(select(CalendarFeed).where(CalendarFeed.revoked_at.is_(None))
                                .order_by(CalendarFeed.created_at.desc()).limit(1))


async def current_url(session: AsyncSession) -> str | None:
    feed = await active_feed(session)
    return feed_url(decrypt(feed.token_enc)) if feed else None


async def rotate(session: AsyncSession, *, actor: str) -> str:
    """Revoke the current token (if any) and issue a new one. Returns the new URL."""
    now = utcnow()
    old = await active_feed(session)
    if old is not None:
        old.revoked_at = now
    token = secrets.token_urlsafe(32)
    session.add(CalendarFeed(token_hash=_hash(token), token_enc=encrypt(token)))
    await session.flush()
    await audit.record(session, actor=actor, action="calendar.feed_rotated" if old else "calendar.feed_created",
                       subject_type="calendar_feed", detail={})
    return feed_url(token)


async def revoke(session: AsyncSession, *, actor: str) -> bool:
    feed = await active_feed(session)
    if feed is None:
        return False
    feed.revoked_at = utcnow()
    await audit.record(session, actor=actor, action="calendar.feed_revoked", subject_type="calendar_feed",
                       detail={})
    return True


async def feed_for_token(session: AsyncSession, token: str) -> CalendarFeed | None:
    if not token or len(token) > 200:
        return None
    return await session.scalar(select(CalendarFeed).where(CalendarFeed.token_hash == _hash(token),
                                                           CalendarFeed.revoked_at.is_(None)))


# ----- what an event says -----------------------------------------------------------------------


@dataclass(frozen=True)
class EventText:
    summary: str
    location: str
    url: str
    description: str


def describe(event: InterviewEvent, employer: str, role: str, level: str) -> EventText:
    """The text of an event at a detail level. Notes are never an input."""
    if level == "employer":
        return EventText(f"Interview: {employer}", "", "", "")
    summary = f"Interview: {role} at {employer}"
    if level == "role":
        return EventText(summary, "", "", "")
    lines = [f"Round {event.round_number}, {event.type}"]
    if event.interviewers:
        lines.append("With: " + ", ".join(event.interviewers))
    return EventText(summary, event.location or "", event.meeting_link or "", "\n".join(lines))


def uid_for(event: InterviewEvent) -> str:
    return f"{event.id}@nchito"


def to_out_event(event: InterviewEvent, employer: str, role: str, level: str, default_minutes: int, *,
                 now: datetime) -> ics.OutEvent | None:
    if event.starts_at is None:
        return None
    text = describe(event, employer, role, level)
    ends = events_service.effective_end(event, default_minutes)
    assert ends is not None
    return ics.OutEvent(uid=uid_for(event), summary=text.summary, starts=event.starts_at, ends=ends,
                        cancelled=event.status in ("cancelled", "rescheduled"), location=text.location,
                        url=text.url, description=text.description,
                        sequence=int(event.updated_at.timestamp()) % 1_000_000 if event.updated_at else 0,
                        modified=event.updated_at or now)


async def _rows(session: AsyncSession, *, since: datetime | None) -> list[tuple[InterviewEvent, str, str]]:
    stmt = (select(InterviewEvent, Job.employer, Job.title)
            .join(Application, Application.id == InterviewEvent.application_id)
            .join(Job, Job.id == Application.job_id)
            .where(InterviewEvent.status.in_(("confirmed", "done", "cancelled", "rescheduled")),
                   InterviewEvent.starts_at.is_not(None)))
    if since is not None:
        stmt = stmt.where(InterviewEvent.starts_at >= since)
    rows = (await session.execute(stmt.order_by(InterviewEvent.starts_at))).all()
    return [(e, employer, role) for e, employer, role in rows]


async def render_feed(session: AsyncSession, *, now: datetime | None = None) -> bytes:
    now = now or utcnow()
    values = await settings_service.values(session)
    level = str(values["calendar.detail_level"])
    default = int(values["calendar.default_duration_minutes"])
    since = now - timedelta(days=int(values["calendar.feed_past_days"]))
    out = [o for e, employer, role in await _rows(session, since=since)
           if (o := to_out_event(e, employer, role, level, default, now=now)) is not None]
    return ics.render_calendar(out, name=str(values["calendar.google_calendar_name"]), now=now)


async def render_one(session: AsyncSession, event_id: uuid.UUID, *, now: datetime | None = None) -> bytes:
    """The owner's own download of one event: full detail (place, link, interviewers), still no notes."""
    now = now or utcnow()
    event = await events_service.get(session, event_id)
    if event.starts_at is None:
        raise events_service.EventError("this event has no time yet", 409, "time_required")
    app = await session.get(Application, event.application_id)
    job = await session.get(Job, app.job_id) if app else None
    default = int(await settings_service.get_value(session, "calendar.default_duration_minutes"))
    out = to_out_event(event, job.employer if job else "", job.title if job else "", "full", default, now=now)
    assert out is not None
    return ics.render_calendar([out], name="Interview", now=now)
