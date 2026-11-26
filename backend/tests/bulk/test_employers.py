"""Employers: the cooldown rule (both start rules, default and other settings, overrides), per-employer
overrides, ending a cooldown early, 'never apply' blocking tailoring and sending, merge and split."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.apply import stages
from app.core.settings import service as settings_service
from app.models.applications import Application, Stage
from app.models.platform import AuditEvent
from app.models.search import ConflictState, EmployerAlias, Job, WatchedEmployer
from app.pipeline import conflicts, employers, filters
from app.pipeline.decisions import decide
from app.pipeline.tailoring import service as tailoring_service
from tests.pipeline.matching.helpers import NOW, data
from tests.pipeline.matching.helpers import job as matching_job
from tests.tracking.helpers import make_app, make_job

ENDED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
APPLIED = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


async def _detail(session, key="acme ltd", now=NOW):
    return await employers.detail(session, key, now=now)


async def test_cooldown_runs_from_the_end_state_when_there_was_a_reply(session) -> None:
    job = await make_job(session, "Analyst", "Acme Ltd")
    await make_app(session, job, Stage.rejected, applied_at=APPLIED, ended_at=ENDED)
    d = await _detail(session)
    assert d.cooldown is not None and d.cooldown.kind == "end_state"
    assert d.cooldown.anchor == ENDED and d.cooldown.until == date(2026, 10, 31)  # 1 Oct + 30 days, not 20 Sep
    assert "ended (rejected) on 2026-10-01" in d.cooldown.text and "ends 2026-10-31" in d.cooldown.text
    assert d.days == 30 and d.days_source == "the default setting"


async def test_cooldown_runs_from_the_applied_date_when_there_was_no_reply(session) -> None:
    job = await make_job(session, "Analyst", "Acme Ltd")
    await make_app(session, job, Stage.submitted, applied_at=APPLIED)
    d = await _detail(session)
    assert d.cooldown is not None and d.cooldown.kind == "applied_date"
    assert d.cooldown.until == date(2026, 10, 20)
    assert "no reply" in d.cooldown.text


async def test_a_reply_in_progress_is_not_cooling_and_a_skip_never_counts(session) -> None:
    await make_app(session, await make_job(session, "A", "Acme Ltd"), Stage.interview, applied_at=APPLIED)
    await make_app(session, await make_job(session, "B", "Acme Ltd"), Stage.skipped)
    d = await _detail(session)
    assert d.cooldown is None  # interview is live with a reply: in progress, not cooling down
    assert d.row.state == "role_in_progress"


async def test_cooldown_maths_follow_the_setting_the_override_and_the_watched_employer(session) -> None:
    job = await make_job(session, "Analyst", "Acme Ltd")
    await make_app(session, job, Stage.rejected, applied_at=APPLIED, ended_at=ENDED)
    await settings_service.set_value(session, "matching.employer_cooldown_days", 45, actor="test")
    d = await _detail(session)
    assert d.cooldown.until == date(2026, 11, 15) and d.days == 45  # another setting value

    session.add(WatchedEmployer(name="Acme Ltd", board_type="greenhouse", board_slug="acme", cooldown_days=60))
    await session.flush()
    d = await _detail(session)
    assert d.cooldown.until == date(2026, 11, 30) and d.days_source == "the watched employer's own"

    await employers.update_policy(session, "acme ltd", {"cooldown_days": 10}, actor="owner")
    d = await _detail(session)
    assert d.cooldown.until == date(2026, 10, 11) and d.days_source == "this employer's override"
    assert d.row.state == "free"  # the 10-day cooldown is over by 26 Nov

    await employers.update_policy(session, "acme ltd", {"cooldown_days": 0}, actor="owner")
    assert (await _detail(session)).cooldown.until == date(2026, 10, 1)  # zero days: ends the day it started


async def test_the_override_reaches_the_submit_gate(session) -> None:
    job = await make_job(session, "Analyst", "Acme Ltd")
    await make_app(session, job, Stage.rejected, applied_at=NOW - timedelta(days=20), ended_at=NOW - timedelta(days=15))
    nxt = await make_app(session, await make_job(session, "Manager", "Acme Ltd"), Stage.ready)
    (await session.get(Job, nxt.job_id)).conflict_state = ConflictState.winner  # unscored: no contest to run
    gate = await conflicts.check_conflict_at_submit(session, nxt, now=NOW, claim=False)
    assert gate.outcome == "fail" and "cooldown until" in gate.reason  # 15 days into a 30 day cooldown

    await employers.update_policy(session, "acme ltd", {"cooldown_days": 14}, actor="owner")
    gate = await conflicts.check_conflict_at_submit(session, nxt, now=NOW, claim=False)
    assert gate.outcome == "pass"


async def test_ending_a_cooldown_early_needs_a_reason_is_audited_and_frees_the_employer(session) -> None:
    await make_app(session, await make_job(session, "Analyst", "Acme Ltd"), Stage.rejected,
                   applied_at=NOW - timedelta(days=20), ended_at=NOW - timedelta(days=15))
    nxt = await make_app(session, await make_job(session, "Manager", "Acme Ltd"), Stage.ready)
    (await session.get(Job, nxt.job_id)).conflict_state = ConflictState.winner
    assert (await _detail(session)).row.state == "cooling_down"

    with pytest.raises(employers.EmployerError) as err:
        await employers.end_cooldown(session, "acme ltd", reason="  ", actor="owner", now=NOW)
    assert err.value.code == "reason_required"
    await employers.end_cooldown(session, "acme ltd", reason="Recruiter asked me to re-apply", actor="owner", now=NOW)
    d = await _detail(session)
    assert d.cooldown is None and d.row.state == "free"
    assert d.released_reason == "Recruiter asked me to re-apply" and d.released_by == "owner"
    assert (await conflicts.check_conflict_at_submit(session, nxt, now=NOW, claim=False)).outcome == "pass"
    event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "employer.cooldown_ended"))
    assert event.detail["reason"] == "Recruiter asked me to re-apply" and event.detail["rule"] == "end_state"
    with pytest.raises(employers.EmployerError) as err:  # nothing is running now
        await employers.end_cooldown(session, "acme ltd", reason="again", actor="owner", now=NOW)
    assert err.value.code == "no_cooldown"
    # a later application starts a fresh cooldown that the earlier release does not cover
    await make_app(session, await make_job(session, "Third", "Acme Ltd"), Stage.rejected,
                   applied_at=NOW + timedelta(days=1), ended_at=NOW + timedelta(days=2))
    assert (await _detail(session, now=NOW + timedelta(days=3))).cooldown is not None


async def test_employer_states(session) -> None:
    await make_job(session, "Free role", "Free Co")
    await make_app(session, await make_job(session, "A", "Busy Co"), Stage.submitted,
                   applied_at=NOW - timedelta(days=1))
    await make_app(session, await make_job(session, "B", "Cold Co"), Stage.withdrawn,
                   applied_at=NOW - timedelta(days=9), ended_at=NOW - timedelta(days=2))
    await make_job(session, "Ask role", "Ask Co")
    await make_job(session, "Never role", "Never Co")
    await employers.update_policy(session, "ask co", {"always_ask_first": True}, actor="owner")
    await employers.update_policy(session, "never co", {"never_apply": True, "never_reason": "conflict of interest"},
                                  actor="owner")
    rows = {r.name: r for r in await employers.overview(session, now=NOW)}
    assert {n: r.state for n, r in rows.items()} == {
        "Free Co": "free", "Busy Co": "role_in_progress", "Cold Co": "cooling_down", "Ask Co": "always_ask_first",
        "Never Co": "blocked"}
    assert rows["Cold Co"].cooldown_until == (NOW - timedelta(days=2) + timedelta(days=30)).date()
    assert rows["Busy Co"].applications == 1 and rows["Busy Co"].last_applied_at == NOW - timedelta(days=1)
    assert rows["Never Co"].state_text == "never apply: conflict of interest"


async def test_never_apply_needs_a_reason(session) -> None:
    await make_job(session, "A", "Acme Ltd")
    with pytest.raises(employers.EmployerError) as err:
        await employers.update_policy(session, "acme ltd", {"never_apply": True}, actor="owner")
    assert err.value.code == "reason_required"
    await employers.update_policy(session, "acme ltd", {"never_apply": True, "never_reason": "no"}, actor="owner")
    await employers.update_policy(session, "acme ltd", {"never_apply": False}, actor="owner")
    pol = await employers.policy_for(session, "acme ltd")
    assert pol.never_apply is False and pol.never_reason is None


async def test_never_apply_blocks_tailoring_the_gate_and_the_decision_record(session) -> None:
    job = await make_job(session, "Analyst", "Acme Ltd")
    app = await make_app(session, job, Stage.shortlisted)
    await employers.update_policy(session, "acme ltd", {"never_apply": True, "never_reason": "bad fit"}, actor="owner")

    with pytest.raises(tailoring_service.TailoringError, match="never apply to Acme Ltd: bad fit"):
        await tailoring_service.request(session, app, actor="owner")
    gate = await conflicts.check_conflict_at_submit(session, app, now=NOW, claim=False)
    assert gate.outcome == "fail" and "never apply" in gate.reason
    assert app.stage == Stage.shortlisted  # the claim never happened

    [(_, record)] = await filters.load_records(session, now=NOW, job_ids=[job.id])
    assert record["never_apply"] == "bad fit"
    decision = decide(data(job_rec=matching_job(never_apply=record["never_apply"]), score=100))
    gate_row = next(g for g in decision.gates if g.gate == "employer_never_apply")
    assert gate_row.layer == "exclusion" and gate_row.outcome == "fail"
    assert decision.verdict == "excluded"  # a 100 score cannot rescue it
    assert decide(data(job_rec=matching_job(), score=100)).verdict != "excluded"

    await employers.update_policy(session, "acme ltd", {"never_apply": False}, actor="owner")
    [(_, record)] = await filters.load_records(session, now=NOW, job_ids=[job.id])
    assert record["never_apply"] is None
    await stages.transition(session, app, Stage.tailoring, actor="owner", why="x")  # and it works again


async def test_never_apply_follows_the_employer_alias(session) -> None:
    job = await make_job(session, "Analyst", "Acme Holdings")
    session.add(EmployerAlias(alias="Acme Holdings", canonical="Acme Ltd"))
    await session.flush()
    await employers.update_policy(session, "acme ltd", {"never_apply": True, "never_reason": "brand"}, actor="owner")
    assert "never apply" in (await employers.never_apply_reason(session, job))


# ----- HTTP --------------------------------------------------------------------------------------------


async def test_http_list_detail_policy_and_end_cooldown(owner_client, session) -> None:
    now = datetime.now(UTC)
    a = await make_job(session, "Analyst", "Acme Ltd")
    await make_app(session, a, Stage.rejected, applied_at=now - timedelta(days=12), ended_at=now - timedelta(days=10))
    await make_job(session, "Manager", "Acme Ltd")
    await session.commit()

    rows = (await owner_client.get("/api/employers")).json()
    assert [r["state"] for r in rows] == ["cooling_down"] and rows[0]["roles_seen"] == 2
    assert rows[0]["held_roles"] == 0 and rows[0]["applications"] == 1
    assert (await owner_client.get("/api/employers", params={"state": "free"})).json() == []

    d = (await owner_client.get("/api/employers/detail", params={"key": "Acme Ltd"})).json()
    assert d["cooldown"]["kind"] == "end_state" and d["cooldown"]["running"] is True and d["cooldown"]["days"] == 30
    assert d["cooldown_days_source"] == "the default setting"
    assert {r["title"] for r in d["roles"]} == {"Analyst", "Manager"} and len(d["history"]) == 1
    assert (await owner_client.get("/api/employers/detail", params={"key": "nobody"})).status_code == 404

    r = await owner_client.patch("/api/employers/policy", params={"key": "acme ltd"}, json={"never_apply": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    r = await owner_client.patch("/api/employers/policy", params={"key": "acme ltd"},
                                 json={"cooldown_days": 7, "priority": 5, "always_ask_first": True,
                                       "notes": "Met their HR at a fair"})
    assert r.status_code == 200 and r.json()["priority"] == 5 and r.json()["cooldown_days"] == 7
    assert r.json()["state"] == "always_ask_first"  # 7 days since the end have gone by: no longer cooling
    d = (await owner_client.get("/api/employers/detail", params={"key": "acme ltd"})).json()
    assert d["notes"] == "Met their HR at a fair" and d["cooldown_days_source"] == "this employer's override"
    assert (await owner_client.post("/api/employers/end-cooldown", params={"key": "acme ltd"},
                                    json={"reason": "x"})).status_code == 409  # nothing running now

    await owner_client.patch("/api/employers/policy", params={"key": "acme ltd"}, json={"cooldown_days": None})
    r = await owner_client.post("/api/employers/end-cooldown", params={"key": "acme ltd"}, json={"reason": "asked"})
    assert r.status_code == 200 and r.json()["state"] == "always_ask_first"
    actions = {x.action for x in (await session.scalars(select(AuditEvent))).all()}
    assert {"employer.policy_updated", "employer.cooldown_ended"} <= actions


async def test_http_conflict_groups_show_winner_and_held(owner_client, session) -> None:
    from tests.apply.helpers import setup_app, setup_campaign

    campaign = await setup_campaign(session)
    await setup_app(session, campaign, title="Senior Analyst", score=90, now=NOW, stage=Stage.shortlisted)
    await setup_app(session, campaign, title="Analyst", score=70, now=NOW, stage=Stage.shortlisted)
    await session.commit()
    d = (await owner_client.get("/api/employers/detail", params={"key": "acme example"})).json()
    [group] = d["conflict_groups"]
    assert {r["conflict_state"] for r in group} == {"winner", "held"}
    held = next(r for r in group if r["conflict_state"] == "held")
    assert "outranked" in held["conflict_note"] and d["employer"]["held_roles"] == 1


async def test_http_states_for_chips(owner_client, session) -> None:
    job = await make_job(session, "Analyst", "Acme Ltd")
    other = await make_job(session, "Analyst", "Never Co")
    await employers.update_policy(session, "never co", {"never_apply": True, "never_reason": "r"}, actor="owner")
    await session.commit()
    r = await owner_client.post("/api/employers/states", json={"job_ids": [str(job.id), str(other.id)]})
    assert r.status_code == 200
    assert r.json()["states"][str(job.id)]["state"] == "free"
    assert r.json()["states"][str(other.id)] == {"state": "blocked", "text": "never apply: r"}


async def test_http_merge_and_split_reuse_the_corrections_code(owner_client, session) -> None:
    await make_job(session, "Analyst", "Acme Holdings")
    keep = await make_job(session, "Manager", "Acme Ltd")
    await session.commit()
    r = await owner_client.post("/api/employers/merge", params={"key": "acme holdings"}, json={"into": "Acme Ltd"})
    assert r.status_code == 200 and r.json()["jobs"] == 1
    rows = (await owner_client.get("/api/employers")).json()
    assert [(x["name"], x["roles_seen"]) for x in rows] == [("Acme Ltd", 2)]
    d = (await owner_client.get("/api/employers/detail", params={"key": "acme ltd"})).json()
    assert d["aliases"] == ["Acme Holdings"]
    assert (await owner_client.post("/api/employers/merge", params={"key": "acme ltd"},
                                    json={"into": "ACME LTD"})).status_code == 409

    r = await owner_client.post("/api/employers/split", json={"alias": "Acme Holdings"})
    assert r.status_code == 200 and r.json()["jobs"] == 1
    assert sorted(x["name"] for x in (await owner_client.get("/api/employers")).json()) == ["Acme Holdings", "Acme Ltd"]
    assert (await owner_client.post("/api/employers/split", json={"alias": "Acme Holdings"})).status_code == 404
    async with __import__("app.core.db", fromlist=["x"]).get_sessionmaker()() as s:
        assert (await s.get(Job, keep.id)).canonical_employer == "Acme Ltd"
        assert await s.scalar(select(Application.id)) is None
