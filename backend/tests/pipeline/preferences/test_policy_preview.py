"""Policy preview: the decision table over recent roles, equal to a real dry run, unknown never yes."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.models.platform import AuditEvent
from app.models.search import Assessment, Campaign
from app.pipeline import dry_run, policy_preview
from app.schemas.json_types import AutomationPolicy, RubricThresholds
from tests.pipeline.matching.helpers import NOW
from tests.pipeline.preferences.data import campaign_with_rubric, scored_job

HIGH = {"skills": 5, "domain": 5, "growth": 4, "Seniority fit": 4}  # 92
GOOD = {"skills": 4, "domain": 4, "growth": 4, "Seniority fit": 4}  # 80
MID = {"skills": 4, "domain": 3, "growth": 3, "Seniority fit": 3}  # 66
STATED = {"pay_state": "stated", "pay_min_minor": 50_000_00, "pay_max_minor": 60_000_00, "pay_currency": "USD",
          "pay_period": "year"}


async def _seed(*, mode: str = "auto_apply"):
    """Six roles: three fully known (two high, one good), one high with pay not stated, one mid, one held."""
    async with get_sessionmaker()() as s:
        campaign, rubric = await campaign_with_rubric(s, mode=mode)
        jobs = {
            "A": await scored_job(s, campaign, rubric, "A", HIGH, apply_method="email", days_ago=1, **STATED),
            "B": await scored_job(s, campaign, rubric, "B", HIGH, apply_method="greenhouse", days_ago=1, **STATED),
            "C": await scored_job(s, campaign, rubric, "C", GOOD, apply_method="email", days_ago=2, **STATED),
            "U": await scored_job(s, campaign, rubric, "U", HIGH, apply_method="email", days_ago=2),
            "M": await scored_job(s, campaign, rubric, "M", MID, apply_method="email", days_ago=3, **STATED),
            "H": await scored_job(s, campaign, rubric, "H", HIGH, apply_method="email", days_ago=3, conflict="held",
                                  conflict_note="outranked by Role A", **STATED),
            "OLD": await scored_job(s, campaign, rubric, "OLD", HIGH, days_ago=90, **STATED),
        }
        await s.commit()
        return campaign.id, {k: j.id for k, j in jobs.items()}


async def _preview(campaign_id, proposal=None, **kw) -> policy_preview.PreviewResult:
    async with get_sessionmaker()() as s:
        campaign = await s.get(Campaign, campaign_id)
        return await policy_preview.preview(s, campaign, proposal or policy_preview.Proposal(), now=NOW, **kw)


async def test_preview_equals_a_real_dry_run_on_the_same_data():
    campaign_id, ids = await _seed()
    for settings in ({}, {"automation.daily_cap": 1}):
        result = await _preview(campaign_id, policy_preview.Proposal(settings=settings))
        async with get_sessionmaker()() as s:
            from app.core.settings import service

            if settings:
                await service.set_value(s, "automation.daily_cap", 1, actor="owner")
            campaign = await s.get(Campaign, campaign_id)
            real = await dry_run.propose_actions(s, campaign, [r.job.id for r in result.rows], now=NOW, limit=100)
            await s.rollback()
        assert [(str(r.job.id), r.action, r.reason, r.score) for r in result.rows] == \
            [(p["job_id"], p["action"], p["reason"], p["score"]) for p in real]
    assert {r.job.id for r in result.rows} == {v for k, v in ids.items() if k != "OLD"}  # the window


async def test_the_line_counts_automatic_roles_by_channel_and_held_runner_ups():
    campaign_id, _ = await _seed()
    result = await _preview(campaign_id)
    assert result.thresholds == {"shortlist": 60, "tailor": 70, "auto_apply": 85}
    assert result.line.qualifying == 2 and result.line.would_apply == 2
    assert result.line.by_channel == {"email": 1, "browser": 1, "other": 0}
    assert result.line.held == 1
    assert result.run_now["apply"] == 2
    unknowns = {u.gate: u for u in result.unknowns}
    assert unknowns["pay_stated"].count == 1
    assert unknowns["pay_stated"].message == "1 role has unknown pay: it will never go automatically."
    assert sum(n for _, _, n in result.bins) == 6 and result.unscored == 0
    assert [n for lo, _, n in result.bins if lo == 90] == [4]  # A, B, U and the held H


async def test_unknown_pay_never_counts_however_low_the_threshold():
    campaign_id, ids = await _seed()
    result = await _preview(campaign_id, policy_preview.Proposal(
        thresholds=RubricThresholds(shortlist=50, tailor=50, auto_apply=50)))
    qualifying = {r.job.id for r in result.rows if r.qualifies}
    assert ids["U"] not in qualifying and ids["H"] not in qualifying
    assert qualifying == {ids["A"], ids["B"], ids["C"], ids["M"]}
    unknown_pay = next(r for r in result.rows if r.job.id == ids["U"])
    assert unknown_pay.action == "ask_owner" and not unknown_pay.qualifies


async def test_lowering_the_threshold_lists_newly_automatic_roles_with_reasons():
    campaign_id, ids = await _seed()
    result = await _preview(campaign_id, policy_preview.Proposal(thresholds=RubricThresholds(auto_apply=75)))
    assert result.baseline_line.would_apply == 2 and result.line.would_apply == 3
    newly = [c for c in result.changes if c.kind == "newly_automatic"]
    assert [c.outcome.job.id for c in newly] == [ids["C"]]
    assert newly[0].reasons == ["score 80 < auto-apply threshold 85"]


async def test_mode_change_blocks_with_the_mode_named():
    campaign_id, ids = await _seed()
    result = await _preview(campaign_id, policy_preview.Proposal(automation=AutomationPolicy(mode="prepare")))
    blocked = [c for c in result.changes if c.kind == "newly_blocked"]
    assert {c.outcome.job.id for c in blocked} == {ids["A"], ids["B"]}
    assert all(c.reasons[0] == "effective mode prepare" for c in blocked)
    assert result.line.would_apply == 0 and result.run_now.get("apply", 0) == 0


async def test_caps_apply_day_by_day_and_quiet_hours_are_reported():
    campaign_id, _ = await _seed()
    result = await _preview(campaign_id, policy_preview.Proposal(
        thresholds=RubricThresholds(auto_apply=75),
        settings={"automation.daily_cap": 1, "automation.quiet_hours_start": "11:00",
                  "automation.quiet_hours_end": "13:00"}))
    # A and B were found the same day: the cap of one a day holds one back; C was found the day before.
    assert result.line.qualifying == 3 and result.line.would_apply == 2 and result.line.capped == 1
    assert result.caps.quiet_hours == "11:00-13:00" and result.caps.quiet_now is True  # 12:00 in Lusaka
    assert result.caps.run_now_would_send == 0  # a run now would wait for the quiet hours to end


async def test_bad_proposals_are_refused_and_nothing_is_written():
    campaign_id, _ = await _seed()
    import pytest

    for proposal in (policy_preview.Proposal(settings={"automation.paused": True}),
                     policy_preview.Proposal(settings={"automation.daily_cap": 50, "automation.weekly_cap": 10}),
                     policy_preview.Proposal(thresholds=RubricThresholds(tailor=90, auto_apply=80))):
        with pytest.raises(policy_preview.PreviewError):
            await _preview(campaign_id, proposal)
    await _preview(campaign_id, policy_preview.Proposal(thresholds=RubricThresholds(shortlist=50, tailor=50,
                                                                                      auto_apply=50)))
    async with get_sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(AuditEvent)) == 0
        assert {a.score for a in (await s.scalars(select(Assessment))).all()} == {92, 80, 66}


async def test_window_is_bounded_by_days():
    campaign_id, ids = await _seed()
    result = await _preview(campaign_id, days=2)
    assert {r.job.id for r in result.rows} == {ids["A"], ids["B"], ids["C"], ids["U"]}
    assert result.window_days == 2 and NOW - timedelta(days=2) < NOW
