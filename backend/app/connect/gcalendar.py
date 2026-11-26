"""Google Calendar: write-only mirror of confirmed interviews. DESIGN.md 12, 18.5.

- **Narrowest scope that can do the job.** ``calendar.app.created``: the app may create secondary calendars and
  read and write events on the calendars *it created*, nothing else. (``calendar.events`` alone cannot create a
  calendar, and ``calendar`` would expose all of the owner's calendars.) The app never reads the owner's other
  calendars, so busy and free are not known to it.
- **One dedicated calendar.** The client only ever touches ``calendar_id`` (never ``primary``), and only events whose
  id it derived itself (``event_id_for``): it will not update or delete anything else, even in its own calendar.
- **Idempotent.** An event's Google id is derived from our event id, so a repeat insert is a ``409`` that becomes an
  update; deleting twice is fine.
- Tokens are Fernet-encrypted in the ``Connection`` row (``calendar_records``). Network goes through an injected
  ``HttpTransport``.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlencode

from app.connect.gdrive import AUTH_URL, REFRESH_MARGIN_SECONDS, TOKEN_URL
from app.connect.gdrive import DriveTokens as CalendarTokens
from app.connect.http_transport import HttpResponse, HttpTransport

API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
ID_PREFIX = "nch"
_OWN_ID = re.compile(rf"^{ID_PREFIX}[0-9a-f]{{32}}$")

READS_DESCRIPTION = ("Creates one calendar of its own and writes your confirmed interviews to it. It never reads "
                     "your other calendars or events, so it cannot see when you are busy.")


class CalendarError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def event_id_for(event_id: uuid.UUID) -> str:
    """Google event ids are 5-1024 characters of ``a-v`` and ``0-9``: ours is a prefix plus the id in hex."""
    return f"{ID_PREFIX}{event_id.hex}"


def is_own_id(google_event_id: str) -> bool:
    return bool(_OWN_ID.match(google_event_id or ""))


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
                       "access_type": "offline", "prompt": "consent", "state": state,
                       "include_granted_scopes": "false"})
    return f"{AUTH_URL}?{query}"


async def exchange_code(transport: HttpTransport, *, client_id: str, client_secret: str, redirect_uri: str,
                        code: str, now: Callable[[], float] = time.time) -> CalendarTokens:
    resp = await transport.request("POST", TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"})
    if not resp.ok:
        raise CalendarError("Google refused the authorisation code", resp.status)
    body = resp.json() or {}
    if not body.get("refresh_token"):
        raise CalendarError("Google returned no refresh token; connect again and accept the consent screen")
    if SCOPE not in str(body.get("scope", "")).split():
        raise CalendarError("the Calendar permission was not granted")
    return CalendarTokens(access_token=body["access_token"], refresh_token=body["refresh_token"],
                          expires_at=now() + float(body.get("expires_in", 3600)))


class GoogleCalendarClient:
    def __init__(self, transport: HttpTransport, tokens: CalendarTokens, *, client_id: str, client_secret: str,
                 calendar_id: str | None = None,
                 on_tokens_changed: Callable[[CalendarTokens], Awaitable[None]] | None = None,
                 on_calendar_created: Callable[[str], Awaitable[None]] | None = None,
                 now: Callable[[], float] = time.time) -> None:
        self._http = transport
        self._tokens = tokens
        self._client_id = client_id
        self._client_secret = client_secret
        self.calendar_id = calendar_id
        self._on_tokens = on_tokens_changed
        self._on_created = on_calendar_created
        self._now = now

    # ----- auth and requests --------------------------------------------------------------------

    async def _refresh(self) -> None:
        resp = await self._http.request("POST", TOKEN_URL, data={
            "client_id": self._client_id, "client_secret": self._client_secret,
            "refresh_token": self._tokens.refresh_token, "grant_type": "refresh_token"})
        if not resp.ok:
            raise CalendarError("Calendar access was revoked or expired; reconnect Google Calendar", resp.status)
        body = resp.json() or {}
        self._tokens = CalendarTokens(access_token=body["access_token"], refresh_token=self._tokens.refresh_token,
                                      expires_at=self._now() + float(body.get("expires_in", 3600)))
        if self._on_tokens is not None:
            await self._on_tokens(self._tokens)

    async def _call(self, method: str, url: str, *, json_body: Any = None) -> HttpResponse:
        if self._tokens.expires_at - self._now() < REFRESH_MARGIN_SECONDS:
            await self._refresh()
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._tokens.access_token}"}
            resp = await self._http.request(method, url, headers=headers, json=json_body)
            if resp.status == 401 and attempt == 1:
                await self._refresh()
                continue
            return resp
        raise CalendarError("unreachable")  # pragma: no cover

    def _calendar(self) -> str:
        if not self.calendar_id or self.calendar_id == "primary":
            raise CalendarError("no dedicated calendar: the app never writes to your primary calendar")
        return quote(self.calendar_id, safe="")

    # ----- the dedicated calendar ---------------------------------------------------------------

    async def ensure_calendar(self, name: str, timezone: str) -> str:
        """Use the calendar already recorded, else create one. Returns its id."""
        if self.calendar_id and self.calendar_id != "primary":
            return self.calendar_id
        resp = await self._call("POST", f"{API}/calendars", json_body={"summary": name, "timeZone": timezone})
        if not resp.ok:
            raise CalendarError("Google would not create the calendar", resp.status)
        self.calendar_id = str((resp.json() or {})["id"])
        if self._on_created is not None:
            await self._on_created(self.calendar_id)
        return self.calendar_id

    async def check(self) -> str:
        resp = await self._call("GET", f"{API}/calendars/{self._calendar()}")
        if resp.status == 404:
            raise CalendarError("the app's calendar was deleted in Google; turn Google Calendar off and on again", 404)
        if not resp.ok:
            raise CalendarError("Google Calendar check failed", resp.status)
        return str((resp.json() or {}).get("summary", ""))

    # ----- events (only our own) ----------------------------------------------------------------

    async def upsert(self, event_id: uuid.UUID, body: dict[str, Any]) -> str:
        """Create the event, or update it when it exists. Safe to repeat."""
        google_id = event_id_for(event_id)
        payload = {**body, "id": google_id}
        calendar = self._calendar()
        resp = await self._call("POST", f"{API}/calendars/{calendar}/events", json_body=payload)
        if resp.status == 409:  # already there: this is the update path
            resp = await self._call("PUT", f"{API}/calendars/{calendar}/events/{google_id}", json_body=payload)
        if not resp.ok:
            raise CalendarError("Google would not save the event", resp.status)
        return google_id

    async def remove(self, google_event_id: str) -> None:
        if not is_own_id(google_event_id):
            raise CalendarError("refusing to delete an event this app did not create")
        resp = await self._call("DELETE", f"{API}/calendars/{self._calendar()}/events/{google_event_id}")
        if resp.status not in (200, 204, 404, 410):
            raise CalendarError("Google would not delete the event", resp.status)
