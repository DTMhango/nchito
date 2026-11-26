"""Wave 1 exit test: a scheduled dry run on the example kit sweeps, scores and lists matches within a cap.

No network: the two sources read invented recorded fixtures through ``FakeFetcher``; every model
call is answered by ``FakeLLMClient`` behind the real budget ledger (reserve before the call,
reconcile after, exactly as ``LLMService`` does). The run goes through the real scheduler tick,
the worker's ``run_pipeline`` task, the orchestrator, normalise, filters, scoring and conflicts.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.clock import FakeClock
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.kit.loader import load_kit
from app.kit.schema import KitFile
from app.llm.client import DataBlock, Message, Stage, Usage
from app.llm.fake import FakeCall, FakeLLMClient
from app.llm.ledger import Ledger
from app.models.applications import Application, ApplicationEvent, PendingAction
from app.models.platform import LedgerEntry, LedgerKind
from app.models.search import (
    Assessment,
    AssessmentState,
    Campaign,
    CampaignStatus,
    Job,
    Rubric,
    RubricStatus,
    Run,
    RunKind,
    RunStatus,
    Schedule,
    Source,
    SourceAccess,
)
from app.pipeline import dry_run, orchestrator, wiring
from app.pipeline.decisions import Decision, GateDecision
from app.schemas.json_types import CampaignCriteria, RubricBody
from app.worker.queue import run_pipeline
from app.worker.scheduler import tick
from tests.sources.support import FakeFetcher

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"
BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs?content=true"
FEED_URL = "https://jobs.example.com/feed.xml"
CALL_COST = 1_500  # micros per call (0.15 cents): many calls, none rounded up to a cent
CALL_ESTIMATE = 5_000


class LedgeredFake:
    """``FakeLLMClient`` behind the real ledger, with the run id for the per-run cap."""

    def __init__(self, fake: FakeLLMClient, run_id: uuid.UUID | None) -> None:
        self.fake, self.run_id, self.ledger = fake, run_id, Ledger()

    async def estimate_cost_micros(self, stage: Stage, messages: Sequence[Message], *, model: str | None = None,
                                   schema: type[BaseModel] | None = None) -> int:
        return await self.fake.estimate_cost_micros(stage, messages, model=model, schema=schema)

    async def complete(self, stage: Stage, messages: Sequence[Message], schema: type[Any], *,
                       max_cost_micros: int, model: str | None = None) -> tuple[Any, Usage]:
        reservation = await self.ledger.reserve(stage=stage, provider="fake", model=model or "fake-model",
                                                amount_micros=max_cost_micros, billed=True, run_id=self.run_id)
        result, usage = await self.fake.complete(stage, messages, schema, max_cost_micros=max_cost_micros,
                                                 model=model)
        await self.ledger.reconcile(reservation, cost_micros=usage.cost_micros, input_tokens=usage.input_tokens,
                                    output_tokens=usage.output_tokens)
        return result, usage


def _posting(call: FakeCall) -> str:
    return "\n".join(p.content for m in call.messages for p in m.parts if isinstance(p, DataBlock))


def extract_reply(call: FakeCall) -> dict[str, Any]:
    text = _posting(call)
    q = lambda value, evidence: {"value": value, "evidence": evidence}  # noqa: E731
    if "cannot sponsor" in text:
        return {"work_model": q("on_site", "Supervise the warehouse shift."),
                "work_rights": q("existing_right_required", "must already hold the right to work"),
                "function": "operations", "level": "supervisor"}
    return {"work_model": q("remote", "This role is fully remote."),
            "remote_scope": q("worldwide", "This role is fully remote."),
            "work_rights": q("sponsorship_possible" if "sponsor visas" in text else "not_stated", "We sponsor visas."),
            "visa_sponsorship": q("yes" if "sponsor visas" in text else "not_stated", "We sponsor visas."),
            "employment_type": q("permanent", "hiring"), "function": "analytics",
            "level": "lead" if "Lead" in text else "senior", "required_skills": ["SQL"]}


RATINGS = {"ExampleCo (fictional)|Senior Data Analyst": 5, "ExampleCo (fictional)|Analytics Lead": 4,
           "Example Insurance (fictional)|Senior Data Analyst": 4}


def score_reply(call: FakeCall) -> dict[str, Any]:
    text = _posting(call)
    title = text.split("Title: ", 1)[1].split("\n", 1)[0]
    employer = text.split("Employer: ", 1)[1].split("\n", 1)[0]
    rating = RATINGS[f"{employer}|{title}"]
    names = [line[2:].split(" (weight")[0] for m in call.messages for p in m.parts if not isinstance(p, DataBlock)
             for line in p.text.splitlines() if line.startswith("- ") and "(weight" in line]
    return {"ratings": [{"criterion": n, "rating": rating, "evidence_fact_ids": ["F-1", "F-2"]} for n in names],
            "gaps": []}


def make_fake() -> FakeLLMClient:
    fake = FakeLLMClient(cost_micros=CALL_COST, estimate_micros=CALL_ESTIMATE)
    fake._queues.clear()

    def route(call: FakeCall) -> dict[str, Any]:
        return extract_reply(call) if call.stage == "extract" else score_reply(call)

    fake.default = route
    return fake


@pytest.fixture
def wired():
    fake = make_fake()
    fetcher = FakeFetcher({BOARD_URL: (200, (FIXTURES / "exampleco_board.json").read_text(encoding="utf-8")),
                           FEED_URL: (200, (FIXTURES / "remote_feed.xml").read_text(encoding="utf-8"))})
    wiring.install()

    async def llm_factory(session, run=None):
        return LedgeredFake(fake, run.id if run else None)

    orchestrator.configure(llm_factory=llm_factory, transport=fetcher)
    yield fake
    wiring.uninstall()


async def set_settings(**values: Any) -> None:
    async with get_sessionmaker()() as s:
        for key, value in values.items():
            await settings_service.set_value(s, key.replace("__", "."), value, actor="test")
        await s.commit()


async def seed(cap_minor: int) -> uuid.UUID:
    """Example kit, its two sources, a campaign with the kit's rubric, a dry-run schedule, a cap."""
    kit = KitFile.model_validate_json((REPO / "kits" / "example" / "kit.json").read_text(encoding="utf-8"))
    raw = json.loads((REPO / "kits" / "example" / "kit.json").read_text(encoding="utf-8"))
    await set_settings(budget__monthly_cap_minor=cap_minor)
    async with get_sessionmaker()() as s:
        await load_kit(s, kit)
        sources = [Source(connector=src["connector"], name=src["name"], access=SourceAccess(src["access"]),
                          config=src["config"], permitted_actions=src["permitted_actions"], enabled=True)
                   for src in raw["sources"]]
        s.add_all(sources)
        rubric = Rubric(name=raw["rubrics"][0]["name"], body=RubricBody.model_validate(raw["rubrics"][0]["body"]),
                        status=RubricStatus.active, family=uuid.uuid4(), version=1)
        s.add(rubric)
        await s.flush()
        spec = raw["campaigns"][0]
        campaign = Campaign(name=spec["name"], status=CampaignStatus.active, rubric_id=rubric.id,
                            priority=spec["priority"], criteria=CampaignCriteria.model_validate(spec["criteria"]),
                            source_ids=[src.id for src in sources])
        s.add(campaign)
        await s.flush()
        s.add(Schedule(name="Nightly dry run", kind=RunKind.sweep, campaign_id=campaign.id, cron="0 6 * * *",
                       dry_run=True, next_run_at=datetime.now(UTC) - timedelta(minutes=1)))
        await s.commit()
        return campaign.id


