"""Permit-time gates in the decision table (pure; DESIGN.md 8.1, CONTRACTS.md 10)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.conditions import CampaignRule, ConditionSet, Group, ValueFilter
from app.pipeline.decisions import decide, resolve_mode
from tests.pipeline.matching.helpers import campaign, counters, data, default_settings, job

pytestmark = pytest.mark.nodb

ALL_PASS = {"packet_current": ("pass", "ok"), "approval_bound": ("pass", "ok"), "duplicate": ("pass", "ok")}


def permit(approval="auto", channel="email", checks=None, **kw):
    app = {"approval": approval, "channel": channel, "permit_checks": ALL_PASS if checks is None else checks}
    return decide(data(purpose="permit", application=app, **kw))


def test_all_gates_pass_grants_an_automatic_permit():
    d = permit()
    assert d.permit == "granted", d.permit_reason


def test_a_100_score_cannot_rescue_an_excluded_role_at_permit_time():
    cs = ConditionSet(root=Group(conditions=[ValueFilter(facet="facets.relocation_required", include=["no"])]))
    rule = CampaignRule(effect="exclude", conditions=cs, reason="no relocation roles").model_dump()
    camp = campaign(criteria={"rules": [rule]})
    for approval in ("auto", "owner"):
        d = permit(approval, camp=camp, score=100)
        assert d.verdict == "excluded"
        assert d.permit == "denied" and d.permit_reason.startswith("excluded")


def test_unknown_is_not_yes():
    unknown_pay = job(pay_state="not_stated", pay={"min_minor": None, "max_minor": None, "currency": None,
                                                    "period": None})
    d = permit("auto", job_rec=unknown_pay)
    assert d.permit == "wait_for_owner" and "pay" in d.permit_reason
    # An unknown permit check is never a pass, whoever approved.
    d = permit("owner", checks={**ALL_PASS, "duplicate": ("unknown", "could not tell")})
    assert d.permit == "denied" and "duplicate" in d.permit_reason
    # Without the permit-time checks there is no permit.
    assert permit("owner", checks={}).permit == "denied"


def test_no_approval_no_permit():
    assert permit(None).permit == "denied"


def test_owner_settles_judgement_gates_but_not_hard_ones():
    owner_settled = {**ALL_PASS, "trusted_site": ("unknown", "not trusted", True)}
    assert permit("auto", channel="browser", checks=owner_settled).permit == "wait_for_owner"
    assert permit("owner", camp=campaign(automation={"mode": "ask_then_apply"}), channel="browser",
                  checks=owner_settled).permit == "granted"
    assert permit("owner", conflict_state="held").permit == "denied"


def test_owner_approval_in_prepare_mode_only_for_the_manual_channel():
    camp = campaign(automation={"mode": "prepare"})
    assert permit("owner", camp=camp).permit == "denied"
    assert permit("owner", camp=camp, channel="manual").permit == "granted"


@pytest.mark.parametrize("cap_key,counter", [("automation.daily_cap", "sent_today"),
                                             ("automation.weekly_cap", "sent_week")])
def test_caps_at_default_and_another_value(cap_key, counter):
    defaults = default_settings()
    cap = defaults[cap_key]
    assert permit(counters=counters(**{counter: cap - 1})).permit == "granted"
    d = permit(counters=counters(**{counter: cap}))
    assert d.permit == "denied" and cap_key.split(".")[1] in d.permit_reason
    lower = default_settings(**{cap_key.replace(".", "__"): 3})
    assert permit(settings=lower, counters=counters(**{counter: 3})).permit == "denied"
    assert permit(settings=lower, counters=counters(**{counter: 2})).permit == "granted"


def test_quiet_hours_in_owner_time_zone_at_default_and_another_value():
    late = datetime(2026, 11, 26, 20, 0, tzinfo=UTC)  # 22:00 in Lusaka
    base = data(purpose="permit", application={"approval": "auto", "channel": "email", "permit_checks": ALL_PASS})
    import dataclasses

    at_late = dataclasses.replace(base, now=late, job={**base.job, "last_checked_at": late})
    d = decide(at_late)
    assert d.permit == "denied" and "quiet_hours" in d.permit_reason
    later_start = default_settings(automation__quiet_hours_start="22:30")
    assert decide(dataclasses.replace(at_late, settings=later_start)).permit == "granted"
    other_zone = default_settings(general__timezone="UTC")  # 20:00 UTC, before 21:00
    assert decide(dataclasses.replace(at_late, settings=other_zone)).permit == "granted"


def test_global_pause_denies():
    d = permit(settings=default_settings(automation__paused=True))
    assert d.permit == "denied" and "global_pause" in d.permit_reason


def test_for_approval_leaves_timing_gates_to_the_permit():
    app = {"approval": "auto", "channel": "email", "permit_checks": ALL_PASS, "for_approval": True}
    d = decide(data(purpose="permit", application=app, settings=default_settings(automation__paused=True)))
    assert d.permit == "granted"


def test_role_not_recently_open_follows_the_setting_for_owner_approvals():
    stale = job(last_checked_at=datetime(2026, 11, 1, tzinfo=UTC))
    camp = campaign(automation={"mode": "ask_then_apply"})
    assert permit("owner", job_rec=stale, camp=camp).permit == "denied"
    allow = default_settings(automation__permit_unknown_open="allow_when_owner_approved")
    assert permit("owner", job_rec=stale, camp=camp, settings=allow).permit == "granted"
    d = permit("auto", job_rec=stale, settings=allow)  # automatic approvals always need a recent check
    assert d.permit == "denied" and "role_open" in d.permit_reason


def test_mode_resolution_per_channel_with_reason():
    camp = campaign(automation={"mode": "prepare", "per_channel": {"email": "auto_apply"}})
    res = resolve_mode(camp, "email")
    assert res.mode == "auto_apply"
    assert "automation.per_channel.email" in res.reason and camp["version"] in res.reason
    assert resolve_mode(camp, "browser").mode == "prepare"
    unconfirmed = {**camp, "review_state": "needs_review"}
    res = resolve_mode(unconfirmed, "email")
    assert res.mode == "prepare" and "capped" in res.reason
    assert resolve_mode({"automation": {}}, None, default_mode="save_only").mode == "save_only"
    # The decision table uses the channel's mode.
    assert permit("auto", camp=camp, channel="browser").permit == "wait_for_owner"
    assert permit("auto", camp=camp, channel="email").permit == "granted"
