"""Google Calendar mirror: with permission only, idempotent, limited to the app's own events, no notes, no reads."""

# ruff: noqa: E501
from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.connect import calendar_records, gcalendar
from app.connect.http_transport import set_transport
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.models.calendar import InterviewEvent
from app.models.platform import AuditEvent, Connection
from app.pipeline import events as svc
from app.pipeline import events_google
from tests.calendar.helpers import FakeGoogleCalendar, make_job_app

SECRET_NOTE = "salary ask is 55k"


@pytest.fixture
def google(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "google_oauth_client_id", "client-id.example.com")
    monkeypatch.setattr(cfg, "google_oauth_client_secret", "client-secret-value")
    fake = FakeGoogleCalendar()
    set_transport(fake)
    yield fake
    set_transport(None)


async def connect(owner_client, google: FakeGoogleCalendar) -> str:
    start = await owner_client.post("/api/connections/oauth/gcalendar/start")
    assert start.status_code == 200, start.text
    query = parse_qs(urlsplit(start.json()["authorize_url"]).query)
    assert query["scope"] == [gcalendar.SCOPE]
    original = google.request

    async def responder(method, url, **kw):
        if url.endswith("/token") and (kw.get("data") or {}).get("grant_type") == "authorization_code":
            from tests.calendar.helpers import FakeGoogleCalendar as F

            return F._reply(200, {"access_token": "access-0", "refresh_token": "refresh-secret", "expires_in": 3600,
                                  "scope": gcalendar.SCOPE})
        return await original(method, url, **kw)

    google.request = responder  # type: ignore[method-assign]
    done = await owner_client.get("/api/connections/oauth/gcalendar/callback", params={"code": "good", "state": query["state"][0]})
    assert done.status_code == 307 and done.headers["location"].endswith("connected=gcalendar")
    google.request = original  # type: ignore[method-assign]
    return (await owner_client.get("/api/calendar")).json()["google"]["connection_id"]


# ----- connecting is a permission, not a side effect ------------------------------------------------------


async def test_oauth_needs_server_credentials(owner_client) -> None:
    assert get_config().google_oauth_client_id is None
    r = await owner_client.post("/api/connections/oauth/gcalendar/start")
    assert r.status_code == 409 and "GOOGLE_OAUTH_CLIENT_ID" in r.json()["detail"]


async def test_connecting_stores_encrypted_tokens_but_stays_off_until_enabled(owner_client, session, google) -> None:
    job, _ = await make_job_app(session)
    conn_id = await connect(owner_client, google)
    state = (await owner_client.get("/api/calendar")).json()["google"]
    assert state["connected"] is True and state["enabled"] is False and state["calendar_ready"] is False
    listed = (await owner_client.get("/api/connections")).json()
    assert [c["provider"] for c in listed] == ["gcalendar"] and listed[0]["scopes_granted"] == [gcalendar.SCOPE]
    assert "refresh-secret" not in json.dumps(listed)
    assert "refresh-secret" not in json.dumps([e.detail for e in await session.scalars(select(AuditEvent))])
    r = await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-03T10:00", "timezone": "UTC"})
    assert r.status_code == 201
    assert google.writes() == [] and google.calendars == {}  # nothing is written, no calendar made, while off
    assert (await owner_client.post("/api/connections", json={"provider": "gcalendar", "label": "x", "secrets": {"k": "v"}})).status_code == 422
    assert conn_id


async def test_enabling_creates_one_dedicated_calendar_and_syncs_existing_events(owner_client, session, google) -> None:
    job, _ = await make_job_app(session)
    await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-03T10:00", "timezone": "Africa/Lusaka", "notes": SECRET_NOTE, "location": "Plot 1"})
    conn_id = await connect(owner_client, google)
    on = await owner_client.put(f"/api/connections/{conn_id}", json={"enabled": True})
    assert on.status_code == 200 and on.json()["enabled"] is True
    assert list(google.calendars) and len(google.calendars) == 1
    assert next(c for c in google.calls if c.method == "POST" and c.url.endswith("/calendars")).json == {"summary": "Nchito interviews", "timeZone": "Africa/Lusaka"}
    assert google.events == {}  # enabling alone writes no events: the periodic pass (or the next change) does
    await events_google.sync_pending(session)
    await session.commit()
    [(gid, body)] = google.events.items()
    assert gid.startswith("nch") and body["summary"] == "Interview: Acme Ltd"
    assert "location" not in body and "description" not in body  # default detail level
    assert SECRET_NOTE not in json.dumps(body)
    off = await owner_client.put(f"/api/connections/{conn_id}", json={"enabled": False})
    assert off.json()["enabled"] is False
    before = len(google.writes())
    await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-04T10:00", "timezone": "UTC"})
    assert len(google.writes()) == before  # off again: no writes
    test = await owner_client.post(f"/api/connections/{conn_id}/test")
    assert test.json()["ok"] is True


# ----- writes: idempotent, own events only ---------------------------------------------------------------


async def enabled(owner_client, session, google):
    conn_id = await connect(owner_client, google)
    await owner_client.put(f"/api/connections/{conn_id}", json={"enabled": True})
    return conn_id


async def test_repeated_sync_makes_no_duplicates_and_no_extra_calls(owner_client, session, google) -> None:
    job, _ = await make_job_app(session)
    await enabled(owner_client, session, google)
    r = await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-03T10:00", "timezone": "UTC"})
    assert r.status_code == 201 and r.json()["google_synced"] is True
    assert len(google.events) == 1 and len(google.writes()) == 1
    for _ in range(3):
        assert await events_google.sync_pending(session) == 0
    assert len(google.writes()) == 1  # unchanged payload: no call at all
    ev = await session.scalar(select(InterviewEvent))
    assert ev is not None
    ev.google_synced_hash = None  # a lost bookkeeping row: the insert collides (409) and becomes an update
    await session.commit()
    assert await events_google.sync_pending(session) == 1
    await session.commit()
    assert len(google.events) == 1


