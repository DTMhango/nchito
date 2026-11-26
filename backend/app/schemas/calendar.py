"""Shapes and shared Literals for interview events (DESIGN.md 12, wave 4 calendar).

Each Literal is defined once here and imported wherever it is used (the OpenAPI test enforces that).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["phone", "video", "onsite", "assessment"]
EventStatus = Literal["proposed", "confirmed", "done", "cancelled", "rescheduled"]
EventSource = Literal["owner", "mail"]
DetailLevel = Literal["employer", "role", "full"]
DebriefOutcome = Literal["went_well", "mixed", "went_badly", "did_not_happen"]
DebriefNext = Literal["waiting", "another_round", "offer", "rejected", "withdrawn"]

EVENT_TYPES: tuple[str, ...] = ("phone", "video", "onsite", "assessment")
DETAIL_LEVELS: tuple[str, ...] = ("employer", "role", "full")
# A cancelled or rescheduled event no longer occupies time.
INACTIVE_STATUSES = frozenset({"cancelled", "rescheduled"})


class EventCandidate(BaseModel):
    """One possible time found in an invitation. The owner picks one; nothing is chosen for them."""

    starts_at: str | None = Field(default=None, description="UTC ISO instant; null while the zone is unknown")
    ends_at: str | None = None
    starts_local: str = Field(description="Wall time as written, YYYY-MM-DDTHH:MM")
    ends_local: str | None = None
    timezone: str | None = Field(default=None, description="IANA zone; null when the invitation did not say")
    label: str = ""
