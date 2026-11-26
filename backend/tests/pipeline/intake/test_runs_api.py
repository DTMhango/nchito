"""Runs and schedules endpoints, and manual capture through the pipeline."""

from __future__ import annotations

import pytest

from app.api.routers.runs import get_enqueue
from app.models.search import Job, Run
from app.pipeline import capture, orchestrator
from tests.pipeline.intake.fakes import make_campaign
from tests.sources.support import FakeFetcher


@pytest.fixture
def web(owner_client, app):
    queued: list[Run] = []

    async def fake_enqueue_factory():
        async def enqueue(run):
            queued.append(run)

        return enqueue

    app.dependency_overrides[get_enqueue] = fake_enqueue_factory
    owner_client.queued = queued
    yield owner_client
    app.dependency_overrides.pop(get_enqueue, None)


async def campaign_id(session):
    c = make_campaign()
    session.add(c)
    await session.commit()
    return str(c.id)


async def test_start_manual_and_dry_run_then_list_get_cancel(web, session):
    cid = await campaign_id(session)
    r = await web.post("/api/runs", json={"kind": "sweep", "campaign_id": cid, "dry_run": True})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "queued" and run["dry_run"] is True and run["trigger"] == "manual"
    assert run["proposed_actions"] == [] and web.queued[0].id is not None
    assert (await web.post("/api/runs", json={"kind": "sweep", "campaign_id": cid})).status_code == 409
    got = (await web.get(f"/api/runs/{run['id']}")).json()
    assert got["id"] == run["id"]
    assert (await web.get("/api/runs", params={"kind": "sweep"})).json()["total"] == 1
    cancelled = await web.post(f"/api/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await web.post(f"/api/runs/{run['id']}/cancel")).status_code == 409
    assert (await web.get(f"/api/runs/{run['id']}")).json()["finished_at"] is not None


async def test_sweep_needs_a_campaign(web):
    assert (await web.post("/api/runs", json={"kind": "sweep"})).status_code == 422
    assert (await web.post("/api/runs", json={"kind": "retention"})).status_code == 202


async def test_schedules_crud_validates_and_rearms(web, session):
    cid = await campaign_id(session)
    body = {"name": "Daily", "kind": "sweep", "campaign_id": cid, "cron": "0 6 * * *", "timezone": "Africa/Lusaka"}
    made = await web.post("/api/schedules", json=body)
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    assert made.json()["next_run_at"] is None  # the tick arms it
    assert (await web.post("/api/schedules", json={**body, "cron": "not cron"})).status_code == 422
    assert (await web.post("/api/schedules", json={**body, "timezone": "Mars/Base"})).status_code == 422
    assert (await web.post("/api/schedules", json={**body, "campaign_id": None})).status_code == 422
    expiry = await web.post("/api/schedules", json={"name": "Expiry", "kind": "expiry_check", "cron": "0 12 * * *"})
    assert expiry.status_code == 201
    upd = await web.put(f"/api/schedules/{sid}", json={**body, "cron": "0 7 * * *"})
    assert upd.json()["cron"] == "0 7 * * *"
    assert (await web.get("/api/schedules")).json()["total"] == 2
    assert (await web.delete(f"/api/schedules/{sid}")).status_code == 204


# ---- manual capture through the pipeline --------------------------------------------------

POSTING = """<html><head><title>Fallback</title><script type="application/ld+json">
{"@type": "JobPosting", "title": "Claims Analyst", "hiringOrganization": {"name": "Example Insurance"},
 "description": "<p>Analyse motor claims and prepare monthly loss reports for the actuarial team.</p>"}
</script></head><body></body></html>"""


async def test_capture_url_is_fetched_normalised_and_filled_in(session, rig):
    rig.llm.respond = {}
    orchestrator.configure(source_factory=None,
                           transport=FakeFetcher({"https://careers.example.com/a": (200, POSTING)}))
    job = await capture.capture(session, "https://careers.example.com/a", None)
    result = await capture.process_capture(session, job.id)
    assert result.fetched and result.job.id == job.id
    assert (job.title, job.employer, job.canonical_employer) == ("Claims Analyst", "Example Insurance",
                                                                 "Example Insurance")
    assert "monthly loss reports" in job.raw_text and capture.CAPTURED_TAG in job.tags
    assert len(rig.llm.calls) == 1


async def test_capture_of_a_known_job_merges_into_it(session, rig):
    orchestrator.configure(source_factory=None, transport=FakeFetcher({
        "https://careers.example.com/a": (200, POSTING), "https://careers.example.com/other-copy": (200, POSTING)}))
    first = await capture.capture(session, "https://careers.example.com/a", None)
    await capture.process_capture(session, first.id)
    second = await capture.capture(session, "https://careers.example.com/other-copy", None)
    again = await capture.process_capture(session, second.id)
    assert again.merged_into is not None and again.merged_into.id == first.id
    assert second.merged_into_id == first.id


async def test_capture_of_pasted_text_without_llm_stays_pending(session, rig):
    orchestrator.configure(llm_factory=None)
    job = await capture.capture(session, None, "Claims Analyst\nAnalyse claims. Apply to jobs@example.com to apply.")
    result = await capture.process_capture(session, job.id)
    assert result.job.apply_email == "jobs@example.com" and "extraction_pending" in job.tags
    assert (await session.get(Job, job.id)).employer == "Unknown employer"


async def test_capture_unreachable_link_stays_a_stub(session, rig):
    orchestrator.configure(source_factory=None, transport=FakeFetcher({"https://careers.example.com/x": (403, "")}))
    job = await capture.capture(session, "https://careers.example.com/x", None)
    result = await capture.process_capture(session, job.id)
    assert result.error and job.availability.value == "unknown" and "extraction_pending" in job.tags