async def scheduled_run(now: datetime) -> Run:
    queued: list[Run] = []

    async def enqueue(run: Run) -> None:
        queued.append(run)

    async with get_sessionmaker()() as s:
        await tick(s, FakeClock(now), enqueue)
        await s.commit()
    run, = queued
    assert run.dry_run and run.trigger in ("schedule", "catch_up")
    await run_pipeline.func(run_id=str(run.id))
    return run


async def load_run(run_id: uuid.UUID) -> Run:
    async with get_sessionmaker()() as s:
        run = await s.get(Run, run_id)
        assert run is not None
        return run


async def pipeline_state(session) -> tuple[int, int, int]:
    counts = []
    for model in (Application, PendingAction, ApplicationEvent):
        counts.append(await session.scalar(select(func.count()).select_from(model)))
    return tuple(counts)  # type: ignore[return-value]


async def test_scheduled_dry_run_sweeps_scores_and_lists_matches_within_the_cap(wired, owner_client, session):
    campaign_id = await seed(cap_minor=500)
    before = await pipeline_state(session)
    run = await load_run((await scheduled_run(datetime.now(UTC))).id)

    assert run.status == RunStatus.succeeded, run.error
    assert run.counts["found"] == 5 and run.counts["new"] == 4  # the repost in the feed is de-duplicated
    assert run.counts["extracted"] == 4 and run.counts["scored"] == 3 and run.counts["filtered_out"] == 1
    assert all(r.status == "ok" for r in run.source_results) and len(run.source_results) == 2

    jobs = {(j.employer, j.title): j for j in (await session.scalars(select(Job))).all()}
    assert len(jobs) == 4
    lead = jobs[("ExampleCo (fictional)", "Analytics Lead")]
    senior = jobs[("ExampleCo (fictional)", "Senior Data Analyst")]
    assert senior.facets.work_model.value == "remote" and senior.function == "analytics"
    assessments = {a.job_id: a for a in (await session.scalars(select(Assessment))).all()}
    assert assessments[senior.id].state == AssessmentState.scored and assessments[senior.id].score == 100
    assert assessments[senior.id].ratings[0].evidence_fact_ids == ["F-1", "F-2"]  # scored with evidence
    warehouse = jobs[("ExampleCo (fictional)", "Warehouse Supervisor")]
    assert assessments[warehouse.id].state == AssessmentState.filtered_out  # excluded before any model call
    assert (senior.conflict_state.value, lead.conflict_state.value) == ("winner", "held")  # one role per employer

    proposals = {(p["employer"], p["title"]): p for p in run.config_versions["proposed_actions"]}
    assert proposals[("ExampleCo (fictional)", "Senior Data Analyst")]["action"] == "prepare"
    assert proposals[("ExampleCo (fictional)", "Analytics Lead")]["action"] == "add_to_matches"
    assert proposals[("ExampleCo (fictional)", "Warehouse Supervisor")]["action"] == "skip"

    remote = {"version": 1, "root": {"type": "group", "op": "and", "negate": False, "conditions": [
        {"type": "values", "facet": "facets.work_model", "include": ["remote"], "exclude": [], "match": "any"}]}}
    listed = (await owner_client.get("/api/jobs", params={"conditions": json.dumps(remote)})).json()
    assert {(i["employer"], i["title"]) for i in listed["items"]} == {
        ("ExampleCo (fictional)", "Senior Data Analyst"), ("ExampleCo (fictional)", "Analytics Lead"),
        ("Example Insurance (fictional)", "Senior Data Analyst")}

    calls = len(wired.calls)
    # 4 extractions + 3 scores + 2 escalations (the two roles scored 80 sit within the margin of 85)
    assert calls == 9 and len(wired.calls_for("score")) == 5
    spent = await session.scalar(select(func.sum(LedgerEntry.amount_micros)).where(
        LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.run_id == run.id))
    assert spent == calls * CALL_COST == run.cost_micros  # micros: 9 small calls cost 1.35 cents, not 9
    assert spent < 500 * 10_000

    campaign = await session.get(Campaign, campaign_id)
    assert campaign.last_sweep_checkpoint is None and campaign.source_checkpoints == {}
    assert all(src.last_success_at is None for src in (await session.scalars(select(Source))).all())
    assert await pipeline_state(session) == before == (0, 0, 0)


