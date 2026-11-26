"""One-application waivers of 'block, waivable once' guardrails."""

from __future__ import annotations

from sqlalchemy import select

from app.models.applications import Application
from app.models.platform import AuditEvent
from app.models.search import Job


async def make_app(session) -> Application:
    job = Job(title="Analyst", employer="Example Co", canonical_employer="Example Co", content_hash="h")
    session.add(job)
    await session.flush()
    app = Application(job_id=job.id)
    session.add(app)
    await session.flush()
    await session.commit()
    return app


async def make_rule(client, name, strictness):
    r = await client.post("/api/kit/guardrails", json={
        "name": name, "severity": "block", "strictness": strictness,
        "params": {"type": "never_mention", "terms": ["synergy"]}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_waiver_lets_one_application_through_and_is_audited(owner_client, session):
    app, other = await make_app(session), await make_app(session)
    rule = await make_rule(owner_client, "No jargon", "block_waivable_once")
    check = {"texts": {"cv": "Great synergy"}}
    assert (await owner_client.post("/api/kit/guardrails/check", json=check)).json()["blocked"] is True

    r = await owner_client.post(f"/api/kit/guardrails/{rule}/waivers",
                                json={"application_id": str(app.id), "reason": "the posting uses the word itself"})
    assert r.status_code == 201 and r.json()["waived_by"] == "owner"
    dup = await owner_client.post(f"/api/kit/guardrails/{rule}/waivers",
                                  json={"application_id": str(app.id), "reason": "again"})
    assert dup.status_code == 409

    mine = (await owner_client.post("/api/kit/guardrails/check", json={**check, "application_id": str(app.id)})).json()
    assert mine["blocked"] is False and mine["results"][0]["waived"] is True
    # another application, and a check with no application, are still blocked: it is one application only
    theirs = {**check, "application_id": str(other.id)}
    assert (await owner_client.post("/api/kit/guardrails/check", json=theirs)).json()["blocked"] is True
    assert (await owner_client.post("/api/kit/guardrails/check", json=check)).json()["blocked"] is True

    listed = (await owner_client.get("/api/kit/guardrail-waivers", params={"application_id": str(app.id)})).json()
    assert len(listed) == 1 and listed[0]["reason"] == "the posting uses the word itself"
    event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "kit.guardrail.waived"))
    assert event.detail["reason"] == "the posting uses the word itself"

    assert (await owner_client.delete(f"/api/kit/guardrail-waivers/{listed[0]['id']}")).status_code == 204
    again = {**check, "application_id": str(app.id)}
    assert (await owner_client.post("/api/kit/guardrails/check", json=again)).json()["blocked"] is True


async def test_always_block_and_advise_rules_cannot_be_waived_and_a_reason_is_required(owner_client, session):
    app = await make_app(session)
    hard = await make_rule(owner_client, "Never", "always_block")
    soft = await make_rule(owner_client, "Advice", "advise")
    for rule in (hard, soft):
        r = await owner_client.post(f"/api/kit/guardrails/{rule}/waivers",
                                    json={"application_id": str(app.id), "reason": "please"})
        assert r.status_code == 409, r.text
    assert (await owner_client.get("/api/kit/guardrail-waivers")).json() == []
    waivable = await make_rule(owner_client, "Waivable", "block_waivable_once")
    blank = await owner_client.post(f"/api/kit/guardrails/{waivable}/waivers",
                                    json={"application_id": str(app.id), "reason": "   "})
    assert blank.status_code == 422
    missing = await owner_client.post(
        f"/api/kit/guardrails/{waivable}/waivers",
        json={"application_id": "00000000-0000-4000-8000-000000000001", "reason": "x"})
    assert missing.status_code == 404
    # a waiver on an always-block rule has no effect on the check either
    r = await owner_client.post("/api/kit/guardrails/check",
                                json={"texts": {"cv": "synergy"}, "application_id": str(app.id)})
    assert r.json()["blocked"] is True
