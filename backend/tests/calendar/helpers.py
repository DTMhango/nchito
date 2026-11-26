"""Fakes for the calendar tests: an in-memory Google Calendar, a notifier, and invention helpers (example.com only)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from app.connect.http_transport import HttpResponse
from app.connect.mailbox import MailMessage
from app.models.applications import Application, Stage
from app.models.search import Job
from tests.tracking.helpers import make_app, make_job

NOW = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)  # 10:00 in Lusaka


@dataclass
class Call:
    method: str
    url: str
    json: Any
    data: dict[str, str] | None = None


@dataclass
class FakeGoogleCalendar:
    """Enough of Calendar v3: token endpoint, create calendar, insert (409 on repeat), update, delete."""

    calendars: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    foreign: dict[str, Any] = field(default_factory=dict)  # events the owner made themselves: must never change

    async def request(self, method: str, url: str, *, headers: Any = None, params: Any = None, json: Any = None,
                      content: bytes | None = None, data: Any = None) -> HttpResponse:
        self.calls.append(Call(method, url, json, dict(data) if data else None))
        if url.endswith("/token"):
            return self._reply(200, {"access_token": "access-1", "expires_in": 3600})
        if url.endswith("/calendars") and method == "POST":
            cal_id = f"cal{len(self.calendars) + 1}@group.calendar.example.com"
            self.calendars[cal_id] = {}
            return self._reply(200, {"id": cal_id, "summary": json["summary"]})
        found = re.match(r".*/calendars/([^/]+)(?:/events(?:/([^/]+))?)?$", url)
        assert found, url
        cal_id, event_id = unquote(found.group(1)), found.group(2)
        if cal_id not in self.calendars:
            return self._reply(404, {})
        events = self.calendars[cal_id]
        if event_id is None and url.endswith("/events"):
            if json["id"] in events:
                return self._reply(409, {})
            events[json["id"]] = json
            return self._reply(200, json)
        if event_id is None:
            return self._reply(200, {"id": cal_id, "summary": "Nchito interviews"})
        if method == "PUT":
            if event_id not in events:
                return self._reply(404, {})
            events[event_id] = json
            return self._reply(200, json)
        if method == "DELETE":
            if event_id not in events:
                return self._reply(404, {})
            del events[event_id]
            return self._reply(204, {})
        return self._reply(405, {})

    @staticmethod
    def _reply(status: int, body: Any) -> HttpResponse:
        return HttpResponse(status, json.dumps(body).encode())

    def writes(self) -> list[Call]:
        return [c for c in self.calls if c.method in ("POST", "PUT", "DELETE") and "/events" in c.url]

    @property
    def events(self) -> dict[str, dict[str, Any]]:
        return next(iter(self.calendars.values()), {})


async def make_job_app(session, *, employer: str = "Acme Ltd", title: str = "Data Analyst",
                       stage: Stage = Stage.submitted) -> tuple[Job, Application]:
    job = await make_job(session, title=title, employer=employer)
    app = await make_app(session, job, stage)
    await session.commit()
    return job, app


def invite(*, body: str = "We would like to invite you to an interview.", subject: str = "Interview invitation",
           calendars: tuple[bytes, ...] = (), message_id: str = "m-1", received: datetime = NOW) -> MailMessage:
    return MailMessage(provider_message_id=message_id, thread_id="t-1", sender="hr@acme.example.com",
                       to=["me@example.com"], subject=subject, received_at=received, body_text=body,
                       calendars=calendars)


def ics_invite(*, uid: str = "inv-1@acme.example.com", start: str = "20261203T143000", tzid: str | None =
               "Africa/Lusaka", end: str | None = "20261203T153000", summary: str = "Interview with Acme",
               method: str = "REQUEST", extra: tuple[str, ...] = ()) -> bytes:
    zone = f";TZID={tzid}" if tzid else ""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"METHOD:{method}", "BEGIN:VEVENT", f"UID:{uid}",
             f"DTSTART{zone}:{start}"]
    if end:
        lines.append(f"DTEND{zone}:{end}")
    lines += [f"SUMMARY:{summary}", "ORGANIZER;CN=Jane Banda:mailto:jane@acme.example.com", *extra, "END:VEVENT",
              "END:VCALENDAR"]
    return ("\r\n".join(lines) + "\r\n").encode()
