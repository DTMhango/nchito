"""The follow-up endpoints end to end (owner session, fake LLM, fake channel)."""

from __future__ import annotations

import pytest

from app.core.clock import utcnow
from app.llm.deps import llm_service
from tests.followups.helpers import PLAIN, llm, reply, sent_app


@pytest.fixture
def fake_llm(app):
    client = llm(PLAIN, reply("Dear hiring team,", "My salary expectation is ZMW 90,000.", "Kind regards,"),
                 PLAIN, PLAIN)
    app.dependency_overrides[llm_service] = lambda: client
    yield client
    app.dependency_overrides.pop(llm_service, None)


async def test_draft_approve_send_and_blocking_checks_over_the_api(owner_client, fake_llm, channel):
    app_id = await sent_app()
    r = await owner_client.post(f"/api/applications/{app_id}/messages", json={"kind": "follow_up"})
    assert r.status_code == 201, r.text
    msg = r.json()
    assert msg["status"] == "draft" and msg["check_status"] == "pass" and msg["send_state"] == "none"
    r = await owner_client.post(f"/api/messages/{msg['id']}/send")
    assert r.json()["status"] == "denied" and r.json()["code"] == "not_approved"
    r = await owner_client.post(f"/api/messages/{msg['id']}/approve")
    assert r.status_code == 200 and r.json()["packet"]["approved_by"] == "owner"
    r = await owner_client.post(f"/api/messages/{msg['id']}/send")
    assert r.json()["status"] == "queued", r.json()
    assert r.json()["message"]["send_state"] == "queued"
    r = await owner_client.post(f"/api/messages/{msg['id']}/cancel")
    assert r.status_code == 200 and r.json()["send_state"] == "cancelled"

    bad = (await owner_client.post(f"/api/applications/{app_id}/messages", json={"kind": "info_reply"})).json()
    assert bad["check_status"] == "block" and bad["questions"]
    r = await owner_client.post(f"/api/messages/{bad['id']}/approve")
    assert r.status_code == 409 and r.json()["detail"]["code"] in ("message_questions", "check_blocking")
    r = await owner_client.put(f"/api/messages/{bad['id']}", json={"body": "Dear hiring team,\n\nThank you.\n\n"
                                                                           "Kind regards,"})
    assert r.json()["check_status"] == "pass" and r.json()["origin"] == "owner"
    r = await owner_client.put(f"/api/messages/{bad['id']}", json={"to": ["new.person@example.com"]})
    assert r.json()["unconfirmed_recipients"] == ["new.person@example.com"] and r.json()["check_status"] == "block"
    r = await owner_client.put(f"/api/messages/{bad['id']}", json={"to": ["new.person@example.com"],
                                                                   "confirm_recipients": True})
    assert r.json()["unconfirmed_recipients"] == [] and r.json()["check_status"] == "pass"

    listed = (await owner_client.get(f"/api/applications/{app_id}/messages")).json()
    assert len(listed["messages"]) == 2 and listed["thread"]["sent_to"] == ["jobs@acme.example.com"]
    assert (await owner_client.get("/api/follow-ups")).status_code == 200


async def test_wind_down_over_the_api(owner_client, fake_llm, channel):
    app_id = await sent_app()
    assert (await owner_client.get("/api/wind-down")).json()["status"] == "none"
    r = await owner_client.post("/api/wind-down", json={"reason": "accepted elsewhere"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["autopilot_paused"]
    key = f"application:{app_id}"
    assert any(i["key"] == key for i in r.json()["live_applications"]["submitted"])
    r = await owner_client.post("/api/wind-down/choices", json={"key": key, "choice": "keep"})
    item = next(i for i in r.json()["live_applications"]["submitted"] if i["key"] == key)
    assert item["choice"] == "keep"
    summary = await owner_client.get("/api/wind-down/summary")
    assert summary.status_code == 200 and "wind-down summary" in summary.text
    r = await owner_client.post("/api/wind-down/reopen")
    assert r.json()["status"] == "reopened" and r.json()["autopilot_paused"]
    assert (await owner_client.post("/api/wind-down/reopen")).json()["detail"]["code"] == "no_winddown"
    assert utcnow()
