"""Feedback, suggestions and policy-preview endpoints."""

from __future__ import annotations

from app.core.db import get_sessionmaker
from tests.pipeline.preferences.data import seed_feedback


async def _seed():
    async with get_sessionmaker()() as s:
        data = await seed_feedback(s)
        await s.commit()
        return data


async def test_feedback_put_get_withdraw(owner_client):
    data = await _seed()
    job_id = data.jobs["G"].id
    r = await owner_client.put(f"/api/jobs/{job_id}/feedback",
                               json={"verdict": "up", "reasons": ["more_like_this"], "note": "  Good fit  "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campaign_id"] == str(data.campaign.id) and body["score_at"] == 66 and body["note"] == "Good fit"
    r = await owner_client.put(f"/api/jobs/{job_id}/feedback", json={"verdict": "down", "reasons": ["pay"]})
    assert r.json()["id"] == body["id"] and r.json()["verdict"] == "down"
    got = (await owner_client.get(f"/api/jobs/{job_id}/feedback")).json()
    assert len(got) == 1 and got[0]["reasons"] == ["pay"]
    listed = (await owner_client.get("/api/preferences/feedback",
                                     params={"campaign_id": str(data.campaign.id), "verdict": "down"})).json()
    assert listed["total"] == 7 and {i["job_title"] for i in listed["items"]} >= {"Role G"}
    assert (await owner_client.put(f"/api/jobs/{job_id}/feedback",
                                   json={"verdict": "sideways"})).status_code == 422
    assert (await owner_client.put(f"/api/jobs/{job_id}/feedback",
                                   json={"verdict": "up", "note": "x" * 501})).status_code == 422
    r = await owner_client.delete(f"/api/jobs/{job_id}/feedback", params={"campaign_id": str(data.campaign.id)})
    assert r.status_code == 204
    assert (await owner_client.get(f"/api/jobs/{job_id}/feedback")).json() == []


async def test_analyse_list_accept_dismiss(owner_client):
    data = await _seed()
    cid = str(data.campaign.id)
    summary = (await owner_client.get("/api/preferences/summary", params={"campaign_id": cid})).json()
    assert (summary["up"], summary["down"], summary["open_suggestions"]) == (4, 6, 0)
    assert summary["owner_only"][0]["area"] == "seniority" and summary["last_analysed_at"] is None
    r = await owner_client.post("/api/preferences/analyse", json={"campaign_id": cid})
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert len(created) == 8
    listed = (await owner_client.get("/api/preferences/suggestions", params={"campaign_id": cid})).json()
    assert listed["total"] == 8
    penalty = next(s for s in created if s["kind"] == "add_penalty")
    assert penalty["backtest"]["newly_drop"][0]["title"] == "Role G"

    edited = {**penalty["change"], "points": 20}
    bt = (await owner_client.post(f"/api/preferences/suggestions/{penalty['id']}/backtest",
                                  json={"change": edited})).json()
    assert bt["newly_drop"][0]["new_score"] == 46
    forbidden = {**penalty["change"], "conditions": {"root": {"conditions": [
        {"type": "values", "facet": "facets.visa_sponsorship", "include": ["no"]}]}}}
    r = await owner_client.post(f"/api/preferences/suggestions/{penalty['id']}/accept", json={"change": forbidden})
    assert r.status_code == 422 and "owner-only" in r.json()["detail"]
    r = await owner_client.post(f"/api/preferences/suggestions/{penalty['id']}/accept",
                                json={"change": edited, "note": "harsher"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted" and r.json()["result"]["rubric_version"] == 2
    assert r.json()["change"]["points"] == 20
    r = await owner_client.post(f"/api/preferences/suggestions/{penalty['id']}/accept", json={})
    assert r.status_code == 409

    view = next(s for s in created if s["kind"] == "add_saved_view")
    r = await owner_client.post(f"/api/preferences/suggestions/{view['id']}/dismiss", json={"note": "no"})
    assert r.json()["status"] == "dismissed"
    again = (await owner_client.post("/api/preferences/analyse", json={"campaign_id": cid})).json()
    assert {s["kind"] for s in again["created"]} <= {"reweight_criterion"}  # only the rubric moved on
    assert view["id"] not in {s["id"] for s in again["created"]}


async def test_policy_preview_endpoint(owner_client):
    data = await _seed()
    cid = str(data.campaign.id)
    r = await owner_client.post(f"/api/campaigns/{cid}/policy-preview", json={"days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["jobs"] == 11 and body["thresholds"] == {"shortlist": 60, "tailor": 70, "auto_apply": 85}
    assert len(body["histogram"]) == 20 and sum(b["count"] for b in body["histogram"]) == 11
    assert body["unknowns"][0]["gate"] == "pay_stated" and body["unknowns"][0]["count"] == 11
    assert body["line"]["would_apply"] == 0  # every role has unknown pay
    r = await owner_client.post(f"/api/campaigns/{cid}/policy-preview",
                                json={"thresholds": {"shortlist": 30, "tailor": 30, "auto_apply": 30}})
    assert r.status_code == 200 and r.json()["line"]["would_apply"] == 0
    r = await owner_client.post(f"/api/campaigns/{cid}/policy-preview", json={"settings": {"automation.paused": True}})
    assert r.status_code == 422
