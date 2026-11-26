"""Endpoints the app shell calls in wave 0: manual capture and the global Autopilot switch."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.api.routers.jobs import get_capture_enqueue
from app.models.platform import SettingRevision
from app.models.search import Job, JobSighting


async def test_capture_requires_owner(client):
    assert (await client.post("/api/jobs/capture", json={"url": "https://jobs.example.com/1"})).status_code == 401


@pytest.fixture
def queued(app):
    ids: list[uuid.UUID] = []

    async def factory():
        async def enqueue(job_id):
            ids.append(job_id)

        return enqueue

    app.dependency_overrides[get_capture_enqueue] = factory
    yield ids
    app.dependency_overrides.pop(get_capture_enqueue, None)


async def test_capture_link_and_text(owner_client, session, queued):
    r = await owner_client.post("/api/jobs/capture", json={"url": "https://jobs.example.com/roles/42",
                                                          "text": "Senior Data Analyst\nRemote, Africa"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    job = await session.get(Job, uuid.UUID(body["id"]))
    assert job.title == "Senior Data Analyst" and job.apply_url == "https://jobs.example.com/roles/42"
    assert job.tags == ["captured"] and job.availability.value == "unknown" and job.triage == "new"
    assert queued == [job.id]  # handed to the worker's process_capture
    sightings = (await session.scalars(select(JobSighting).where(JobSighting.job_id == job.id))).all()
    assert [s.url for s in sightings] == ["https://jobs.example.com/roles/42"]

    text_only = await owner_client.post("/api/jobs/capture", json={"text": "Data Scientist at Example Ltd"})
    assert text_only.status_code == 202
    audit = (await owner_client.get("/api/audit", params={"action": "job.captured"})).json()
    assert len(audit["items"]) == 2


async def test_capture_validation(owner_client):
    r = await owner_client.post("/api/jobs/capture", json={"url": "  ", "text": ""})
    assert r.status_code == 422 and r.json()["detail"] == "Paste a link or the posting text."
    r = await owner_client.post("/api/jobs/capture", json={"url": "javascript:alert(1)"})
    assert r.status_code == 422


async def test_autopilot_requires_owner(client):
    assert (await client.get("/api/autopilot")).status_code == 401


async def test_autopilot_pause_and_resume(owner_client, session):
    state = (await owner_client.get("/api/autopilot")).json()
    assert state == {"paused": False, "paused_at": None,
                     "summary": {"cancelled": [], "paused": [], "already_out": []}}

    paused = (await owner_client.put("/api/autopilot", json={"paused": True})).json()
    assert paused["paused"] is True and paused["paused_at"]
    assert paused["summary"] == {"cancelled": [], "paused": [], "already_out": []}
    assert (await owner_client.get("/api/autopilot")).json()["paused"] is True
    setting = (await owner_client.get("/api/settings/automation.paused")).json()
    assert setting["value"] is True

    resumed = (await owner_client.put("/api/autopilot", json={"paused": False})).json()
    assert resumed["paused"] is False and resumed["paused_at"] is None

    revisions = (await session.scalars(select(SettingRevision).where(SettingRevision.key == "automation.paused")
                                       .order_by(SettingRevision.version))).all()
    assert [(r.new_value, r.reason) for r in revisions] == [(True, "autopilot paused"), (False, "autopilot resumed")]
    audit = (await owner_client.get("/api/audit", params={"subject_id": "automation.paused"})).json()
    assert len(audit["items"]) == 2
