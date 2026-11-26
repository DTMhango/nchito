"""Sweep orchestration: isolation, checkpoint, overlap, dry run, hand-off; expiry; retention."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.models.applications import Application
from app.models.search import Availability, Job, JobSighting, Run, RunKind, RunStatus
from app.pipeline import normalise, orchestrator
from app.sources.base import SourceError
from tests.pipeline.intake.conftest import NOW
from tests.pipeline.intake.fakes import make_campaign, make_source, raw

EXTRACT = {"work_model": {"value": "remote", "evidence": "work with the actuarial team"}, "required_skills": ["Python"]}


async def setup(session, rig, names=("A",), **conn):
    sources = [make_source(n) for n in names]
    session.add_all(sources)
    await session.flush()
    campaign = make_campaign(source_ids=[s.id for s in sources])
    session.add(campaign)
    await session.flush()
    run = Run(kind=RunKind.sweep, trigger="manual", campaign_id=campaign.id, status=RunStatus.running)
    session.add(run)
    await session.flush()
    return sources, campaign, run


async def job_count(session):
    return await session.scalar(select(func.count()).select_from(Job))


async def test_sweep_ingests_extracts_and_hands_ids_to_scoring(session, rig):
    _, campaign, run = await setup(session, rig)
    rig.connector("A", jobs=[raw(req="R1", title="Claims Analyst"), raw(req="R2", title="Data Engineer")])
    rig.llm.respond = EXTRACT
    status = await orchestrator.run_sweep(session, run)
    assert status == RunStatus.succeeded, (run.error, run.source_results)
    assert run.counts["found"] == 2 and run.counts["new"] == 2 and run.counts["extracted"] == 2
    for key in ("passed_filters", "above_threshold", "tailored", "applied"):
        assert run.counts[key] == 0
    assert run.source_results[0].status == "ok" and run.source_results[0].new == 2
    assert run.cost_micros == 6 and run.config_versions["prompt_extract"] == normalise.PROMPT_VERSION
    jobs = (await session.scalars(select(Job))).all()
    assert {j.facets.work_model.value for j in jobs} == {"remote"} and jobs[0].availability == Availability.unknown
    (hooked_run, ids), = rig.scored
    assert hooked_run is run and set(ids) == {j.id for j in jobs}
    assert campaign.last_sweep_checkpoint == NOW


async def test_one_failing_source_does_not_fail_the_run_and_checkpoint_stays(session, rig):
    sources, campaign, run = await setup(session, rig, names=("A", "B"))
    rig.connector("A", jobs=[raw(req="R1")])
    rig.connector("B", error=SourceError("HTTP 503"))
    status = await orchestrator.run_sweep(session, run)
    assert status == RunStatus.partial and await job_count(session) == 1
    by_name = {r.source_id: r for r in run.source_results}
    assert by_name[str(sources[0].id)].status == "ok" and by_name[str(sources[1].id)].status == "failed"
    assert "503" in by_name[str(sources[1].id)].error
    assert campaign.last_sweep_checkpoint is None  # partial: checkpoint does not move
    assert sources[1].health.consecutive_failures == 1 and sources[0].last_success_at == NOW


async def test_failed_sweep_does_not_advance_checkpoint(session, rig):
    _, campaign, run = await setup(session, rig)
    campaign.last_sweep_checkpoint = NOW - timedelta(days=3)
    rig.connector("A", error=RuntimeError("boom"))
    status = await orchestrator.run_sweep(session, run)
    assert status == RunStatus.failed and campaign.last_sweep_checkpoint == NOW - timedelta(days=3)
    assert rig.scored == []


async def test_window_is_checkpoint_minus_overlap_and_overlap_is_deduplicated(session, rig):
    _, campaign, run = await setup(session, rig)
    conn = rig.connector("A", jobs=[raw(req="R1"), raw(req="R2")])
    await orchestrator.run_sweep(session, run)
    run.status = RunStatus.succeeded
    assert conn.since_seen == [None] and campaign.last_sweep_checkpoint == NOW
    rig.clock.advance(days=1)
    run2 = Run(kind=RunKind.sweep, trigger="schedule", campaign_id=campaign.id, status=RunStatus.running)
    session.add(run2)
    await session.flush()
    await orchestrator.run_sweep(session, run2)
    assert conn.since_seen[1] == NOW - timedelta(days=2)  # schedule.overlap_days default 2
    assert run2.counts["new"] == 0 and run2.counts["seen"] == 2 and await job_count(session) == 2
    assert len(rig.scored) == 1  # nothing new to score the second time
    assert await session.scalar(select(func.count()).select_from(JobSighting)) == 2


async def test_dry_run_writes_nothing_and_proposes_actions(session, rig):
    sources, campaign, run = await setup(session, rig)
    run.dry_run = True
    rig.connector("A", jobs=[raw(req="R1", title="Claims Analyst")])
    status = await orchestrator.run_sweep(session, run)
    assert status == RunStatus.succeeded and await job_count(session) == 0
    assert run.counts["new"] == 1 and rig.llm.calls == [] and rig.scored == []
    assert campaign.last_sweep_checkpoint is None and sources[0].last_success_at is None
    action, = run.config_versions["proposed_actions"]
    assert action["title"] == "Claims Analyst" and action["action"] == "add_to_matches" and action["job_id"] is None


async def test_budget_cap_leaves_jobs_pending_extraction_and_retries_later(session, rig):
    _, campaign, run = await setup(session, rig)
    job = raw(req="R1")
    rig.connector("A", jobs=[job])
    rig.llm.raise_budget = True
    await orchestrator.run_sweep(session, run)
    stored = await session.scalar(select(Job))
    assert run.counts["extract_skipped"] == 1 and normalise.PENDING_TAG in stored.tags
    run.status = RunStatus.succeeded
    rig.llm.raise_budget = False
    rig.llm.respond = EXTRACT
    run2 = Run(kind=RunKind.sweep, trigger="manual", campaign_id=campaign.id, status=RunStatus.running)
    session.add(run2)
    await session.flush()
    await orchestrator.run_sweep(session, run2)
    assert normalise.PENDING_TAG not in stored.tags and stored.facets.work_model.value == "remote"


async def test_second_sweep_for_same_campaign_running_is_skipped(session, rig):
    _, campaign, _ = await setup(session, rig)
    other = Run(kind=RunKind.sweep, trigger="schedule", campaign_id=campaign.id, status=RunStatus.running)
    session.add(other)
    await session.flush()
    rig.connector("A", jobs=[raw()])
    assert await orchestrator.run_sweep(session, other) == RunStatus.skipped


async def test_scoring_hook_failure_does_not_fail_intake(session, rig):
    _, _, run = await setup(session, rig)
    rig.connector("A", jobs=[raw(req="R1")])

    async def bad(run, ids):
        raise RuntimeError("scorer down")

    orchestrator.register_score_hook(bad)
    assert await orchestrator.run_sweep(session, run) == RunStatus.succeeded
    assert "scoring hand-off failed" in run.error


# ---- expiry -------------------------------------------------------------------------------


async def seeded_job(session, rig, availability="open"):
    _, _, run = await setup(session, rig)
    rig.connector("A", jobs=[raw(req="R1")], availability=availability)
    await orchestrator.run_sweep(session, run)
    job = await session.scalar(select(Job))
    expiry = Run(kind=RunKind.expiry_check, trigger="schedule", status=RunStatus.running)
    session.add(expiry)
    await session.flush()
    return job, expiry


async def test_expiry_open_closed_and_failed_check_is_unknown_never_closed(session, rig):
    job, expiry = await seeded_job(session, rig, "open")
    await orchestrator.run_expiry_check(session, expiry)
    assert job.availability == Availability.open and job.last_checked_at == NOW
    rig.connectors["A"].availability = "closed"
    await orchestrator.run_expiry_check(session, expiry)
    assert job.availability == Availability.closed

    job.availability = Availability.open
    rig.connectors["A"].availability = SourceError("HTTP 500")  # check itself fails
    checked_before = job.last_checked_at
    rig.clock.advance(hours=5)
    await orchestrator.run_expiry_check(session, expiry)
    assert job.availability == Availability.unknown and job.last_checked_at == checked_before
    assert expiry.counts == {"checked": 1, "unknown": 1}


async def test_expiry_skips_applied_and_archived_jobs(session, rig):
    job, expiry = await seeded_job(session, rig)
    session.add(Application(job_id=job.id, applied_at=NOW))
    await session.flush()
    await orchestrator.run_expiry_check(session, expiry)
    assert expiry.counts == {} and rig.connectors["A"].checked == []


# ---- retention ----------------------------------------------------------------------------


async def test_retention_drops_text_and_archives_per_settings(session, rig):
    job, _ = await seeded_job(session, rig)
    old = NOW - timedelta(days=100)
    kept_applied = Job(title="Applied", employer="X", canonical_employer="X", content_hash="h1", triage="new",
                       raw_text="text", created_at=old, updated_at=old)
    below = Job(title="Below", employer="Y", canonical_employer="Y", content_hash="h2", triage="below_threshold",
                raw_text="text", created_at=NOW - timedelta(days=40), updated_at=NOW - timedelta(days=40))
    closed = Job(title="Closed", employer="Z", canonical_employer="Z", content_hash="h3", triage="new",
                 availability=Availability.closed, raw_text="t")
    session.add_all([kept_applied, below, closed])
    await session.flush()
    session.add(Application(job_id=kept_applied.id))
    run = Run(kind=RunKind.retention, trigger="schedule", status=RunStatus.running)
    session.add(run)
    await session.flush()
    await orchestrator.run_retention(session, run)
    assert below.raw_text is None and below.triage == "below_threshold"
    assert closed.triage == "archived" and kept_applied.triage == "new" and kept_applied.raw_text == "text"
    assert job.triage == "new"  # fresh
    assert run.counts["text_dropped"] == 1
