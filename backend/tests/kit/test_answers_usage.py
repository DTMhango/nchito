"""Answers in use: pending_applications_using counts open applications whose packet or pending actions use it."""

from __future__ import annotations

from app.models.applications import Application, ApplicationPacket, PendingAction, PendingActionType, Stage
from app.models.search import Job
from app.schemas.json_types import PacketAnswer, PacketContents, PacketDestination

QUESTION = {"canonical": "Do you need visa sponsorship?", "variants": []}


async def make_job(session, title="Analyst") -> Job:
    job = Job(title=title, employer="Example Co", canonical_employer="Example Co", content_hash=title)
    session.add(job)
    await session.flush()
    return job


async def make_app(session, stage: Stage, answer_ids: list[str]) -> Application:
    job = await make_job(session, f"Role {stage.value} {len(answer_ids)}")
    app = Application(job_id=job.id, stage=stage)
    session.add(app)
    await session.flush()
    contents = PacketContents(
        destination=PacketDestination(url="https://example.com/apply", domain="example.com"),
        sending_identity="owner@example.com",
        answers=[PacketAnswer(question="Visa?", value="No", answer_id=i) for i in answer_ids])
    session.add(ApplicationPacket(application_id=app.id, version=1, content_hash="0" * 64, contents=contents))
    await session.flush()
    return app


async def test_counts_open_applications_using_the_answer(owner_client, session):
    made = await owner_client.post("/api/kit/answers", json={"patterns": QUESTION, "value": "No"})
    other = await owner_client.post("/api/kit/answers", json={"patterns": {"canonical": "Notice period?"},
                                                              "value": "30 days"})
    answer_id, other_id = made.json()["id"], other.json()["id"]
    assert made.json()["pending_applications_using"] == 0

    ready = await make_app(session, Stage.ready, [answer_id])
    await make_app(session, Stage.tailoring, [other_id])          # a different answer
    await make_app(session, Stage.submitted, [answer_id])         # already sent: a fixed snapshot
    via_action = await make_app(session, Stage.shortlisted, [])
    session.add(PendingAction(type=PendingActionType.unknown_question, application_id=via_action.id,
                              title="Visa?", detail={"answer_id": answer_id}))
    await session.commit()

    assert (await owner_client.get(f"/api/kit/answers/{answer_id}")).json()["pending_applications_using"] == 2
    listed = {a["id"]: a for a in (await owner_client.get("/api/kit/answers")).json()["items"]}
    assert listed[answer_id]["pending_applications_using"] == 2 and listed[other_id]["pending_applications_using"] == 1

    uses = (await owner_client.get(f"/api/kit/answers/{answer_id}/usage")).json()
    assert {u["application_id"]: u["via"] for u in uses} == {str(ready.id): "packet",
                                                             str(via_action.id): "pending_action"}
    assert (await owner_client.get("/api/kit/answers/00000000-0000-0000-0000-000000000000/usage")).status_code == 404
