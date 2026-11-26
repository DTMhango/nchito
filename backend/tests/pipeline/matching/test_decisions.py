"""The decision table: precedence, unknown is not yes, pay and deadline states, structured reasons."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.conditions import CampaignRule, ConditionSet, Group, ValueFilter
from app.pipeline.decisions import decide
from tests.pipeline.matching.helpers import NOW, campaign, counters, data, default_settings, job

pytestmark = pytest.mark.nodb


def _rule(effect: str, facet: str, value: str, points: int | None = None) -> dict:
    cs = ConditionSet(root=Group(conditions=[ValueFilter(facet=facet, include=[value])]))
    return CampaignRule(effect=effect, conditions=cs, points=points, reason=f"{effect} {value}").model_dump()


def _gate(decision, name):
    return next(g for g in decision.gates if g.gate == name)


def test_happy_path_auto_applies_with_reasons():
    d = decide(data())
    assert d.verdict == "auto_apply" and d.auto_apply_allowed, [g for g in d.blocking]
    score = _gate(d, "score")
    assert any(r.source == "setting" and r.rule == "scoring.threshold_shortlist" for r in score.rules)
    assert all(g.reason for g in d.gates)


def test_a_100_score_cannot_rescue_an_excluded_role():
    camp = campaign(criteria={"rules": [_rule("exclude", "facets.relocation_required", "no")]})
    d = decide(data(camp=camp, score=100))
    assert d.verdict == "excluded" and not d.auto_apply_allowed
    gate = _gate(d, "rule:0")
    assert gate.outcome == "fail" and gate.layer == "exclusion"
    assert gate.rules[0].source == "campaign" and gate.rules[0].version == camp["version"]
    # An override score cannot rescue it either.
    d2 = decide(data(camp=camp, score=100, override={"by": "owner", "reason": "I like it", "score": 100}))
    assert d2.verdict == "excluded"


def test_ineligible_role_is_excluded_regardless_of_score():
    d = decide(data(job_rec=job(facets={"work_model": "on_site"}),
                    camp=campaign(criteria={"work_models": ["remote"]}), score=100))
    assert d.verdict == "excluded"


def test_passed_deadline_excludes_but_open_until_filled_passes():
    past = decide(data(job_rec=job(deadline=NOW.date() - timedelta(days=1))))
    assert past.verdict == "excluded" and _gate(past, "deadline_passed").outcome == "fail"
    open_ended = decide(data(job_rec=job(deadline_state="open_until_filled", deadline=None)))
    assert _gate(open_ended, "deadline").outcome == "pass" and open_ended.verdict == "auto_apply"


POLICIES = ("review", "pass_with_penalty", "pass_blocks_auto", "fail")
UNKNOWN_CASES = {
    "pay": dict(job_rec=job(pay_state="not_stated", pay={}), gate="pay_floor"),
    "eligibility": dict(job_rec=job(facets={"work_rights": "not_stated"}), gate="work_rights"),
    "deadline": dict(job_rec=job(deadline_state="not_stated", deadline=None), gate="deadline"),
}
EXPECTED_VERDICT = {"review": "review", "pass_with_penalty": "ask_owner", "pass_blocks_auto": "ask_owner",
                    "fail": "excluded"}


@pytest.mark.parametrize("kind", sorted(UNKNOWN_CASES))
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("source", ["campaign", "setting"])
def test_unknown_is_never_yes(kind, policy, source):
    case = UNKNOWN_CASES[kind]
    if source == "campaign":
        camp, settings = campaign(unknown_data_policy={kind: policy}), default_settings()
    else:
        camp, settings = campaign(), default_settings(**{f"scoring__unknown_{kind}": policy})
    d = decide(data(job_rec=case["job_rec"], camp=camp, settings=settings, score=95))
    gate = _gate(d, case["gate"])
    assert not d.auto_apply_allowed
    assert d.verdict == EXPECTED_VERDICT[policy], (policy, d.verdict, d.blocking)
    assert gate.outcome == ("fail" if policy == "fail" else "unknown")
    ref = gate.rules[-1] if policy != "pass_with_penalty" else gate.rules[-2]
    assert ref.source == source and ref.effective_value == policy
    if policy == "pass_with_penalty":
        assert d.effective_score == 95 - default_settings()["scoring.unknown_penalty"]
    else:
        assert d.effective_score == 95
    if policy in ("pass_with_penalty", "pass_blocks_auto"):
        assert _gate(d, "known_data").outcome == "unknown"


def test_pay_estimated_and_not_stated_behave_differently():
    camp = campaign(unknown_data_policy={"pay": "fail"})
    estimate = {"min_minor": 45_000_00, "max_minor": 55_000_00, "currency": "USD", "period": "year",
                "source": "salary survey (example)", "estimated_on": date(2026, 11, 1)}
    estimated = decide(data(job_rec=job(pay_state="estimated", pay={}, pay_estimate=estimate), camp=camp))
    not_stated = decide(data(job_rec=job(pay_state="not_stated", pay={}), camp=camp))
    # Estimated at or above the floor passes the filter (non-mandatory unknown) but blocks auto-apply.
    eg = _gate(estimated, "pay_floor")
    assert eg.outcome == "unknown" and not eg.mandatory and estimated.verdict == "ask_owner"
    assert eg.rules[0].source.startswith("estimate:") and eg.rules[0].version == "2026-11-01"
    assert _gate(estimated, "pay_stated").outcome == "unknown"
    # Not stated falls to the policy (fail here).
    assert _gate(not_stated, "pay_floor").outcome == "fail" and not_stated.verdict == "excluded"
    # An estimate below the floor also falls to the policy, never silently passes.
    low = dict(estimate, max_minor=30_000_00, min_minor=25_000_00)
    below = decide(data(job_rec=job(pay_state="estimated", pay={}, pay_estimate=low), camp=camp))
    assert below.verdict == "excluded" and "estimated pay is below" in _gate(below, "pay_floor").reason


def test_stated_pay_below_floor_fails_and_different_currency_is_unknown():
    low = decide(data(job_rec=job(pay={"min_minor": 1, "max_minor": 2, "currency": "USD", "period": "year"})))
    assert low.verdict == "excluded" and _gate(low, "pay_floor").outcome == "fail"
    zmw = decide(data(job_rec=job(pay={"min_minor": 1, "max_minor": 9_999_999_00, "currency": "ZMW",
                                       "period": "year"})))
    assert _gate(zmw, "pay_floor").outcome == "unknown" and not zmw.auto_apply_allowed


def test_scoring_layers_and_mode_ceiling():
    assert decide(data(score=None)).verdict == "review"
    assert decide(data(score=10)).verdict == "below_threshold"
    assert decide(data(score=65)).verdict == "shortlist"
    prepare = decide(data(camp=campaign(automation={"mode": "prepare"}), score=95))
    assert prepare.verdict == "tailor"
    unconfirmed = decide(data(camp=campaign(review_state="needs_review", confirmed=False), score=95))
    assert unconfirmed.mode == "prepare" and unconfirmed.verdict == "tailor" and not unconfirmed.auto_apply_allowed


def test_penalty_and_bonus_rules_adjust_score_with_reasons():
    camp = campaign(criteria={"rules": [_rule("penalty", "facets.relocation_required", "no", 30),
                                        _rule("bonus", "facets.visa_sponsorship", "yes", 2)]})
    d = decide(data(camp=camp, score=90))
    assert d.effective_score == 62
    assert {g.reason.split(":")[0] for g in d.gates if g.layer == "score" and g.gate.startswith("rule:")} == {
        "penalty -30", "bonus +2"}


@pytest.mark.parametrize("name,kwargs", [
    ("global_pause", dict(settings=default_settings(automation__paused=True))),
    ("daily_cap", dict(counters=counters(sent_today=5))),
    ("conflict_winner", dict(conflict_state="held")),
    ("role_open", dict(job_rec=job(last_checked_at=NOW - timedelta(days=3)))),
    ("always_ask_first", dict(job_rec=job(always_ask_first=True))),
    ("employer_live", dict(counters=counters(employer_live=1))),
])
def test_each_automation_gate_blocks(name, kwargs):
    d = decide(data(**kwargs))
    assert not d.auto_apply_allowed and _gate(d, name).outcome != "pass"


def test_quiet_hours_use_owner_timezone():
    late = NOW.replace(hour=20)  # 22:00 in Lusaka
    d = decide(data().__class__(**{**data().__dict__, "now": late}))
    assert _gate(d, "quiet_hours").outcome == "fail" and not d.auto_apply_allowed


def test_permit_purpose_without_permit_checks_is_not_granted():
    d = decide(data(purpose="permit"))
    assert _gate(d, "permit_checks").outcome == "unknown" and not d.auto_apply_allowed
