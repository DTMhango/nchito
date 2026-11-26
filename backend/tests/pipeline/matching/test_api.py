"""Campaigns, rubrics, assessments and jobs endpoints; the Matches filter grammar; views."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import func, select

from app.api.routers import assessments as assessments_router
from app.core.conditions import ConditionSet
from app.core.db import get_sessionmaker
from app.models.applications import Application
from app.models.search import Assessment, AssessmentState, Job, PayEstimate
from app.pipeline import scoring
from app.pipeline.decisions import decide
from app.pipeline.filters import campaign_record, load_records
from app.schemas.json_types import CampaignCriteria
from tests.pipeline.matching.fakes import (
    RUBRIC,
    FakeLLMClient,
    add_campaign,
    add_facts,
    add_job,
    add_rubric,
    ratings,
)
from tests.pipeline.matching.helpers import NOW, default_settings

YES = {"value": "yes", "evidence": "Relocation required."}
NO = {"value": "no", "evidence": "No relocation."}


async def seed_jobs() -> dict[str, uuid.UUID]:
    """Five invented jobs covering each facet type, including not-stated values."""
    async with get_sessionmaker()() as s:
        jobs = {
            "reloc_sponsor": await add_job(s, "Data Engineer", "North Example", facets={
                "relocation_required": YES, "visa_sponsorship": YES, "required_skills": ["Python", "Spark"],
                "years_experience": {"value": 5}, "work_model": {"value": "on_site"},
                "min_education": {"value": {"level": "masters", "required": True}}}),
            "reloc_nosponsor": await add_job(s, "Data Analyst", "South Example", facets={
                "relocation_required": YES, "visa_sponsorship": NO, "required_skills": ["SQL"],
                "years_experience": {"value": 2}, "work_model": {"value": "hybrid"}}),
            "remote": await add_job(s, "Analytics Engineer", "East Example", facets={
                "relocation_required": NO, "required_skills": ["Python", "SQL"],
                "work_model": {"value": "remote"}, "remote_scope": {"value": "worldwide"},
                "min_education": {"value": {"level": "bachelors", "required": False}}}),
            "unstated": await add_job(s, "Reporting Lead", "West Example"),
            "powerbi": await add_job(s, "BI Developer", "West Example", function="bi",
                                     facets={"required_skills": ["PowerBI"]}),
        }
        s.add(PayEstimate(job_id=jobs["unstated"].id, min_minor=1, max_minor=2, currency="USD", source="survey",
                          estimated_on=NOW.date()))
        jobs["unstated"].pay_state = "estimated"
        jobs["remote"].pay_state = "stated"
        jobs["remote"].pay_max_minor, jobs["remote"].pay_currency, jobs["remote"].pay_period = 9_000_000, "USD", "year"
        await s.commit()
        return {k: v.id for k, v in jobs.items()}


def cs(*conditions: dict) -> str:
    return json.dumps({"version": 1, "root": {"type": "group", "op": "and", "conditions": list(conditions)}})


def vf(facet: str, include=(), exclude=(), match="any") -> dict:
    return {"type": "values", "facet": facet, "include": list(include), "exclude": list(exclude), "match": match}


async def ids(client, **params) -> set[uuid.UUID]:
    r = await client.get("/api/jobs", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return {uuid.UUID(i["id"]) for i in r.json()["items"]}


FACET_CASES = [
    # yes/no facet: include, exclude and not-stated are distinct
    ("facets.relocation_required", ["yes"], [], {"reloc_sponsor", "reloc_nosponsor"}),
    ("facets.relocation_required", [], ["yes"], {"remote", "unstated", "powerbi"}),
    ("facets.relocation_required", ["not_stated"], [], {"unstated", "powerbi"}),
    ("facets.relocation_required", [], ["not_stated"], {"reloc_sponsor", "reloc_nosponsor", "remote"}),
    # enum facet
    ("facets.work_model", ["remote", "hybrid"], [], {"remote", "reloc_nosponsor"}),
    ("facets.work_model", [], ["on_site"], {"reloc_nosponsor", "remote", "unstated", "powerbi"}),
    ("facets.work_model", ["not_stated"], [], {"unstated", "powerbi"}),
    # list facet (skills, aliases applied below)
    ("facets.required_skills", ["python"], [], {"reloc_sponsor", "remote"}),
    ("facets.required_skills", [], ["sql"], {"reloc_sponsor", "unstated", "powerbi"}),
    ("facets.required_skills", ["not_stated"], [], {"unstated"}),
    # nested facet
    ("facets.min_education.level", ["masters"], [], {"reloc_sponsor"}),
    ("facets.min_education.level", [], ["masters"], {"reloc_nosponsor", "remote", "unstated", "powerbi"}),
    ("facets.min_education.level", ["not_stated"], [], {"reloc_nosponsor", "unstated", "powerbi"}),
    # pay states never merge
    ("pay_state", ["estimated"], [], {"unstated"}),
    ("pay_state", ["not_stated"], [], {"reloc_sponsor", "reloc_nosponsor", "powerbi"}),
]


@pytest.mark.parametrize("facet,include,exclude,expected", FACET_CASES)
async def test_include_exclude_and_not_stated_per_facet_type(owner_client, facet, include, exclude, expected):
    jobs = await seed_jobs()
    got = await ids(owner_client, conditions=cs(vf(facet, include, exclude)))
    assert got == {jobs[k] for k in expected}


async def test_range_any_all_text_group_sort_and_pages(owner_client):
    jobs = await seed_jobs()
    rng = {"type": "range", "facet": "facets.years_experience", "min": 3}
    assert await ids(owner_client, conditions=cs(rng)) == {jobs["reloc_sponsor"]}
    rng["not_stated"] = "include"
    assert await ids(owner_client, conditions=cs(rng)) == {jobs[k] for k in ("reloc_sponsor", "unstated", "remote",
                                                                                "powerbi")}
    both = vf("facets.required_skills", ["python", "sql"], match="all")
    assert await ids(owner_client, conditions=cs(both)) == {jobs["remote"]}
    assert await ids(owner_client, q="engineer") == {jobs["reloc_sponsor"], jobs["remote"]}
    r = await owner_client.get("/api/jobs", params={"conditions": cs(vf("facets.relocation_required", ["yes"])),
                                                    "group_by": "facets.visa_sponsorship"})
    assert {(g["value"], g["count"]) for g in r.json()["groups"]} == {("yes", 1), ("no", 1)}
    r = await owner_client.get("/api/jobs", params={"sort": "title", "limit": 2})
    body = r.json()
    assert [i["title"] for i in body["items"]] == ["Analytics Engineer", "BI Developer"] and body["total"] == 5
    r2 = await owner_client.get("/api/jobs", params={"sort": "title", "limit": 2, "cursor": body["next_cursor"]})
    assert [i["title"] for i in r2.json()["items"]] == ["Data Analyst", "Data Engineer"]
    assert (await owner_client.get("/api/jobs", params={"sort": "nonsense"})).status_code == 422
    assert (await owner_client.get("/api/jobs", params={"conditions": "{bad"})).status_code == 422


async def test_skill_alias_reevaluates_without_refetch(owner_client):
    jobs = await seed_jobs()
    query = cs(vf("facets.required_skills", ["Power BI"]))
    assert await ids(owner_client, conditions=query) == set()
    r = await owner_client.post("/api/skill-aliases", json={"alias": "PowerBI", "canonical": "Power BI"})
    assert r.status_code == 201, r.text
    assert await ids(owner_client, conditions=query) == {jobs["powerbi"]}


async def _snapshot() -> list:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(Job.id, Job.triage, Job.tags, Job.conflict_state, Job.updated_at))).all()
        n = await s.scalar(select(func.count()).select_from(Assessment))
        return [*sorted(map(tuple, rows), key=str), n]


async def test_saved_view_never_alters_pipeline_state(owner_client):
    await seed_jobs()
    before = await _snapshot()
    body = {"conditions": json.loads(cs(vf("facets.relocation_required", ["yes"]))),
            "group_by": "facets.visa_sponsorship", "sort": [{"field": "title", "direction": "asc"}]}
    r = await owner_client.post("/api/views", json={"name": "Relocation", "body": body, "pinned": True})
    assert r.status_code == 201 and r.json()["count"] == 2
    view_id = r.json()["id"]
    listed = await owner_client.get("/api/jobs", params={"view_id": view_id})
    assert listed.json()["total"] == 2 and listed.json()["groups"]
    assert [v["count"] for v in (await owner_client.get("/api/views")).json()["items"]] == [2]
    await owner_client.get("/api/jobs/facets")
    assert await _snapshot() == before


@pytest.mark.parametrize("effect", ["include", "exclude"])
async def test_view_copied_to_campaign_rule_matches_exactly_the_same_jobs(owner_client, effect):
    await seed_jobs()
    conditions = cs(vf("facets.relocation_required", ["yes"]), vf("facets.visa_sponsorship", [], ["no"]))
    view = (await owner_client.post("/api/views", json={"name": "Reloc, sponsored", "body": {
        "conditions": json.loads(conditions)}})).json()
    camp = (await owner_client.post("/api/campaigns", json={"name": "Rules"})).json()
    r = await owner_client.post(f"/api/campaigns/{camp['id']}/rules/from-view",
                                json={"view_id": view["id"], "effect": effect})
    assert r.status_code == 200, r.text
    assert "rules" in r.json()["unconfirmed"]
    shown = await ids(owner_client, view_id=view["id"])
    preview = (await owner_client.post(f"/api/campaigns/{camp['id']}/preview",
                                       json={"conditions": json.loads(conditions), "limit": 500})).json()
    assert {uuid.UUID(i) for i in preview["sample_job_ids"]} == shown
    async with get_sessionmaker()() as s:
        from app.models.search import Campaign
        campaign = await s.get(Campaign, uuid.UUID(camp["id"]))
        settings = default_settings()
        matched = set()
        for job, record in await load_records(s, now=NOW):
            d = decide(scoring.decision_input(now=NOW, record=record, crecord=campaign_record(campaign),
                                              settings=settings, versions={}, rubric=None, base_score=90, job=job))
            gate = next(g for g in d.gates if g.gate == "rule:0")
            if (gate.outcome == "pass") == (effect == "include"):
                matched.add(job.id)
    assert matched == shown and shown


async def test_campaign_crud_per_item_confirmation_and_mode_cap(owner_client):
    body = {"name": "Analytics", "automation": {"mode": "auto_apply"}, "schedule_cron": "0 7 * * *",
            "criteria": {"seniority": ["senior"], "pay_floors": [{"employment_type": "permanent",
                                                                  "amount_minor": 100, "currency": "ZMW"}],
                         "locations": [{"place": "Zambia", "kind": "allow"}]}}
    r = await owner_client.post("/api/campaigns", json=body)
    assert r.status_code == 201, r.text
    camp = r.json()
    assert camp["automation"]["mode"] == "auto_apply" and camp["mode_ceiling"] == "prepare"
    assert sorted(camp["unconfirmed"]) == ["locations", "pay_floors", "seniority"]
    assert camp["schedule_cron"] == "0 7 * * *" and camp["match_counts"] == {"new": 0, "shortlisted": 0, "held": 0}
    cid = camp["id"]
    assert (await owner_client.post(f"/api/campaigns/{cid}/confirm/keywords")).status_code == 409
    for item in ("pay_floors", "locations"):
        r = await owner_client.post(f"/api/campaigns/{cid}/confirm/{item}")
        assert r.json()["mode_ceiling"] == "prepare" and r.json()["review_state"] == "needs_review"
    r = await owner_client.post(f"/api/campaigns/{cid}/confirm/seniority")
    assert r.json()["unconfirmed"] == [] and r.json()["review_state"] == "confirmed"
    assert r.json()["mode_ceiling"] == "auto_apply"
    # Changing a criteria item puts it back on the list and the lock returns.
    body["criteria"]["seniority"] = ["lead"]
    r = await owner_client.put(f"/api/campaigns/{cid}", json=body)
    assert r.json()["unconfirmed"] == ["seniority"] and r.json()["mode_ceiling"] == "prepare"
    clone = (await owner_client.post(f"/api/campaigns/{cid}/clone")).json()
    assert clone["name"] == "Analytics (copy)" and clone["status"] == "draft" and clone["mode_ceiling"] == "prepare"
    r = await owner_client.post(f"/api/campaigns/{cid}/status", json={"status": "active"})
    assert r.json()["status"] == "active"
    listed = (await owner_client.get("/api/campaigns")).json()
    assert listed["total"] == 2
    assert (await owner_client.post("/api/campaigns", json={**body, "schedule_cron": "bad"})).status_code == 422
    assert (await owner_client.delete(f"/api/campaigns/{clone['id']}")).status_code == 204
    dry = await owner_client.post(f"/api/campaigns/{cid}/dry-run")
    assert dry.status_code == 202


async def _scored_setup(score: int, *, exclude: bool = False):
    async with get_sessionmaker()() as s:
        rubric = await add_rubric(s)
        criteria = CampaignCriteria()
        if exclude:
            criteria = CampaignCriteria.model_validate({"rules": [{"effect": "exclude", "reason": "no relocation",
                                                                    "conditions": json.loads(cs(vf(
                                                                        "facets.relocation_required", ["yes"])))}]})
        campaign = await add_campaign(s, rubric, criteria=criteria)
        job = await add_job(s, facets={"relocation_required": YES})
        a = Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored, score=score,
                       base_score=score, rubric_id=rubric.id, rubric_version=1)
        s.add(a)
        await s.commit()
        return job.id, campaign.id, a.id


async def test_override_records_who_and_why_and_never_bypasses_filters(owner_client):
    job_id, _, aid = await _scored_setup(40, exclude=True)
    r = await owner_client.post(f"/api/assessments/{aid}/override", json={"score": 100, "reason": "great team"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["override"]["by"] == "owner" and body["override"]["reason"] == "great team"
    assert body["score"] is None  # excluded: the override cannot rescue it
    why = (await owner_client.get(f"/api/jobs/{job_id}/why")).json()
    assert why["decision"] == "excluded"
    rule = next(r for r in why["rules"] if r["rule"] == "exclusion.rule:0")
    assert rule["outcome"] == "fail" and rule["source"] == "campaign" and rule["version"]
    assert why["conditions"][0]["matched"] is True


async def test_override_changes_score_when_filters_pass(owner_client):
    job_id, _, aid = await _scored_setup(40)
    r = await owner_client.post(f"/api/assessments/{aid}/override", json={"score": 80, "reason": "known team"})
    assert r.json()["score"] == 80 and r.json()["base_score"] == 40
    got = (await owner_client.get("/api/assessments", params={"job_id": str(job_id)})).json()
    assert got["total"] == 1 and got["items"][0]["override"]["score"] == 80
    why = (await owner_client.get(f"/api/jobs/{job_id}/why")).json()
    score_rule = next(r for r in why["rules"] if r["rule"] == "score.score")
    assert "assessment.override=80" in score_rule["effective_value"]
    assert any(r["source"] == "setting" and r["version"] for r in why["rules"])


async def test_rescore_queues_a_run(owner_client, monkeypatch):
    job_id, campaign_id, _ = await _scored_setup(40)
    queued = []

    async def fake_enqueue(run):
        queued.append(run.id)

    monkeypatch.setattr(assessments_router, "enqueue", fake_enqueue)
    r = await owner_client.post("/api/assessments/rescore", json={"job_ids": [str(job_id)],
                                                                  "campaign_id": str(campaign_id)})
    assert r.status_code == 202 and queued == [uuid.UUID(r.json()["run_id"])]


async def test_rubric_versions_activate_and_backtest_via_api(owner_client):
    rubric_body = RUBRIC.model_dump()
    assert (await owner_client.post("/api/rubrics", json={"name": "Bad", "body": {
        "criteria": [{"name": "a", "weight": 50}]}})).status_code == 422
    draft = (await owner_client.post("/api/rubrics", json={"name": "Default", "body": rubric_body})).json()
    assert draft["status"] == "draft" and draft["version"] == 1
    active = (await owner_client.post(f"/api/rubrics/{draft['id']}/activate")).json()
    assert active["status"] == "active" and active["version"] == 2
    edited = (await owner_client.put(f"/api/rubrics/{active['id']}", json={"name": "Default", "body": rubric_body}))
    assert edited.json()["status"] == "draft" and edited.json()["version"] == 3
    camp = (await owner_client.post("/api/campaigns", json={"name": "C", "rubric_id": active["id"]})).json()
    async with get_sessionmaker()() as s:
        await add_facts(s, "F-1")
        job = await add_job(s)
        await s.commit()
    payload = {"rubric_id": edited.json()["id"], "campaign_id": camp["id"], "job_ids": [str(job.id)]}
    assert (await owner_client.post("/api/rubrics/backtest/estimate", json=payload)).status_code == 503
    client = FakeLLMClient(ratings({"skills": 5, "domain": 5}))

    async def factory(session):
        return client

    scoring.set_client_factory(factory)
    try:
        est = (await owner_client.post("/api/rubrics/backtest/estimate", json=payload)).json()
        assert est["estimated_cost_minor"] == 0 and est["estimated_cost_micros"] > 0 and est["to_score"] == 1
        assert client.calls == []
        result = (await owner_client.post("/api/rubrics/backtest", json=payload)).json()
        assert result["rows"][0]["new_score"] == 100 and len(client.calls) == 1
    finally:
        scoring.set_client_factory(None)


async def test_tag_rules_tag_saved_jobs_and_catalogue_lists_facets(owner_client):
    jobs = await seed_jobs()
    rule = {"tag": "relocation", "conditions": json.loads(cs(vf("facets.relocation_required", ["yes"])))}
    assert (await owner_client.post("/api/tag-rules", json=rule)).status_code == 201
    tagged = await ids(owner_client, conditions=cs(vf("tags", ["relocation"])))
    assert tagged == {jobs["reloc_sponsor"], jobs["reloc_nosponsor"]}
    await owner_client.post("/api/custom-facets", json={"key": "rms", "question": "Requires RMS experience?"})
    catalogue = {e["facet"]: e for e in (await owner_client.get("/api/jobs/facets")).json()}
    reloc = {v["value"]: v["count"] for v in catalogue["facets.relocation_required"]["values"]}
    assert reloc == {"yes": 2, "no": 1, "not_stated": 2}
    assert catalogue["custom.rms"]["kind"] == "values"
    assert catalogue["facets.years_experience"]["kind"] == "range"


async def test_job_detail_patch_and_release(owner_client):
    async with get_sessionmaker()() as s:
        campaign = await add_campaign(s, await add_rubric(s))
        one, two = await add_job(s, "One"), await add_job(s, "Two")
        for job, score in ((one, 90), (two, 80)):
            s.add(Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored, score=score,
                             base_score=score))
        await s.commit()
    from app.pipeline import conflicts
    async with get_sessionmaker()() as s:
        await conflicts.resolve_employers(s, ["Acme Example"], now=NOW)
        await s.commit()
    detail = (await owner_client.get(f"/api/jobs/{two.id}")).json()
    assert detail["conflict_state"] == "held" and detail["best_score"] == 80
    row = next(i for i in (await owner_client.get("/api/jobs")).json()["items"] if i["id"] == str(two.id))
    assert row["conflict"] == {"state": "held", "note": row["conflict_note"], "outranked_by_job_id": str(one.id),
                               "outranked_by_title": "One", "score": 80, "outranked_by_score": 90,
                               "reason": "outranked"}
    assert row["work_model"] == "not_stated" and row["pay_state"] == "not_stated" and row["source"] is None
    r = await owner_client.post(f"/api/jobs/{two.id}/release", json={"reason": "want both"})
    assert r.json()["conflict_state"] == "released"
    assert (await owner_client.post(f"/api/jobs/{one.id}/release", json={"reason": "nope"})).status_code == 409
    r = await owner_client.patch(f"/api/jobs/{one.id}", json={"triage": "skipped", "tags": ["mine"]})
    assert r.json()["triage"] == "skipped" and r.json()["tags"] == ["mine"]
    assert r.json()["conflict_state"] == "none"
    assert (await owner_client.get(f"/api/jobs/{uuid.uuid4()}")).status_code == 404
    async with get_sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Application)) == 0


def test_condition_set_round_trip():
    assert ConditionSet.model_validate_json(cs(vf("tags", ["a"]))).root.conditions[0].facet == "tags"
