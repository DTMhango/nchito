"""Calendar endpoints: schedule per job, proposals, .ics download, the private feed (token, rotation, detail levels)."""

# ruff: noqa: E501
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.settings import service as settings_service
from app.models.applications import Stage
from app.models.platform import AuditEvent
from tests.calendar.helpers import make_job_app

SECRET_NOTE = "salary ask is 55k, do not mention the other offer"


async def add_event(client, job_id, **over):
    body = {"round_number": 1, "type": "video", "status": "confirmed", "starts_local": "2026-12-03T14:30",
            "ends_local": "2026-12-03T15:30", "timezone": "Europe/London", "location": "Plot 1, Cairo Road",
            "meeting_link": "https://meet.example.com/room", "interviewers": ["Jane Banda"], "notes": SECRET_NOTE,
            **over}
    r = await client.post(f"/api/jobs/{job_id}/events", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def stranger(app):
    """A client with no session cookie: what a calendar app subscribing to the feed looks like."""
    transport = httpx.ASGITransport(app=app, client=("10.0.0.2", 50001))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def feed_path(url: str) -> str:
    return url.removeprefix("http://testserver")


async def test_event_response_carries_both_time_zones(owner_client, session) -> None:
    job, _ = await make_job_app(session)
    ev = await add_event(owner_client, job.id)
    assert ev["starts_at"].startswith("2026-12-03T14:30")  # London in December is UTC
    assert ev["timezone"] == "Europe/London" and ev["starts_local"] == "2026-12-03T14:30"
    assert ev["owner_timezone"] == "Africa/Lusaka" and ev["owner_starts_local"] == "2026-12-03T16:30"
    assert ev["status"] == "confirmed" and ev["source"] == "owner" and ev["needs_input"] is False
    listed = (await owner_client.get(f"/api/jobs/{job.id}/events")).json()
    assert [e["id"] for e in listed] == [ev["id"]]


async def test_events_need_a_signed_in_owner_and_an_application(owner_client, stranger, session) -> None:
    job, _ = await make_job_app(session)
    assert (await stranger.get(f"/api/jobs/{job.id}/events")).status_code == 401
    from tests.tracking.helpers import make_job

    bare = await make_job(session, employer="No App Ltd")
    await session.commit()
    r = await owner_client.post(f"/api/jobs/{bare.id}/events", json={"starts_local": "2026-12-03T10:00", "timezone": "UTC"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_application"


async def test_validation_errors_use_stable_codes(owner_client, session) -> None:
    job, _ = await make_job_app(session)
    r = await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-03-29T01:30", "timezone": "Europe/London"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "nonexistent_time"
    r = await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "tomorrow", "timezone": "UTC"})
    assert r.status_code == 422
    r = await owner_client.post(f"/api/jobs/{job.id}/events", json={"starts_local": "2026-12-03T10:00"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "timezone_required"


async def test_overlap_warning_is_returned_on_both_events(owner_client, session) -> None:
    job1, _ = await make_job_app(session, employer="Acme Ltd")
    job2, _ = await make_job_app(session, employer="Beta Ltd")
    a = await add_event(owner_client, job1.id, timezone="Africa/Lusaka")
    b = await add_event(owner_client, job2.id, timezone="Africa/Lusaka", starts_local="2026-12-03T15:00", ends_local="2026-12-03T16:00")
    again = (await owner_client.get(f"/api/interview-events/{a['id']}")).json()
    assert [c["event_id"] for c in again["conflicts"]] == [b["id"]] and again["conflicts"][0]["employer"] == "Beta Ltd"
    assert [c["event_id"] for c in b["conflicts"]] == [a["id"]]


async def test_proposal_needs_the_owner_to_confirm_and_reschedule_cancel_work(owner_client, session) -> None:
    from app.pipeline import events as svc
    from tests.calendar.helpers import invite

    job, app = await make_job_app(session)
    proposal = await svc.propose_from_message(session, app, invite(body="Options: 3 December 2026 at 10:00 or 4 December 2026 at 11:00"),
                                              values=await settings_service.values(session))
    await session.commit()
    assert proposal is not None
    got = (await owner_client.get(f"/api/jobs/{job.id}/events")).json()[0]
    assert got["status"] == "proposed" and got["needs_input"] is True and len(got["candidates"]) == 2
    no_zone = await owner_client.post(f"/api/interview-events/{proposal.id}/confirm", json={"candidate_index": 0})
    assert no_zone.status_code == 422 and no_zone.json()["detail"]["code"] == "timezone_required"
    ok = await owner_client.post(f"/api/interview-events/{proposal.id}/confirm", json={"candidate_index": 1, "timezone": "Africa/Lusaka"})
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed" and ok.json()["starts_local"] == "2026-12-04T11:00"
    twice = await owner_client.post(f"/api/interview-events/{proposal.id}/confirm", json={"candidate_index": 1, "timezone": "Africa/Lusaka"})
    assert twice.status_code == 409
    moved = await owner_client.post(f"/api/interview-events/{proposal.id}/reschedule", json={"starts_local": "2026-12-05T09:00", "timezone": "Africa/Lusaka"})
    assert moved.status_code == 200 and moved.json()["replaces_id"] == str(proposal.id) and moved.json()["status"] == "confirmed"
    old = (await owner_client.get(f"/api/interview-events/{proposal.id}")).json()
    assert old["status"] == "rescheduled"
    cancelled = await owner_client.post(f"/api/interview-events/{moved.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"


async def test_upcoming_lists_events_within_the_window_and_proposals(owner_client, session) -> None:
    from datetime import timedelta

    from app.core.clock import utcnow

    job, _ = await make_job_app(session)
    soon = (utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    far = (utcnow() + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M")
    near = await add_event(owner_client, job.id, starts_local=soon, ends_local=None, timezone="UTC")
    await add_event(owner_client, job.id, starts_local=far, ends_local=None, timezone="UTC")
    got = (await owner_client.get("/api/interview-events/upcoming")).json()
    assert [e["id"] for e in got] == [near["id"]]
    wide = (await owner_client.get("/api/interview-events/upcoming", params={"days": 90})).json()
    assert len(wide) == 2
    await settings_service.set_value(session, "calendar.upcoming_days", 90, actor="test")
    await session.commit()
    assert len((await owner_client.get("/api/interview-events/upcoming")).json()) == 2


async def test_debrief_endpoint_updates_event_stage_and_sets_followup(owner_client, session) -> None:
    job, _ = await make_job_app(session, stage=Stage.submitted)
    ev = await add_event(owner_client, job.id, timezone="UTC")
    r = await owner_client.post(f"/api/interview-events/{ev['id']}/debrief", json={"outcome": "went_well", "next_step": "waiting", "notes": "Good"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["event"]["status"] == "done" and out["event"]["outcome"] == "went_well"
    assert out["stage_changed_to"] == "interview" and out["follow_up_id"]
    again = await owner_client.post(f"/api/interview-events/{ev['id']}/debrief", json={"outcome": "mixed"})
    assert again.status_code in (200, 409)


async def test_ics_download_has_place_and_link_but_never_the_notes(owner_client, session) -> None:
    job, _ = await make_job_app(session)
    ev = await add_event(owner_client, job.id)
    r = await owner_client.get(f"/api/interview-events/{ev['id']}/ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"] and "acme-ltd" in r.headers["content-disposition"]
    text = r.text
    assert "BEGIN:VEVENT" in text and "DTSTART:20261203T143000Z" in text and "Plot 1\\, Cairo Road" in text
    assert "https://meet.example.com/room" in text and "Jane Banda" in text
    assert SECRET_NOTE not in text and "55k" not in text
    pending = await add_event(owner_client, job.id, status="proposed", starts_local=None, ends_local=None, timezone=None)
    assert (await owner_client.get(f"/api/interview-events/{pending['id']}/ics")).status_code == 409


# ----- the feed -----------------------------------------------------------------------------------------


async def test_feed_default_detail_is_the_employer_only_with_no_notes(owner_client, stranger, session) -> None:
    job, _ = await make_job_app(session, employer="Acme Ltd", title="Senior Data Analyst")
    await add_event(owner_client, job.id)
    state = (await owner_client.get("/api/calendar")).json()
    assert state["feed_url"] is None and state["detail_level"] == "employer"
    url = (await owner_client.post("/api/calendar/feed")).json()["url"]
    assert url.startswith("http://testserver/api/calendar/feed/") and url.endswith(".ics")
    assert (await owner_client.get("/api/calendar")).json()["feed_url"] == url  # the owner can copy it again
    r = await stranger.get(feed_path(url))  # no cookie: the token is the credential
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert "SUMMARY:Interview: Acme Ltd" in text
    for leaked in (SECRET_NOTE, "55k", "Senior Data Analyst", "Cairo Road", "meet.example.com", "Jane Banda"):
        assert leaked not in text


async def test_feed_detail_levels_change_what_is_published_and_notes_never(owner_client, stranger, session) -> None:
    job, _ = await make_job_app(session, employer="Acme Ltd", title="Senior Data Analyst")
    await add_event(owner_client, job.id)
    path = feed_path((await owner_client.post("/api/calendar/feed")).json()["url"])
    await settings_service.set_value(session, "calendar.detail_level", "role", actor="test")
    await session.commit()
    role = (await stranger.get(path)).text
    assert "SUMMARY:Interview: Senior Data Analyst at Acme Ltd" in role and "Cairo Road" not in role
    await settings_service.set_value(session, "calendar.detail_level", "full", actor="test")
    await session.commit()
    full = (await stranger.get(path)).text
    assert "Cairo Road" in full and "meet.example.com/room" in full and "Jane Banda" in full and "Round 1" in full
    assert SECRET_NOTE not in full and "55k" not in full


async def test_feed_rotation_and_revocation_end_the_old_url(owner_client, stranger, session) -> None:
    job, _ = await make_job_app(session)
    await add_event(owner_client, job.id)
    first = (await owner_client.post("/api/calendar/feed")).json()["url"]
    assert (await stranger.get(feed_path(first))).status_code == 200
    second = (await owner_client.post("/api/calendar/feed")).json()["url"]
    assert second != first
    assert (await stranger.get(feed_path(first))).status_code == 404
    assert (await stranger.get(feed_path(second))).status_code == 200
    assert (await owner_client.delete("/api/calendar/feed")).status_code == 204
    assert (await stranger.get(feed_path(second))).status_code == 404
    assert (await owner_client.get("/api/calendar")).json()["feed_url"] is None
    for guess in ("/api/calendar/feed/.ics", "/api/calendar/feed/not-a-token.ics", "/api/calendar/feed/" + "a" * 300 + ".ics"):
        assert (await stranger.get(guess)).status_code == 404
    actions = [e.action for e in await session.scalars(select(AuditEvent).where(AuditEvent.action.like("calendar.feed%")))]
    assert actions.count("calendar.feed_created") == 1 and "calendar.feed_rotated" in actions and "calendar.feed_revoked" in actions


async def test_feed_token_is_stored_hashed_and_encrypted_never_in_the_audit(owner_client, session) -> None:
    from app.models.calendar import CalendarFeed

    url = (await owner_client.post("/api/calendar/feed")).json()["url"]
    token = url.rsplit("/", 1)[1].removesuffix(".ics")
    row = await session.scalar(select(CalendarFeed))
    assert row is not None and token not in (row.token_hash, row.token_enc) and len(row.token_hash) == 64
    details = [str(e.detail) for e in await session.scalars(select(AuditEvent))]
    assert not any(token in d for d in details)


async def test_feed_shows_cancelled_and_rescheduled_as_cancelled_and_never_proposals(owner_client, stranger, session) -> None:
    job, _ = await make_job_app(session)
    keep = await add_event(owner_client, job.id)
    gone = await add_event(owner_client, job.id, starts_local="2026-12-10T10:00", ends_local=None)
    await add_event(owner_client, job.id, status="proposed", starts_local="2026-12-11T10:00", ends_local=None)
    await owner_client.post(f"/api/interview-events/{gone['id']}/cancel")
    path = feed_path((await owner_client.post("/api/calendar/feed")).json()["url"])
    text = (await stranger.get(path)).text
    assert text.count("BEGIN:VEVENT") == 2 and text.count("STATUS:CANCELLED") == 1 and f"{keep['id']}@nchito" in text
    assert "DTSTART:20261211" not in text


async def test_setting_defaults_and_state(owner_client) -> None:
    state = (await owner_client.get("/api/calendar")).json()
    assert state["reminder_offsets_minutes"] == [1440, 60] and state["prep_nudge_minutes"] == 2880
    assert state["google"]["connected"] is False and state["google"]["enabled"] is False