async def test_too_low_a_cap_pauses_for_budget_and_resumes_when_raised(wired, owner_client, session):
    await seed(cap_minor=1)  # 1 cent = 10_000 micros: room for a few 1_500-micro calls only
    run = await load_run((await scheduled_run(datetime.now(UTC))).id)
    assert run.status == RunStatus.paused, run.error
    assert "Paused for budget" in run.error and run.config_versions["paused"]["scope"] == "monthly"
    parked = await session.scalar(select(func.count()).select_from(Assessment).where(
        Assessment.state.in_([AssessmentState.parked, AssessmentState.pending])))
    pending = await session.scalar(select(func.count()).select_from(Job).where(Job.tags.any("extraction_pending")))
    assert parked + pending > 0

    async with get_sessionmaker()() as s:  # nothing changed: the tick leaves it paused
        assert await orchestrator.resume_paused(s, _no_enqueue) == []
    await set_settings(budget__monthly_cap_minor=500)
    resumed: list[Run] = []

    async def enqueue(r: Run) -> None:
        resumed.append(r)

    async with get_sessionmaker()() as s:
        await orchestrator.resume_paused(s, enqueue)
    assert [r.id for r in resumed] == [run.id]
    await run_pipeline.func(run_id=str(run.id))

    done = await load_run(run.id)
    assert done.status == RunStatus.succeeded, done.error
    session.expire_all()
    states = {a.state for a in (await session.scalars(select(Assessment))).all()}
    assert states == {AssessmentState.scored, AssessmentState.filtered_out}
    assert await session.scalar(select(func.count()).select_from(Job).where(
        Job.tags.any("extraction_pending"))) == 0
    assert len(done.config_versions["proposed_actions"]) == 4


