"""Refusals on packet build, approval, permit and dispatch carry a stable machine ``code`` beside the words
(app.apply.errors; invented data only)."""

from __future__ import annotations

import uuid

import pytest

from app.apply import approval, errors, packets
from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from tests.apply.helpers import email_draft, setup_app, setup_campaign
from tests.apply.test_dispatch_api import _outside_quiet_hours, channel  # noqa: F401 (fixture)

EMAIL = {"channel": "email", "sending_identity": "owner@example.com",
         "email": {"to": ["jobs@acme.example.com"], "subject": "Application", "body": "Dear team"}}


@pytest.mark.parametrize(("reason", "code"), [
    ("no tailored spec", "no_spec"),
    ("the check of spec v2 is stale: fact F-1 changed", "check_stale"),
    ("the check of spec v2 blocks", "check_blocking"),
    ("CV.pdf is not a document rendered from the checked spec v2", "document_not_rendered"),
])
def test_spec_gate_reasons_map_to_codes(reason, code):
    assert errors.for_spec(reason) == code
    assert errors.for_permit_reason(f"spec_checked: {reason}") == code


@pytest.mark.parametrize(("reason", "code"), [
    ("global_pause: automation paused", "paused"),
    ("quiet_hours: inside quiet hours", "quiet_hours"),
    ("conflict_winner: held: outranked by Lead", "held_by_conflict"),
    ("daily_cap: 5 sent today (cap 5)", "cap_reached"),
    ("excluded: no remote", "excluded"),
    ("effective mode prepare does not let the system apply; use the manual handoff", "mode_not_allowed"),
    ("something new", "refused"),
])
def test_permit_reasons_map_to_codes(reason, code):
    assert errors.for_permit_reason(reason) == code


def test_every_mapped_code_is_a_known_code():
    assert set(errors.GATE_CODES.values()) <= set(errors.CODES)


async def _app(mode: str = "ask_then_apply") -> str:
    async with get_sessionmaker()() as s:
        await _outside_quiet_hours(s)
        campaign = await setup_campaign(s, mode=mode)
        _, app = await setup_app(s, campaign, now=utcnow())
        await s.commit()
        return str(app.id)


async def test_build_without_a_checked_spec_is_no_spec(owner_client):
    app_id = await _app()
    cv = {"name": "cv.pdf", "kind": "cv", "sha256": "a" * 64, "document_id": str(uuid.uuid4())}
    r = await owner_client.post(f"/api/applications/{app_id}/packet", json={**EMAIL, "files": [cv]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_spec", r.text
    assert "no tailored spec" in r.json()["detail"]["reason"]


async def test_invalid_packet_and_superseded_approval(owner_client):
    app_id = await _app()
    r = await owner_client.post(f"/api/applications/{app_id}/packet", json={**EMAIL, "email": None})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_packet"
    built = (await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)).json()["packet"]
    stale = await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": built["version"], "packet_hash": "0" * 64, "channel": "email"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "packet_superseded"
    wrong = await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": built["version"], "packet_hash": built["content_hash"], "channel": "manual"})
    assert wrong.json()["detail"]["code"] == "channel_mismatch"


async def test_mode_that_does_not_let_the_system_apply(owner_client):
    app_id = await _app(mode="prepare")
    built = (await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)).json()["packet"]
    r = await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": built["version"], "packet_hash": built["content_hash"], "channel": "email"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "mode_not_allowed", r.text


async def test_dispatch_refused_while_paused_says_paused(owner_client, channel):  # noqa: F811
    now = utcnow()
    async with get_sessionmaker()() as s:
        await _outside_quiet_hours(s)
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, now=now)
        built = await packets.build(s, app, email_draft(), actor="owner", now=now)
        await approval.approve(s, app, packet_version=1, packet_hash=built.packet.content_hash, channel="email",
                               actor="owner", now=now)
        await s.commit()
    assert (await owner_client.put("/api/autopilot", json={"paused": True})).status_code == 200
    r = await owner_client.post(f"/api/applications/{app.id}/dispatches", json={})
    assert r.status_code == 200 and r.json()["status"] == "denied" and r.json()["code"] == "paused", r.text
    assert (await owner_client.put("/api/autopilot", json={"paused": False})).status_code == 200
    queued = (await owner_client.post(f"/api/applications/{app.id}/dispatches", json={})).json()
    assert queued["status"] == "queued" and queued["code"] is None
    d = queued["dispatch"]["id"]
    assert (await owner_client.post(f"/api/applications/{app.id}/dispatches/{d}/cancel")).status_code == 200
    again = await owner_client.post(f"/api/applications/{app.id}/dispatches/{d}/cancel")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_settled"
