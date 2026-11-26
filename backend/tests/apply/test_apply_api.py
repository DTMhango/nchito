"""Apply endpoints: packet, receipt, approve / reject / request changes, pending actions, trusted sites,
autopilot (invented data only)."""

from __future__ import annotations

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    PendingAction,
    PendingActionType,
)
from app.models.platform import AuditEvent
from tests.apply.helpers import setup_app, setup_campaign

EMAIL = {"channel": "email", "sending_identity": "owner@example.com",
         "email": {"to": ["jobs@acme.example.com"], "subject": "Application", "body": "Dear team"}}


async def _app(**kw):
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s, **kw)
        _job, app = await setup_app(s, campaign, now=utcnow())
        await s.commit()
        return app.id


async def test_build_receipt_approve(owner_client):
    app_id = await _app()
    r = await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)
    assert r.status_code == 200, r.text
    built = r.json()
    assert built["created"] and built["approval"]["status"] == "wait_for_owner" and not built["approval"]["approved"]
    assert built["approval"]["pending_action_id"]
    packet = built["packet"]
    again = (await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)).json()
    assert not again["created"] and again["packet"]["id"] == packet["id"]
    receipt = (await owner_client.get(f"/api/applications/{app_id}/receipt")).json()
    assert receipt["action_label"] == "Send email to jobs@acme.example.com"
    assert all(g["outcome"] in ("pass", "fail", "unknown") for g in receipt["gates"])
    assert all(g["passed"] == (g["outcome"] == "pass") for g in receipt["gates"])
    bad = await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": 1, "packet_hash": "0" * 64, "channel": "email"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "approval_refused"
    ok = await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": packet["version"], "packet_hash": packet["content_hash"], "channel": "email"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["approved_packet_id"] == packet["id"]
    listed = (await owner_client.get(f"/api/applications/{app_id}/packets")).json()
    assert [p["version"] for p in listed] == [1]
    current = (await owner_client.get(f"/api/applications/{app_id}/packet")).json()
    assert current["approved_by"] is not None


async def test_changed_packet_needs_a_new_approval(owner_client):
    app_id = await _app()
    first = (await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)).json()["packet"]
    await owner_client.post(f"/api/applications/{app_id}/approve", json={
        "packet_version": 1, "packet_hash": first["content_hash"], "channel": "email"})
    changed = {**EMAIL, "email": {**EMAIL["email"], "body": "Dear team, updated"}}
    second = (await owner_client.post(f"/api/applications/{app_id}/packet", json=changed)).json()
    assert second["created"] and second["packet"]["version"] == 2
    assert [c["path"] for c in second["changes"]] == ["email.body"]
    detail = (await owner_client.get(f"/api/applications/{app_id}")).json()
    assert detail["approved_packet_id"] is None
    receipt = (await owner_client.get(f"/api/applications/{app_id}/receipt")).json()
    assert receipt["changes_since_last_look"][0]["path"] == "email.body"


async def test_reject_and_request_changes(owner_client):
    app_id = await _app()
    await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)
    r = await owner_client.post(f"/api/applications/{app_id}/request-changes", json={"note": "shorter"})
    assert r.status_code == 200 and r.json()["stage"] == "tailoring"
    assert (await owner_client.get(f"/api/applications/{app_id}/packet")).status_code == 404
    r = await owner_client.post(f"/api/applications/{app_id}/reject", json={"reason": "not for me"})
    assert r.status_code == 200 and r.json()["stage"] == "skipped"
    async with get_sessionmaker()() as s:
        acts = set((await s.scalars(select(AuditEvent.action))).all())
    assert {"application.changes_requested", "application.rejected"} <= acts


async def test_resolve_approval_and_continue(owner_client):
    app_id = await _app()
    built = (await owner_client.post(f"/api/applications/{app_id}/packet", json=EMAIL)).json()
    action_id = built["approval"]["pending_action_id"]
    r = await owner_client.post(f"/api/pending-actions/{action_id}/resolve", json={"resolution": "approved"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"
    async with get_sessionmaker()() as s:
        task = AgentTask(type=AgentTaskType.apply, status=AgentTaskStatus.blocked)
        s.add(task)
        await s.flush()
        actions = [PendingAction(type=PendingActionType.sign_in, title="Sign in", group_key="portal:acme",
                                 agent_task_id=task.id) for _ in range(2)]
        s.add_all(actions)
        await s.commit()
        first, task_id = actions[0].id, task.id
    r = await owner_client.post(f"/api/pending-actions/{first}/resolve", json={"resolution": "continue"})
    assert r.status_code == 200, r.text
    async with get_sessionmaker()() as s:
        assert (await s.get(AgentTask, task_id)).status == AgentTaskStatus.queued
        statuses = (await s.scalars(select(PendingAction.status).where(PendingAction.group_key == "portal:acme")))
        assert {x.value for x in statuses} == {"resolved"}
    wrong = await owner_client.post(f"/api/pending-actions/{first}/resolve", json={"resolution": "chosen"})
    assert wrong.status_code in (409, 422)


async def test_trusted_sites_crud(owner_client):
    r = await owner_client.post("/api/trusted-sites", json={"domain": "greenhouse.io", "system": "greenhouse"})
    assert r.status_code == 201, r.text
    site = r.json()
    assert site["trusted_by"] == "owner"
    assert (await owner_client.post("/api/trusted-sites", json={"domain": "greenhouse.io"})).status_code == 409
    listed = (await owner_client.get("/api/trusted-sites")).json()
    assert [s["domain"] for s in listed["items"]] == ["greenhouse.io"]
    app_id = await _app()
    browser = {"channel": "browser", "sending_identity": "owner@example.com",
               "destination_url": "https://boards.greenhouse.io/acme/jobs/1"}
    packet = (await owner_client.post(f"/api/applications/{app_id}/packet", json=browser)).json()["packet"]
    assert packet["contents"]["destination"]["trusted"] is True
    assert (await owner_client.delete(f"/api/trusted-sites/{site['id']}")).status_code == 204


async def test_autopilot_carries_who_and_why(owner_client):
    r = await owner_client.put("/api/autopilot", json={"paused": True, "reason": "travelling"})
    state = r.json()
    assert state["paused"] and state["paused_by"] and state["reason"] == "travelling" and state["paused_at"]
    state = (await owner_client.put("/api/autopilot", json={"paused": False})).json()
    assert not state["paused"] and state["paused_by"] is None
