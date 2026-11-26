"""One role per employer (DESIGN.md 7.1)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import Application, PendingAction, PendingActionType, Stage
from app.models.platform import AuditEvent
from app.models.search import Assessment, AssessmentState, Availability, ConflictState, Job
from app.pipeline import conflicts
from tests.pipeline.matching.fakes import add_campaign, add_job, add_rubric
from tests.pipeline.matching.helpers import NOW


async def scored(session, job, campaign, score: int) -> Assessment:
    a = Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored, score=score,
                   base_score=score, filter_results=[])
    session.add(a)
    await session.flush()
    return a


async def setting(session, key, value):
    await settings_service.set_value(session, key, value, actor="owner")


async def resolve(session, *jobs):
    await conflicts.resolve_employers(session, {j.canonical_employer for j in jobs}, now=NOW)
    for j in jobs:
        await session.refresh(j)


async def test_highest_score_wins_and_loser_is_held_with_reason(session):
    campaign = await add_campaign(session, await add_rubric(session))
    manager = await add_job(session, "Analytics Manager")
    senior = await add_job(session, "Senior Analyst")
    a_win = await scored(session, manager, campaign, 88)
    a_lose = await scored(session, senior, campaign, 74)
    await resolve(session, manager, senior)
    assert manager.conflict_state == ConflictState.winner and senior.conflict_state == ConflictState.held
    assert "outranked by Analytics Manager (Analytics), 88 vs 74" in senior.conflict_note
    assert "matching.conflict_winner=highest_score" in manager.conflict_note
    assert a_win.is_conflict_winner and not a_lose.is_conflict_winner
    event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "conflict.decided"))
    assert event.detail["winner"]["score"] == 88


@pytest.mark.parametrize("change", ["closed", "skipped"])
async def test_promotion_when_winner_closes_or_is_skipped(session, change):
    campaign = await add_campaign(session, await add_rubric(session))
    first = await add_job(session, "Head of Analytics")
    second = await add_job(session, "Analytics Manager")
    await scored(session, first, campaign, 90)
    await scored(session, second, campaign, 80)
    await resolve(session, first, second)
    assert second.conflict_state == ConflictState.held
    if change == "closed":
        first.availability = Availability.closed
    else:
        first.triage = "skipped"
    await conflicts.on_job_changed(session, first, now=NOW)
    await session.refresh(second)
    await session.refresh(first)
    assert second.conflict_state == ConflictState.winner
    assert second.conflict_note.startswith("promoted after Head of Analytics")
    assert first.conflict_state == ConflictState.none


@pytest.mark.parametrize("rule,expected", [("highest_score", "B role"), ("campaign_priority_then_score", "A role")])
async def test_cross_campaign_setting_both_ways(session, rule, expected):
    rubric = await add_rubric(session)
    camp_a = await add_campaign(session, rubric, name="Priority", priority=10)
    camp_b = await add_campaign(session, rubric, name="Other", priority=0)
    a_job = await add_job(session, "A role")
    b_job = await add_job(session, "B role")
    await scored(session, a_job, camp_a, 70)
    await scored(session, b_job, camp_b, 90)
    await setting(session, "matching.conflict_winner", rule)
    await resolve(session, a_job, b_job)
    winner = a_job if expected == "A role" else b_job
    loser = b_job if winner is a_job else a_job
    assert winner.conflict_state == ConflictState.winner and loser.conflict_state == ConflictState.held
    assert f"matching.conflict_winner={rule}" in winner.conflict_note  # which rule chose it (18.6 item 3)


async def test_ties_go_to_preferred_seniority_then_later_deadline_then_newer_posting(session):
    campaign = await add_campaign(session, await add_rubric(session), preferred_seniority="senior")
    mid = await add_job(session, "Analyst", level="mid")
    senior = await add_job(session, "Senior Analyst", level="senior")
    await scored(session, mid, campaign, 80)
    await scored(session, senior, campaign, 80)
    await resolve(session, mid, senior)
    assert senior.conflict_state == ConflictState.winner
    early = await add_job(session, "Analyst A", employer="Tie Example", deadline=NOW.date() + timedelta(days=5))
    late = await add_job(session, "Analyst B", employer="Tie Example", deadline=NOW.date() + timedelta(days=50))
    await scored(session, early, campaign, 80)
    await scored(session, late, campaign, 80)
    await resolve(session, early, late)
    assert late.conflict_state == ConflictState.winner
    old = await add_job(session, "Analyst C", employer="Posted Example", posted_at=NOW - timedelta(days=9))
    new = await add_job(session, "Analyst D", employer="Posted Example", posted_at=NOW - timedelta(days=1))
    await scored(session, old, campaign, 80)
    await scored(session, new, campaign, 80)
    await resolve(session, old, new)
    assert new.conflict_state == ConflictState.winner


@pytest.mark.parametrize("prepared", [Stage.tailoring, Stage.ready])
async def test_edited_or_approved_winner_is_not_displaced_silently(session, prepared):
    """``tailoring``: the owner is editing; ``ready``: prepared and awaiting or holding approval."""
    campaign = await add_campaign(session, await add_rubric(session))
    current = await add_job(session, "Senior Analyst")
    await scored(session, current, campaign, 80)
    await resolve(session, current)
    session.add(Application(job_id=current.id, campaign_id=campaign.id, stage=prepared))
    await session.flush()
    challenger = await add_job(session, "Head of Analytics")
    await scored(session, challenger, campaign, 95)
    await resolve(session, current, challenger)
    assert current.conflict_state == ConflictState.winner and challenger.conflict_state == ConflictState.held
    action = await session.scalar(select(PendingAction).where(PendingAction.type == PendingActionType.conflict_choice))
    assert action.detail["current"]["job_id"] == str(current.id)
    assert action.detail["challenger"]["job_id"] == str(challenger.id)
    await resolve(session, current, challenger)  # resolving again does not raise a second action
    assert len((await session.scalars(select(PendingAction))).all()) == 1


@pytest.mark.parametrize("scope,expected", [
    ("same_department", {"Finance Lead": "winner", "IT Lead": "winner"}),
    ("whole_employer", {"Finance Lead": "winner", "IT Lead": "held"}),
    ("off", {"Finance Lead": "none", "IT Lead": "none"}),
])
async def test_different_departments_under_each_scope(session, scope, expected):
    await setting(session, "matching.roles_per_employer_scope", scope)
    campaign = await add_campaign(session, await add_rubric(session))
    fin = await add_job(session, "Finance Lead", function="finance")
    it = await add_job(session, "IT Lead", function="it")
    await scored(session, fin, campaign, 90)
    await scored(session, it, campaign, 80)
    await resolve(session, fin, it)
    assert {fin.title: fin.conflict_state.value, it.title: it.conflict_state.value} == expected


async def test_unknown_function_counts_as_same_department(session):
    campaign = await add_campaign(session, await add_rubric(session))
    fin = await add_job(session, "Finance Lead", function="finance")
    unknown = await add_job(session, "Lead", function=None)
    await scored(session, fin, campaign, 70)
    await scored(session, unknown, campaign, 85)
    await resolve(session, fin, unknown)
    assert unknown.conflict_state == ConflictState.winner and fin.conflict_state == ConflictState.held


async def test_release_one_held_role_is_audited(session):
    campaign = await add_campaign(session, await add_rubric(session))
    a, b = await add_job(session, "One"), await add_job(session, "Two")
    await scored(session, a, campaign, 90)
    await scored(session, b, campaign, 80)
    await resolve(session, a, b)
    await conflicts.release_held(session, b, actor="owner", reason="I want both")
    await resolve(session, a, b)
    assert b.conflict_state == ConflictState.released and a.conflict_state == ConflictState.winner
    event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "conflict.released"))
    assert event.detail["reason"] == "I want both"
    with pytest.raises(ValueError):
        await conflicts.release_held(session, a, actor="owner", reason="not held")


async def _app(session, job, stage, *, applied_days_ago=None, ended_days_ago=None) -> Application:
    app = Application(job_id=job.id, stage=stage,
                      applied_at=NOW - timedelta(days=applied_days_ago) if applied_days_ago is not None else None,
                      ended_at=NOW - timedelta(days=ended_days_ago) if ended_days_ago is not None else None)
    session.add(app)
    await session.flush()
    return app


@pytest.mark.parametrize("existing,max_live,passes", [
    # Live from applying until an end state, however long it lasts.
    (dict(stage=Stage.interview, applied_days_ago=200), 1, False),
    (dict(stage=Stage.submitted_unconfirmed, applied_days_ago=200), 1, False),
    (dict(stage=Stage.interview, applied_days_ago=200), 2, True),   # a reply: no cooldown, under the cap
    # No reply: the cooldown runs from the applied date.
    (dict(stage=Stage.submitted, applied_days_ago=10), 2, False),
    (dict(stage=Stage.submitted, applied_days_ago=40), 2, True),
    # Ended: the cooldown runs from the end state.
    (dict(stage=Stage.rejected, applied_days_ago=90, ended_days_ago=10), 1, False),
    (dict(stage=Stage.rejected, applied_days_ago=90, ended_days_ago=40), 1, True),
    # Skipped before applying never counts.
    (dict(stage=Stage.skipped), 1, True),
])
async def test_live_count_and_cooldown_examples(session, existing, max_live, passes):
    if max_live != 1:
        await setting(session, "matching.max_live_per_employer", max_live)
    campaign = await add_campaign(session, await add_rubric(session))
    earlier = await add_job(session, "Earlier role", function="other")
    await _app(session, earlier, **existing)
    target = await add_job(session, "New role", function="analytics")
    await scored(session, target, campaign, 90)
    target.conflict_state = ConflictState.winner
    app = await _app(session, target, Stage.ready)
    gate = await conflicts.check_conflict_at_submit(session, app, now=NOW)
    assert (gate.outcome == "pass") is passes, gate.reason
    assert gate.rules and gate.rules[0].source == "setting"
    assert app.stage == (Stage.applying if passes else Stage.ready)


async def test_group_locked_after_applying_and_better_role_raises_pending_action(session):
    campaign = await add_campaign(session, await add_rubric(session))
    applied = await add_job(session, "Senior Analyst")
    a = await scored(session, applied, campaign, 75)
    app = await _app(session, applied, Stage.submitted, applied_days_ago=3)
    app.assessment_id = a.id
    better = await add_job(session, "Lead Analyst")
    await scored(session, better, campaign, 92)
    await resolve(session, applied, better)
    assert better.conflict_state == ConflictState.held and "already applied to Senior Analyst" in better.conflict_note
    action = await session.scalar(select(PendingAction))
    assert action.detail["kind"] == "better_role_after_applying"


async def test_two_concurrent_submit_checks_cannot_both_pass():
    maker = get_sessionmaker()
    async with maker() as s:
        campaign = await add_campaign(s, await add_rubric(s))
        one, two = await add_job(s, "Role One"), await add_job(s, "Role Two", function="other")
        one.conflict_state = ConflictState.winner
        two.conflict_state = ConflictState.released
        apps = [Application(job_id=one.id, campaign_id=campaign.id, stage=Stage.ready),
                Application(job_id=two.id, campaign_id=campaign.id, stage=Stage.ready)]
        s.add_all(apps)
        await s.commit()
        ids = [a.id for a in apps]

    async def attempt(app_id):
        async with maker() as s:
            app = await s.get(Application, app_id)
            gate = await conflicts.check_conflict_at_submit(s, app, now=NOW)
            await asyncio.sleep(0.2)  # hold the lock while the other runner waits
            await s.commit()
            return gate.outcome

    outcomes = await asyncio.gather(attempt(ids[0]), attempt(ids[1]))
    assert sorted(outcomes) == ["fail", "pass"]
    async with maker() as s:
        stages = sorted((await s.scalars(select(Application.stage))).all())
        assert stages.count(Stage.applying) == 1


async def test_recruiter_postings_grouped_by_title_and_flagged(session):
    campaign = await add_campaign(session, await add_rubric(session))
    direct = await add_job(session, "Senior Data Analyst", employer="Direct Example")
    r1 = await add_job(session, "Senior Data Analyst", employer="Agency Example", recruiter="Agency Example")
    r2 = await add_job(session, "Senior Data Analyst, Lusaka", employer="Agency Example",
                       recruiter="Agency Example")
    r3 = await add_job(session, "Warehouse Supervisor", employer="Agency Example", recruiter="Agency Example")
    for job, score in ((direct, 80), (r1, 85), (r2, 70), (r3, 60)):
        await scored(session, job, campaign, score)
    await resolve(session, direct, r1, r2, r3)
    assert r1.conflict_state == ConflictState.winner and r2.conflict_state == ConflictState.held
    assert r3.conflict_state == ConflictState.winner  # a different vacancy at the same agency
    assert conflicts.RECRUITER_FLAG_TAG in r1.tags and "Direct Example" in r1.conflict_note
    assert conflicts.RECRUITER_FLAG_TAG not in r3.tags
    assert (await session.get(Job, direct.id)).conflict_state == ConflictState.winner


async def test_dry_run_reports_a_tie_instead_of_raising_a_pending_action(session):
    from app.models.search import Run, RunKind, RunStatus
    from app.pipeline import dry_run

    campaign = await add_campaign(session, await add_rubric(session))
    current = await add_job(session, "Senior Analyst")
    await scored(session, current, campaign, 80)
    await resolve(session, current)
    session.add(Application(job_id=current.id, campaign_id=campaign.id, stage=Stage.ready))
    await session.flush()
    challenger = await add_job(session, "Head of Analytics")
    await scored(session, challenger, campaign, 95)

    sink: list = []
    await conflicts.resolve_employers(session, {current.canonical_employer}, now=NOW, sink=sink)
    assert (await session.scalars(select(PendingAction))).all() == []  # a dry run raises nothing
    assert len(sink) == 1 and sink[0]["detail"]["kind"] == "displace_prepared"
    proposals = dry_run.choice_proposals(sink)
    assert proposals[0]["action"] == "ask_owner" and proposals[0]["job_id"] == str(challenger.id)

    # the same through the scoring entry point of a dry-run run: reported on the run, no pending action
    from app.pipeline import scoring
    from tests.pipeline.matching.fakes import FakeLLMClient, add_facts, ratings

    await add_facts(session, "F-1", "F-2")
    campaign2 = await add_campaign(session, await add_rubric(session), name="Second")
    first = await add_job(session, "Senior Analyst", employer="Dry Example")
    await scoring.score_jobs(session, None, [first.id], campaign_ids=[campaign2.id], now=NOW,
                             client=FakeLLMClient(ratings({"skills": 4, "domain": 4})))
    session.add(Application(job_id=first.id, campaign_id=campaign2.id, stage=Stage.ready))
    await session.flush()
    second = await add_job(session, "Head of Analytics", employer="Dry Example")
    run = Run(kind=RunKind.sweep, trigger="manual", dry_run=True, status=RunStatus.running,
              campaign_id=campaign2.id)
    session.add(run)
    await session.flush()
    await scoring.score_jobs(session, run, [second.id], now=NOW,
                             client=FakeLLMClient(ratings({"skills": 5, "domain": 5})))
    assert (await session.scalars(select(PendingAction))).all() == []
    assert len(run.config_versions["dry_run_choices"]) == 1