async def _no_enqueue(run: Run) -> None:
    raise AssertionError("nothing should be resumed")


async def test_dry_run_proposals_count_simulated_applications_against_the_caps(session, monkeypatch):
    """The proposals feed each simulated application into the next decision's counters."""
    campaign = Campaign(name="C", status=CampaignStatus.active, criteria=CampaignCriteria())
    session.add(campaign)
    await session.flush()
    jobs = []
    for i, employer in enumerate(("A Ltd", "A Ltd", "B Ltd")):
        job = Job(title=f"Role {i}", employer=employer, canonical_employer=employer, content_hash=f"h{i}")
        session.add(job)
        await session.flush()
        session.add(Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored,
                               base_score=90 - i, score=90 - i))
        jobs.append(job)
    await session.flush()
    seen: list[dict[str, int]] = []

    def fake_decide(data):
        seen.append(dict(data.counters))
        ok = data.counters["sent_today"] < 1 and data.counters["employer_live"] < 1
        gate = GateDecision("daily_cap", "automation", "pass" if ok else "fail", "cap reached" if not ok else "ok")
        return Decision(verdict="auto_apply" if ok else "ask_owner", gates=(gate,), auto_apply_allowed=ok,
                        effective_score=data.score)

    monkeypatch.setattr(dry_run, "decide", fake_decide)
    out = await dry_run.propose_actions(session, campaign, [j.id for j in jobs], now=datetime.now(UTC), limit=10)
    assert [p["action"] for p in out] == ["apply", "ask_owner", "ask_owner"]
    assert [c["sent_today"] for c in seen] == [0, 1, 1] and [c["sent_week"] for c in seen] == [0, 1, 1]
    assert [c["employer_live"] for c in seen] == [0, 1, 0]  # the second A Ltd role sees the simulated one
    assert out[1]["reason"] == "cap reached"
