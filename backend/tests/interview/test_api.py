"""Interview endpoints: generate (queued once), get, estimate, edit, note, favourite, versions, practice,
export and rounds."""

from __future__ import annotations

import uuid

import pytest

from app.api.routers.interview import get_interview_enqueue
from app.core.db import get_sessionmaker
from app.llm.deps import llm_service
from app.models.applications import InterviewPack, Stage
from app.pipeline.interview import service
from tests.interview.helpers import fake
from tests.tailoring.helpers import world


@pytest.fixture
def queued(app) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []

    async def enqueue(pack: InterviewPack) -> None:
        ids.append(pack.id)

    app.dependency_overrides[get_interview_enqueue] = lambda: enqueue
    yield ids
    app.dependency_overrides.pop(get_interview_enqueue, None)


@pytest.fixture
def fake_llm(app):
    client = fake()
    app.dependency_overrides[llm_service] = lambda: client
    yield client
    app.dependency_overrides.pop(llm_service, None)


async def seeded():
    async with get_sessionmaker()() as s:
        w = await world(s, stage=Stage.interview)
        await s.commit()
    return w


async def build_now(pack_id: str) -> None:
    async with get_sessionmaker()() as s:
        await service.process(s, fake(), uuid.UUID(pack_id))
        await s.commit()


async def test_generate_get_edit_export_and_rounds(owner_client, queued, fake_llm):
    w = await seeded()
    base = f"/api/jobs/{w.job.id}/interview-pack"
    assert (await owner_client.get(base)).status_code == 404
    r = await owner_client.post(base)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["generation"] == 1 and body["estimate_micros"] == 0
    assert (await owner_client.post(base)).json()["generation"] == 1 and len(queued) == 1  # queued once
    await build_now(body["id"])

    pack = (await owner_client.get(base)).json()
    assert pack["status"] == "done" and pack["flagged"] == [] and pack["basis"]["source"] == "none"
    est = (await owner_client.get(f"{base}/estimate")).json()
    assert set(est["sections"]) == {"role_brief", "why_you", "questions", "stories", "questions_to_ask", "gaps"}

    edit = await owner_client.put(f"{base}/sections/why_you", json={"content": {"points": [
        {"requirement": "SQL", "point": {"text": "Grew customers by 99%.", "fact_ids": ["F-3"]}}]}})
    assert edit.status_code == 200 and edit.json()["flagged"] is True and edit.json()["version"] == 2
    bad = await owner_client.put(f"{base}/sections/why_you", json={"content": {"nope": 1}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_section"
    versions = (await owner_client.get(f"{base}/sections/why_you/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    note = await owner_client.put(f"{base}/sections/gaps/note", json={"note": "Mention the course."})
    assert note.json()["notes"] == {"gaps": "Mention the course."}
    fav = await owner_client.put(f"{base}/stories/s1/favourite", json={"favourite": True})
    assert fav.status_code == 200 and fav.json()["content"]["items"][0]["favourite"] is True
    assert (await owner_client.put(f"{base}/stories/s9/favourite", json={})).status_code == 404
    story_version = fav.json()["version"]
    story = await owner_client.put(f"{base}/stories/s1", json={"situation": "A quarterly report was late.",
                                                               "base_version": story_version})
    assert story.status_code == 200 and story.json()["version"] == story_version + 1
    item = story.json()["content"]["items"][0]
    assert item["situation"] == "A quarterly report was late." and item["favourite"] is True
    stale = await owner_client.put(f"{base}/stories/s1", json={"result": "x", "base_version": story_version})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_conflict"
    assert (await owner_client.put(f"{base}/stories/s9", json={"title": "x"})).status_code == 404

    regen = await owner_client.post(f"{base}/sections/why_you/regenerate")
    assert regen.status_code == 202 and regen.json()["pending_sections"] == ["why_you", "crib_sheet"]
    again = await owner_client.post(f"{base}/sections/why_you/regenerate")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "still_queued"
    await build_now(body["id"])

    txt = await owner_client.get(f"{base}/export", params={"fmt": "txt"})
    assert txt.status_code == 200 and txt.headers["content-type"].startswith("text/plain")
    assert "Mention the course." in txt.text
    pdf = await owner_client.get(f"{base}/export")
    assert pdf.content.startswith(b"%PDF")

    practice = await owner_client.post(f"{base}/practice", json={"question": "Why this role?",
                                                                 "draft_answer": "I like reporting."})
    assert practice.status_code == 201 and practice.json()["status"] == "done"
    assert len((await owner_client.get(f"{base}/practice")).json()) == 1

    rnd = await owner_client.post(f"{base}/rounds", json={"round_number": 1, "format": "video",
                                                          "interviewers": ["A. Example"]})
    assert rnd.status_code == 201, rnd.text
    upd = await owner_client.put(f"/api/interview-rounds/{rnd.json()['id']}",
                                 json={"round_number": 1, "notes": "Went well."})
    assert upd.json()["notes"] == "Went well."
    assert len((await owner_client.get(f"{base}/rounds")).json()) == 1


async def test_unknown_section_is_refused(owner_client, queued, fake_llm):
    w = await seeded()
    r = await owner_client.post(f"/api/jobs/{w.job.id}/interview-pack", json={"sections": ["company_news"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_section" and queued == []


async def test_practice_endpoint_and_retry_after_a_budget_pause(owner_client, app):
    """``POST .../practice`` stores a budget refusal as ``paused``; ``POST /api/interview-practice/{id}/retry``
    asks again on the same row (it used to return before retrying), and a done answer is not asked twice."""
    from app.llm.client import BudgetExhausted

    w = await seeded()
    base = f"/api/jobs/{w.job.id}/interview-pack"
    refusal = BudgetExhausted("monthly", needed_micros=5, available_micros=0, currency="USD")
    app.dependency_overrides[llm_service] = lambda: fake(PracticeFeedback=refusal)
    try:
        r = await owner_client.post(f"{base}/practice", json={"question": "Why this role?",
                                                              "draft_answer": "I like reporting.",
                                                              "category": "motivation"})
        assert r.status_code == 201 and r.json()["status"] == "paused" and r.json()["feedback"] is None
        paused_id = r.json()["id"]
        still = await owner_client.post(f"/api/interview-practice/{paused_id}/retry")
        assert still.status_code == 200 and still.json()["status"] == "paused"  # the budget still refuses

        working = fake()
        app.dependency_overrides[llm_service] = lambda: working
        retried = await owner_client.post(f"/api/interview-practice/{paused_id}/retry")
        assert retried.status_code == 200, retried.text
        out = retried.json()
        assert out["id"] == paused_id and out["status"] == "done" and out["feedback"]["feedback"]
        assert out["question"] == "Why this role?" and out["draft_answer"] == "I like reporting."
        assert len(working.calls) == 1

        again = await owner_client.post(f"/api/interview-practice/{paused_id}/retry")
        assert again.status_code == 200 and again.json()["status"] == "done" and len(working.calls) == 1
        listed = (await owner_client.get(f"{base}/practice")).json()
        assert [p["id"] for p in listed] == [paused_id]  # retried in place, not a second row
        assert (await owner_client.post(f"/api/interview-practice/{uuid.uuid4()}/retry")).status_code == 404
    finally:
        app.dependency_overrides.pop(llm_service, None)