async def test_changes_update_and_cancel_or_reschedule_removes_the_google_copy(owner_client, session, google) -> None:
    job, _ = await make_job_app(session)
    await enabled(owner_client, session, google)
    first = (await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-03T10:00", "timezone": "UTC"})).json()
    await owner_client.put(f"/api/interview-events/{first['id']}", json={"location": "Plot 9", "type": "onsite"})
    assert len(google.events) == 1
    await settings_service.set_value(session, "calendar.detail_level", "full", actor="test")
    await session.commit()
    await owner_client.put(f"/api/interview-events/{first['id']}", json={"location": "Plot 9", "type": "onsite"})
    [(gid, body)] = google.events.items()
    assert body["location"] == "Plot 9" and "Round 1, onsite" in body["description"]
    moved = (await owner_client.post(f"/api/interview-events/{first['id']}/reschedule", json={"starts_local": "2026-12-05T10:00", "timezone": "UTC"})).json()
    assert gid not in google.events and len(google.events) == 1  # old removed, new inserted
    assert next(iter(google.events)) == gcalendar.event_id_for(uuid.UUID(moved["id"]))
    await owner_client.post(f"/api/interview-events/{moved['id']}/cancel")
    assert google.events == {}
    await events_google.sync_pending(session)
    assert google.events == {}  # nothing comes back


async def test_proposals_are_never_written_to_google(owner_client, session, google) -> None:
    job, _app = await make_job_app(session)
    await enabled(owner_client, session, google)
    await owner_client.post(f"/api/jobs/{job.id}/events", json={"status": "proposed", "starts_local": "2026-12-03T10:00", "timezone": "UTC"})
    await events_google.sync_pending(session)
    assert google.events == {}


async def test_client_only_touches_its_own_events_in_its_own_calendar(owner_client, session, google) -> None:
    await enabled(owner_client, session, google)
    conn = await session.scalar(select(Connection))
    assert conn is not None
    client = calendar_records.client(session, conn)
    cal = next(iter(google.calendars))
    google.calendars[cal]["theirs123"] = {"summary": "Dentist"}  # an event the owner made in that calendar
    before = dict(google.calendars[cal])
    with pytest.raises(gcalendar.CalendarError):
        await client.remove("theirs123")
    with pytest.raises(gcalendar.CalendarError):
        await client.remove("nch" + "0" * 31)  # right prefix, wrong shape
    assert google.calendars[cal]["theirs123"] == before["theirs123"]
    assert not [c for c in google.calls if c.method == "DELETE"]
    assert not gcalendar.is_own_id("primary") and gcalendar.is_own_id(gcalendar.event_id_for(uuid.uuid4()))
    # never the primary calendar, never a read of other calendars
    with pytest.raises(gcalendar.CalendarError):
        await gcalendar.GoogleCalendarClient(google, gcalendar.CalendarTokens("a", "r", 1e12), client_id="c", client_secret="s", calendar_id="primary", now=lambda: 0).upsert(uuid.uuid4(), {})
    assert not [c for c in google.calls if c.method == "GET" and "/events" in c.url]
    assert not [c for c in google.calls if "calendarList" in c.url or "freeBusy" in c.url]


async def test_a_failing_google_never_breaks_the_owner_and_is_retried(owner_client, session, google) -> None:
    job, _ = await make_job_app(session)
    await enabled(owner_client, session, google)
    original = google.request

    async def down(method, url, **kw):
        if "/events" in url:
            return FakeGoogleCalendar._reply(500, {})
        return await original(method, url, **kw)

    google.request = down  # type: ignore[method-assign]
    r = await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-03T10:00", "timezone": "UTC"})
    assert r.status_code == 201 and r.json()["google_synced"] is False and r.json()["google_error"]
    google.request = original  # type: ignore[method-assign]
    assert await events_google.sync_pending(session) == 1
    await session.commit()
    ev = await session.scalar(select(InterviewEvent))
    assert ev is not None and ev.google_error is None and ev.google_synced_hash and len(google.events) == 1


async def test_payload_follows_the_detail_level_and_never_includes_notes(session) -> None:
    _, app = await make_job_app(session, employer="Acme Ltd", title="Analyst")
    ev = await svc.create(session, app, svc.EventData(starts_local="2026-12-03T10:00", timezone="Africa/Lusaka", notes=SECRET_NOTE,
                                                      location="Plot 1", meeting_link="https://meet.example.com/x", interviewers=("Jane",)),
                          status="confirmed", actor="owner")
    kwargs = {"default_minutes": 60, "owner_timezone": "Africa/Lusaka"}
    employer = events_google.payload_for(ev, "Acme Ltd", "Analyst", level="employer", **kwargs)
    role = events_google.payload_for(ev, "Acme Ltd", "Analyst", level="role", **kwargs)
    full = events_google.payload_for(ev, "Acme Ltd", "Analyst", level="full", **kwargs)
    assert employer["summary"] == "Interview: Acme Ltd" and set(employer) == {"summary", "start", "end", "extendedProperties"}
    assert role["summary"] == "Interview: Analyst at Acme Ltd" and "location" not in role
    assert full["location"] == "Plot 1" and full["source"]["url"] == "https://meet.example.com/x"
    assert SECRET_NOTE not in json.dumps([employer, role, full])
    assert employer["start"] == {"dateTime": "2026-12-03T08:00:00+00:00", "timeZone": "Africa/Lusaka"}
