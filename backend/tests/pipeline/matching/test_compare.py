"""Compare roles side by side (DESIGN.md 18.4): three-state facets, pay normalised only where sound, score
breakdown, gates, employer group, no model call. Invented data only."""

from __future__ import annotations

import uuid

import pytest

from app.models.search import Assessment, AssessmentState, ConflictState
from app.pipeline import compare
from app.schemas.json_types import CriterionRating, FilterResult
from tests.pipeline.matching.fakes import add_campaign, add_job, add_rubric

ZERO = "00000000-0000-0000-0000-000000000000"


def row(out, key):
    return next(r for r in out.rows if r.key == key)


async def scored(session, job, campaign, rubric, score, ratings, filters=(), gaps=()):
    a = Assessment(job_id=job.id, campaign_id=campaign.id, rubric_id=rubric.id, rubric_version=rubric.version,
                   state=AssessmentState.scored, score=score, base_score=score, gaps=list(gaps),
                   ratings=[CriterionRating(criterion=k, rating=v) for k, v in ratings.items()],
                   filter_results=[FilterResult(name=n, result=r, reason=why) for n, r, why in filters])
    session.add(a)
    await session.flush()
    return a


async def trio(session, **pay):
    """Three roles under one rubric: stated yearly pay, monthly pay, and none."""
    rubric = await add_rubric(session)
    campaign = await add_campaign(session, rubric)
    a = await add_job(session, "Data Analyst", "Acme Example", pay_state="stated", pay_min_minor=50_000_00,
                      pay_max_minor=60_000_00, pay_currency="USD", pay_period="year",
                      facets={"work_model": {"value": "remote"}, "visa_sponsorship": {"value": "yes"}})
    b = await add_job(session, "BI Developer", "Beta Example", pay_state="stated", pay_min_minor=5_000_00,
                      pay_max_minor=5_000_00, pay_currency="USD", pay_period="month",
                      facets={"work_model": {"value": "hybrid"}, "visa_sponsorship": {"value": "no"}})
    c = await add_job(session, "Analyst", "Gamma Example", facets={"work_model": {"value": "on_site"}}, **pay)
    await scored(session, a, campaign, rubric, 80, {"skills": 4, "domain": 3},
                 [("pay_floor", "pass", "50k clears the floor")], ["no SQL Server"])
    await scored(session, b, campaign, rubric, 70, {"skills": 3, "domain": 4}, [("pay_floor", "pass", "ok")])
    await scored(session, c, campaign, rubric, 60, {"skills": 2}, [("pay_floor", "unknown", "pay not stated")])
    return [a, b, c]


async def test_three_roles_side_by_side_with_unknown_pay(session):
    jobs = await trio(session)
    out = await compare.build(session, [j.id for j in jobs])
    assert [j.title for j in out.jobs] == ["Data Analyst", "BI Developer", "Analyst"]
    # Facets are three-state: a stated no, a stated yes, and a fact the posting does not state.
    visa = row(out, "facet:visa_sponsorship")
    assert [c.state for c in visa.cells] == ["yes", "no", "not_stated"]
    assert [c.value for c in row(out, "facet:work_model").cells] == ["remote", "hybrid", "on site"]
    # Pay: yearly and monthly are normalised; the role with no stated pay is shown as such and the row
    # refuses to rank (no best role is named).
    pay = row(out, "pay")
    assert pay.cells[0].amount_minor == 55_000_00 and pay.cells[1].amount_minor == 60_000_00
    assert pay.cells[2].state == "not_stated" and pay.cells[2].value is None and pay.cells[2].amount_minor is None
    assert not pay.comparable and pay.best_index is None and "Analyst" in pay.note
    # Scores: one rubric, so comparable; per criterion; a missing rating is not stated, not zero.
    assert [c.value for c in row(out, "score").cells] == [80, 70, 60]
    assert row(out, "score").comparable and row(out, "score").best_index == 0
    skills, domain = row(out, "criterion:skills"), row(out, "criterion:domain")
    assert [c.value for c in skills.cells] == [4, 3, 2] and skills.best_index == 0 and skills.comparable
    assert [c.state for c in domain.cells] == ["stated", "stated", "not_stated"]
    assert not domain.comparable and domain.best_index is None and "not rated" in domain.note
    # Eligibility gates keep their three states.
    assert [c.state for c in row(out, "gate:pay_floor").cells] == ["pass", "pass", "unknown"]
    assert row(out, "gaps").cells[0].value == "no SQL Server" and row(out, "gaps").cells[1].state == "not_stated"
    # Employer group, deadline, how to apply.
    assert [c.value for c in row(out, "employer_group").cells] == ["Acme Example", "Beta Example", "Gamma Example"]
    assert [c.state for c in row(out, "deadline").cells] == ["not_stated"] * 3
    assert out.winner_id is None


