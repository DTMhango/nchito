"""Studio endpoints: tailor (queued, idempotent), spec get/put (owner edits re-run checks), check."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.routers.applications import get_tailor_enqueue
from app.core.db import get_sessionmaker
from app.llm.deps import llm_service
from app.llm.fake import FakeLLMClient
from app.models.applications import ApplicationPacket, Stage, TailoringRequest
from app.pipeline.tailoring import service
from app.schemas.json_types import PacketContents, PacketDestination
from tests.tailoring.helpers import good_spec, world


@pytest.fixture
def queued(app) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []

    async def enqueue(req: TailoringRequest) -> None:
        ids.append(req.id)

    app.dependency_overrides[get_tailor_enqueue] = lambda: enqueue
    yield ids
    app.dependency_overrides.pop(get_tailor_enqueue, None)


@pytest.fixture
def fake_llm(app) -> FakeLLMClient:
    fake = FakeLLMClient()
    app.dependency_overrides[llm_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(llm_service, None)


async def seeded(**kw: Any):
    async with get_sessionmaker()() as s:
        w = await world(s, **kw)
        await s.commit()
    return w


async def test_tailor_queues_once_per_spec_version(owner_client, queued):
    w = await seeded()
    r = await owner_client.post(f"/api/applications/{w.app.id}/tailor")
    assert r.status_code == 202, r.text
    assert r.json()["queued"] is True and r.json()["run_id"] is not None
    r2 = await owner_client.post(f"/api/applications/{w.app.id}/tailor")
    assert r2.status_code == 202 and r2.json()["queued"] is True
    assert len(queued) == 1  # the same request, not queued twice
    detail = (await owner_client.get(f"/api/applications/{w.app.id}")).json()
    assert detail["stage"] == "tailoring"
    state = (await owner_client.get(f"/api/applications/{w.app.id}/spec")).json()
    assert state["tailoring"] == "queued" and state["version"] is None and not state["checked"]


async def test_tailor_refused_after_submission(owner_client, queued):
    w = await seeded(stage=Stage.submitted)
    r = await owner_client.post(f"/api/applications/{w.app.id}/tailor")
    assert r.status_code == 409 and queued == []


async def test_put_spec_reruns_checks_and_get_shows_the_checked_hash(owner_client):
    w = await seeded()
    r = await owner_client.put(f"/api/applications/{w.app.id}/spec", json={"spec": good_spec(w)})
    assert r.status_code == 200, r.text
    assert all(c["status"] == "pass" for c in r.json()["check_results"])
    state = (await owner_client.get(f"/api/applications/{w.app.id}/spec")).json()
    assert state["version"] == 1 and state["origin"] == "owner" and state["checked"] and state["status"] == "pass"

    bad = good_spec(w)
    bad["summary"] = {"text": "Cut monthly reporting time by 75% at Globex Example Ltd.", "fact_ids": ["F-1"]}
    r = await owner_client.put(f"/api/applications/{w.app.id}/spec", json={"spec": bad})
    blocks = [c for c in r.json()["check_results"] if c["status"] == "block"]
    assert blocks and blocks[0]["check"] == "fact_trace" and "75%" in blocks[0]["detail"]
    state = (await owner_client.get(f"/api/applications/{w.app.id}/spec")).json()
    assert state["version"] == 2 and state["status"] == "block" and state["checked"]
    assert [v["status"] for v in state["versions"]] == ["block", "pass"]
    first = (await owner_client.get(f"/api/applications/{w.app.id}/spec", params={"version": 1})).json()
    assert first["status"] == "pass" and first["content_hash"] != state["content_hash"]
    assert (await owner_client.get(f"/api/applications/{w.app.id}/spec", params={"version": 9})).status_code == 404
    timeline = (await owner_client.get(f"/api/applications/{w.app.id}/timeline")).json()
    assert [e["detail"]["version"] for e in timeline if e["kind"] == "spec_version"] == [1, 2]


async def test_editing_the_spec_invalidates_an_approved_packet(owner_client):
    w = await seeded()
    async with get_sessionmaker()() as s:
        packet = ApplicationPacket(application_id=w.app.id, version=1, content_hash="a" * 64,
                                   contents=PacketContents(destination=PacketDestination(
                                       url="https://jobs.example.com/apply", domain="jobs.example.com"),
                                       sending_identity="owner@example.com"))
        s.add(packet)
        await s.flush()
        app = await s.get(type(w.app), w.app.id)
        app.approved_packet_id = packet.id
        await s.commit()
    r = await owner_client.put(f"/api/applications/{w.app.id}/spec", json={"spec": good_spec(w)})
    assert r.json()["approved_packet_id"] is None
    async with get_sessionmaker()() as s:
        got = await s.get(ApplicationPacket, packet.id)
        assert got.invalidated_at is not None and "spec version 1" in got.invalidated_reason


async def test_check_endpoint_runs_the_model_pass_without_clearing_code_findings(owner_client, fake_llm):
    w = await seeded()
    r = await owner_client.post(f"/api/applications/{w.app.id}/check")
    assert r.status_code == 409  # nothing to check yet
    bad = good_spec(w)
    bad["skills"] = ["SQL", "Rust"]
    await owner_client.put(f"/api/applications/{w.app.id}/spec", json={"spec": bad})
    fake_llm.script("claim_check", {"flags": [{"path": "summary", "problem": "vague", "fact_ids": []}]})
    r = await owner_client.post(f"/api/applications/{w.app.id}/check")
    assert r.status_code == 200, r.text
    by_check = {(c["check"], c["status"]) for c in r.json()}
    assert ("skills", "block") in by_check and ("claim_check", "warn") in by_check
    assert fake_llm.calls_for("claim_check")


async def test_the_worker_task_processes_a_queued_request(owner_client, queued):
    w = await seeded()
    await owner_client.post(f"/api/applications/{w.app.id}/tailor")
    fake = FakeLLMClient().script("tailor", {**good_spec(w), "screening_questions": []}).script(
        "claim_check", {"flags": []})
    async with get_sessionmaker()() as s:
        assert await service.process(s, fake, queued[0]) == "done"
        await s.commit()
    state = (await owner_client.get(f"/api/applications/{w.app.id}/spec")).json()
    assert state["version"] == 1 and state["origin"] == "tailor" and state["tailoring"] == "done"
    assert state["checked"] and state["status"] == "pass"
    r = await owner_client.post(f"/api/applications/{w.app.id}/tailor")
    assert r.json()["queued"] is True and len(queued) == 2  # version 1 exists: a new draft may be asked for
