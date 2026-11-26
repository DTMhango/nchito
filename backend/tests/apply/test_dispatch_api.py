"""Dispatch, handoff, reconcile, restore and pending-action resolution endpoints (invented data only)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.apply import approval, dispatch, packets, resolvers, restore
from app.apply.channels import registry
from app.apply.channels.base import DispatchOutcome
from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from tests.apply.fakes import FakeChannel
from tests.apply.helpers import email_draft, setup_app, setup_campaign


@pytest.fixture
def channel():
    fake = FakeChannel(hasher=registry.packet_hash)

    async def factory(session):
        return fake

    registry.register("email", factory, replace=True)
    yield fake
    registry.unregister("email")


async def _outside_quiet_hours(s) -> None:
    """The API runs on the real clock: put quiet hours well away from now."""
    local = utcnow().astimezone(ZoneInfo("Africa/Lusaka"))
    start, end = local + timedelta(hours=6), local + timedelta(hours=7)
    await settings_service.set_value(s, "automation.quiet_hours_start", start.strftime("%H:%M"), actor="owner")
    await settings_service.set_value(s, "automation.quiet_hours_end", end.strftime("%H:%M"), actor="owner")


async def _approved_app(draft) -> str:
    now = utcnow()
    async with get_sessionmaker()() as s:
        await _outside_quiet_hours(s)
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, now=now)
        built = await packets.build(s, app, draft, actor="owner", now=now)
        await approval.approve(s, app, packet_version=1, packet_hash=built.packet.content_hash,
                               channel=draft.channel, actor="owner", now=now)
        await s.commit()
        return str(app.id)


MANUAL = packets.PacketDraft(channel="manual", destination_url="https://boards.greenhouse.io/acme/jobs/1",
                             sending_identity="owner@example.com",
                             answers=[packets.DraftAnswer(question="Notice period", value="One month")])


async def test_manual_handoff_dispatch_and_mark_submitted(owner_client):
    app_id = await _approved_app(MANUAL)
    kit = await owner_client.get(f"/api/applications/{app_id}/handoff")
    assert kit.status_code == 200, kit.text
    assert kit.json()["answers"] == [{"question": "Notice period", "value": "One month"}]
    created = await owner_client.post(f"/api/applications/{app_id}/dispatches", json={})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "queued" and body["dispatch"]["status"] == "handed_off" and body["dispatch"]["uncertain"]
    done = await owner_client.post(f"/api/applications/{app_id}/mark-submitted", json={"reference": "GH-7"})
    assert done.status_code == 200, done.text
    assert done.json()["stage"] == "submitted"
    listed = (await owner_client.get(f"/api/applications/{app_id}/dispatches")).json()
    assert [d["status"] for d in listed] == ["sent"] and listed[0]["evidence"]["value"] == "GH-7"
    again = await owner_client.post(f"/api/applications/{app_id}/dispatches", json={})
    assert again.json()["status"] == "denied"


async def test_email_dispatch_cancel_during_delay(owner_client, channel):
    app_id = await _approved_app(email_draft())
    created = (await owner_client.post(f"/api/applications/{app_id}/dispatches", json={})).json()
    assert created["status"] == "queued", created
    dispatch_id = created["dispatch"]["id"]
    assert created["dispatch"]["status"] == "reserved" and created["dispatch"]["send_after"]
    cancelled = await owner_client.post(f"/api/applications/{app_id}/dispatches/{dispatch_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    twice = await owner_client.post(f"/api/applications/{app_id}/dispatches/{dispatch_id}/cancel")
    assert twice.status_code == 409
    assert not channel.dispatched


async def test_reconcile_endpoint_and_confirm_resolution(owner_client, channel):
    channel.outcomes = [TimeoutError("timeout")]
    app_id = await _approved_app(email_draft())
    dispatch_id = (await owner_client.post(f"/api/applications/{app_id}/dispatches", json={})).json()["dispatch"]["id"]
    later = utcnow() + timedelta(minutes=11)
    async with get_sessionmaker()() as s:
        await dispatch.run(s, uuid.UUID(dispatch_id), now=later)
    checked = await owner_client.post(f"/api/applications/{app_id}/dispatches/{dispatch_id}/reconcile",
                                      json={"decision": "check"})
    assert checked.status_code == 200 and checked.json()["result"] == "waiting"
    # The owner is asked after the wait; confirming settles it with the reference as evidence.
    async with get_sessionmaker()() as s:
        await dispatch.tick(s, now=later + timedelta(hours=25))
        action = await s.scalar(select(PendingAction).where(
            PendingAction.type == PendingActionType.confirm_submission))
        action_id = action.id
    resolved = await owner_client.post(f"/api/pending-actions/{action_id}/resolve",
                                       json={"resolution": "confirmed", "reference": "ACME-9"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    detail = (await owner_client.get(f"/api/applications/{app_id}")).json()
    assert detail["stage"] == "submitted" and detail["reference"] == "ACME-9"
    not_open = await owner_client.post(f"/api/applications/{app_id}/dispatches/{dispatch_id}/reconcile",
                                       json={"decision": "not_sent"})
    assert not_open.status_code == 409
    assert len(channel.dispatched) == 1


async def test_reconcile_endpoint_not_sent(owner_client, channel):
    channel.outcomes = [TimeoutError("timeout")]
    app_id = await _approved_app(email_draft())
    dispatch_id = (await owner_client.post(f"/api/applications/{app_id}/dispatches", json={})).json()["dispatch"]["id"]
    async with get_sessionmaker()() as s:
        await dispatch.run(s, uuid.UUID(dispatch_id), now=utcnow() + timedelta(minutes=11))
    r = await owner_client.post(f"/api/applications/{app_id}/dispatches/{dispatch_id}/reconcile",
                                json={"decision": "not_sent", "note": "not in my sent items"})
    assert r.status_code == 200 and r.json()["result"] == "not_sent" and r.json()["dispatch"]["status"] == "failed"
    assert (await owner_client.get(f"/api/applications/{app_id}")).json()["stage"] == "ready"


async def test_restore_endpoints(owner_client, channel):
    channel.outcomes = [TimeoutError("timeout")]
    channel.reconciles = [DispatchOutcome(status="failed", error="not in sent items")]
    app_id = await _approved_app(email_draft())
    dispatch_id = (await owner_client.post(f"/api/applications/{app_id}/dispatches", json={})).json()["dispatch"]["id"]
    now = utcnow()
    async with get_sessionmaker()() as s:
        await dispatch.run(s, uuid.UUID(dispatch_id), now=now + timedelta(minutes=11))
        await restore.enter(s, now=now + timedelta(minutes=12))
        await s.commit()
    st = (await owner_client.get("/api/autopilot/restore")).json()
    assert st["active"] and [d["id"] for d in st["outstanding"]] == [dispatch_id]
    refused = await owner_client.post("/api/autopilot/resume-after-restore")
    assert refused.status_code == 409 and refused.json()["detail"]["outstanding"] == [dispatch_id]
    plain = await owner_client.put("/api/autopilot", json={"paused": False})
    assert plain.status_code == 409 and plain.json()["detail"]["code"] == "restore_paused"
    async with get_sessionmaker()() as s:
        await dispatch.tick(s, now=now + timedelta(minutes=13))
    ok = await owner_client.post("/api/autopilot/resume-after-restore")
    assert ok.status_code == 200, ok.text
    assert not (await owner_client.get("/api/autopilot")).json()["paused"]


# ----- proposal resolvers (other streams' kinds) ---------------------------------------------------


async def test_approving_a_registered_proposal_calls_its_resolver(owner_client):
    calls = []

    async def fake_apply(session, action, *, actor):
        calls.append((action.id, actor))

    resolvers.register("mail_stage_proposal", fake_apply)
    try:
        async with get_sessionmaker()() as s:
            action = PendingAction(type=PendingActionType.approve, title="Move to interview?",
                                   detail={"kind": "mail_stage_proposal", "to": "interview"})
            s.add(action)
            await s.commit()
            action_id = action.id
        r = await owner_client.post(f"/api/pending-actions/{action_id}/resolve", json={"resolution": "approved"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "resolved" and calls == [(action_id, "owner")]
    finally:
        resolvers.unregister("mail_stage_proposal")
        resolvers.register_lazy("mail_stage_proposal", "app.connect.mail_sync:apply_proposal")


async def test_a_proposal_whose_module_is_missing_stays_open(owner_client):
    resolvers.register_lazy("absent_kind", "app.connect.not_in_this_build:apply_proposal")
    try:
        async with get_sessionmaker()() as s:
            action = PendingAction(type=PendingActionType.approve, title="?", detail={"kind": "absent_kind"})
            s.add(action)
            await s.commit()
            action_id = action.id
        r = await owner_client.post(f"/api/pending-actions/{action_id}/resolve", json={"resolution": "approved"})
        assert r.status_code == 501
        async with get_sessionmaker()() as s:
            assert (await s.get(PendingAction, action_id)).status == PendingStatus.open
    finally:
        resolvers.unregister("absent_kind")


async def test_channel_registry_registers_by_name_and_shares_the_packet_hash():
    assert "manual" in registry.available() and registry.packet_hash is packets.content_hash
    with pytest.raises(registry.ChannelUnavailable):
        async with get_sessionmaker()() as s:
            await registry.get(s, "browser")


async def test_stage_machine_only_reconciliation_returns_an_unconfirmed_send_to_ready():
    from app.apply import stages

    app = Application(stage=Stage.submitted_unconfirmed)
    assert stages.check_transition(app, Stage.ready, "system").ok
    assert not stages.check_transition(app, Stage.ready, "owner").ok
    assert Stage.ready not in stages.allowed_targets(app)