async def test_pay_ranks_when_every_role_states_comparable_pay(session):
    a = await add_job(session, "Data Analyst", "Acme Example", pay_state="stated", pay_min_minor=50_000_00,
                      pay_max_minor=60_000_00, pay_currency="USD", pay_period="year")
    b = await add_job(session, "BI Developer", "Beta Example", pay_state="stated", pay_min_minor=6_000_00,
                      pay_max_minor=6_000_00, pay_currency="USD", pay_period="month")
    pay = row(await compare.build(session, [a.id, b.id]), "pay")
    assert pay.comparable and pay.best_index == 1 and pay.cells[1].amount_minor == 72_000_00
    assert "per year" in pay.cells[1].note
    # An estimate is flagged as one, and still ranks.
    b.pay_state = "estimated"
    est = row(await compare.build(session, [a.id, b.id]), "pay")
    assert est.cells[1].state == "estimated" and "estimate" in est.cells[1].note


async def test_pay_in_different_currencies_or_per_hour_is_not_comparable(session):
    usd = await add_job(session, "Data Analyst", "Acme Example", pay_state="stated", pay_min_minor=50_000_00,
                        pay_max_minor=50_000_00, pay_currency="USD", pay_period="year")
    zmw = await add_job(session, "BI Developer", "Beta Example", pay_state="stated", pay_min_minor=400_000_00,
                        pay_max_minor=400_000_00, pay_currency="ZMW", pay_period="year")
    hourly = await add_job(session, "Contractor", "Gamma Example", pay_state="stated", pay_min_minor=40_00,
                           pay_max_minor=40_00, pay_currency="USD", pay_period="hour")
    mixed = row(await compare.build(session, [usd.id, zmw.id]), "pay")
    assert not mixed.comparable and mixed.best_index is None and "different currencies" in mixed.note
    assert "no exchange rate" in mixed.note
    per_hour = row(await compare.build(session, [usd.id, hourly.id]), "pay")
    assert not per_hour.comparable and per_hour.cells[1].amount_minor is None
    assert per_hour.cells[1].value == "40 USD per hour" and "not normalised" in per_hour.cells[1].note


async def test_scores_under_different_rubric_versions_are_not_compared(session):
    one = await add_rubric(session)
    two = await add_rubric(session, version=2)
    campaign = await add_campaign(session, one)
    a = await add_job(session, "Data Analyst", "Acme Example")
    b = await add_job(session, "BI Developer", "Beta Example")
    await scored(session, a, campaign, one, 80, {"skills": 4})
    other = await add_campaign(session, two, name="Other")
    await scored(session, b, other, two, 90, {"skills": 5})
    out = await compare.build(session, [a.id, b.id])
    score = row(out, "score")
    assert not score.comparable and score.best_index is None and "different rubric" in score.note
    assert [c.value for c in row(out, "criterion:skills").cells] == [4, 5]  # still shown
    assert row(out, "criterion:skills").best_index is None


async def test_a_role_nobody_assessed_is_unknown_not_zero(session):
    rubric = await add_rubric(session)
    campaign = await add_campaign(session, rubric)
    a = await add_job(session, "Data Analyst", "Acme Example")
    b = await add_job(session, "BI Developer", "Beta Example")
    await scored(session, a, campaign, rubric, 80, {"skills": 4})
    score = row(await compare.build(session, [a.id, b.id]), "score")
    assert score.cells[1].state == "unknown" and score.cells[1].value is None and not score.comparable


async def test_the_conflict_groups_winner_and_reason_are_reported(session):
    win = await add_job(session, "Data Analyst", "Acme Example", conflict_state=ConflictState.winner,
                        conflict_note="higher score and earlier deadline")
    held = await add_job(session, "Data Scientist", "Acme Example", conflict_state=ConflictState.held,
                         conflict_note="held behind Data Analyst")
    out = await compare.build(session, [held.id, win.id])
    assert out.winner_id == win.id and out.winner_reason == "higher score and earlier deadline"
    assert row(out, "employer_group").cells[0].note == "held: held behind Data Analyst"
    other = await add_job(session, "Analyst", "Beta Example")
    assert (await compare.build(session, [win.id, other.id])).winner_id is None  # different employers


def test_ids_are_validated():
    one, two, three, four, five = (uuid.uuid4() for _ in range(5))
    assert compare.parse_ids(f"{one},{two}") == [one, two]
    for bad in (str(one), f"{one},{one}", f"{one},nope", ",".join(str(i) for i in (one, two, three, four, five))):
        with pytest.raises(compare.CompareError):
            compare.parse_ids(bad)


async def test_compare_endpoint(owner_client, session):
    jobs = await trio(session)
    await session.commit()
    ids = ",".join(str(j.id) for j in jobs)
    r = await owner_client.get(f"/api/jobs/compare/{ids}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_ids"] == [str(j.id) for j in jobs] and body["winner_id"] is None
    pay = next(x for x in body["rows"] if x["key"] == "pay")
    assert pay["comparable"] is False and pay["cells"][2]["state"] == "not_stated"
    assert (await owner_client.get(f"/api/jobs/compare/{jobs[0].id}")).status_code == 422
    assert (await owner_client.get(f"/api/jobs/compare/{jobs[0].id},{ZERO}")).status_code == 404
    assert (await owner_client.get("/api/jobs/compare/a,b")).status_code == 422
