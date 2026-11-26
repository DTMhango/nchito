"""Interview events and the calendar feed token (DESIGN.md 12, wave 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity, PydanticJSON
from app.schemas.calendar import EventCandidate


class InterviewEvent(Base, Entity):
    """One interview, assessment or call for an application. Times are stored in UTC with the zone the
    employer used; ``candidates`` holds the options of a proposal the owner has not yet settled."""

    __tablename__ = "interview_event"
    __table_args__ = (
        Index("ix_interview_event_start", "starts_at"),
        Index("ix_interview_event_uid", "application_id", "ics_uid"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"), index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="video")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed")
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="owner")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None] = mapped_column(String(64), doc="IANA zone the employer used")
    location: Mapped[str | None] = mapped_column(String(300))
    meeting_link: Mapped[str | None] = mapped_column(String(2000), doc="Stored as text; never fetched")
    interviewers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    notes: Mapped[str | None] = mapped_column(Text, doc="Private: never leaves in the feed or Google")
    candidates: Mapped[list[EventCandidate]] = mapped_column(PydanticJSON(list[EventCandidate]), nullable=False,
                                                             default=list, server_default="[]")
    source_ref: Mapped[str | None] = mapped_column(String(300), doc="Mail message id a proposal came from")
    ics_uid: Mapped[str | None] = mapped_column(String(300))
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("interview_event.id", ondelete="SET NULL"))
    google_event_id: Mapped[str | None] = mapped_column(String(80))
    google_synced_hash: Mapped[str | None] = mapped_column(String(64))
    google_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_error: Mapped[str | None] = mapped_column(String(300))
    debrief_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(20))
    outcome_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CalendarFeed(Base, Entity):
    """The private subscription feed. Lookup is by hash; the token is kept encrypted so the owner can copy the
    URL again. Rotating revokes the old row and adds a new one."""

    __tablename__ = "calendar_feed"

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
