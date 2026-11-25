"""Round trips for JSONB columns validated by Pydantic shapes, and shape rejection on write."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import StatementError

from app.core.conditions import CampaignRule, ConditionSet, Group, ValueFilter
from app.models import (
    Answer,
    Application,
    ApplicationPacket,
    Campaign,
    Fact,
    Guardrail,
    Job,
    PayEstimate,
    Rubric,
)
from app.models.kit import AnswerClass, FactKind, GuardrailType, Strictness
from app.models.search import DeadlineState, PayState
from app.schemas.json_types import (
    AutomationPolicy,
    CampaignCriteria,
    JobFacets,
    NeverTogether,
    PacketContents,
    PacketDestination,
    PacketFile,
    PayFloor,
    RubricBody,
    RubricCriterion,
    WhereMustLive,
)


async def _reload(session, obj):
    await session.commit()
    session.expunge_all()
    return await session.get(type(obj), obj.id)


async def _job(session, **kw) -> Job:
    job = Job(title="Data Analyst", employer="Acme Ltd", canonical_employer="Acme", content_hash="0" * 64, **kw)
    session.add(job)
    await session.flush()
    return job


async def test_job_facets_round_trip(session):
    facets = JobFacets.model_validate({
        "visa_sponsorship": {"value": "yes", "evidence": "We sponsor work permits."},
        "where_must_live": {"value": WhereMustLive(kind="places", places=["ZM", "ZA"]).model_dump(),
                            "evidence": "Must live in Zambia or South Africa."},
        "required_skills": ["python", "sql"],
    })
    job = await _job(session, facets=facets, pay_state=PayState.stated, pay_min_minor=4_000_000,
                     pay_max_minor=5_500_000, pay_currency="USD", pay_period="year",
                     deadline_state=DeadlineState.dated, deadline=date(2026, 12, 31))
    loaded = await _reload(session, job)
    assert isinstance(loaded.facets, JobFacets)
    assert loaded.facets.visa_sponsorship.value == "yes"
    assert loaded.facets.visa_sponsorship.evidence == "We sponsor work permits."
    assert loaded.facets.where_must_live.value.places == ["ZM", "ZA"]
    assert loaded.facets.relocation_required.value == "not_stated"
    assert loaded.pay_state == PayState.stated and loaded.pay_min_minor == 4_000_000
    assert loaded.deadline_state == DeadlineState.dated


async def test_pay_estimate_kept_apart(session):
    job = await _job(session, pay_state=PayState.estimated)
    session.add(PayEstimate(job_id=job.id, min_minor=3_000_000, max_minor=4_000_000, currency="USD",
                            source="Salary survey (example)", estimated_on=date(2026, 11, 1),
                            assumptions="Senior band, remote"))
    loaded = await _reload(session, job)
    assert loaded.pay_min_minor is None and loaded.pay_state == PayState.estimated


async def test_invalid_facet_shape_rejected(session):
    with pytest.raises((StatementError, ValidationError)):
        await _job(session, facets={"visa_sponsorship": {"value": "maybe"}})
    await session.rollback()


async def test_campaign_criteria_and_policy(session):
    rule = CampaignRule(effect="exclude", reason="needs existing right",
                        conditions=ConditionSet(root=Group(conditions=[
                            ValueFilter(facet="facets.work_rights", include=["existing_right_required"])])))
    campaign = Campaign(name="Remote analytics", criteria=CampaignCriteria(
        titles=["Senior Data Analyst"], rules=[rule],
        pay_floors=[PayFloor(employment_type="permanent", amount_minor=4_000_000, currency="USD")]),
        automation=AutomationPolicy(mode="prepare", per_channel={"email": "ask_then_apply"}))
    session.add(campaign)
    loaded = await _reload(session, campaign)
    assert loaded.criteria.rules[0].effect == "exclude"
    assert loaded.criteria.rules[0].conditions.root.conditions[0].include == ["existing_right_required"]
    assert loaded.criteria.pay_floors[0].amount_minor == 4_000_000
    assert loaded.automation.per_channel == {"email": "ask_then_apply"}
    assert loaded.unknown_data_policy.pay is None


async def test_rubric_weights_must_sum_to_100(session):
    good = RubricBody(criteria=[RubricCriterion(name="Fit", weight=60), RubricCriterion(name="Pay", weight=40)])
    rubric = Rubric(name="Two", body=good)
    session.add(rubric)
    loaded = await _reload(session, rubric)
    assert [c.weight for c in loaded.body.criteria] == [60, 40]
    with pytest.raises(ValidationError):
        RubricBody(criteria=[RubricCriterion(name="Fit", weight=50)])


async def test_guardrail_params_discriminated(session):
    g = Guardrail(type=GuardrailType.never_together, name="ratio", scope=["everywhere"],
                  strictness=Strictness.always_block,
                  params=NeverTogether(group_a=["F-7"], group_b=["F-8"]))
    session.add(g)
    loaded = await _reload(session, g)
    assert isinstance(loaded.params, NeverTogether)
    assert loaded.params.group_b == ["F-8"]
    with pytest.raises((StatementError, ValidationError)):
        session.add(Guardrail(type=GuardrailType.limit, name="bad", scope=[], params={"type": "limit"}))
        await session.flush()
    await session.rollback()


async def test_fact_and_answer(session):
    fact = Fact(code="F-1", kind=FactKind.metric, text="Cut reporting from 5 days to 1.", keep_out_of_prompts=True)
    answer = Answer(patterns={"canonical": "Notice period?", "variants": ["When can you start?"]},
                    value="One month", answer_class=AnswerClass.auto, review_after=date(2027, 1, 1))
    session.add_all([fact, answer])
    lf = await _reload(session, fact)
    assert lf.keep_out_of_prompts is True and lf.review_state.value == "needs_review"
    la = await session.get(Answer, answer.id)
    assert la.patterns.variants == ["When can you start?"]
    assert isinstance(la.conditions, ConditionSet) and la.confirmed_at is None


async def test_packet_round_trip_and_hash(session):
    job = await _job(session)
    app_row = Application(job_id=job.id)
    session.add(app_row)
    await session.flush()
    contents = PacketContents(
        requisition="R-1", destination=PacketDestination(url="https://boards.example.com/apply", domain="example.com"),
        sending_identity="owner@example.com",
        files=[PacketFile(name="cv.pdf", kind="cv", sha256=hashlib.sha256(b"cv").hexdigest())])
    digest = hashlib.sha256(contents.model_dump_json().encode()).hexdigest()
    packet = ApplicationPacket(application_id=app_row.id, version=1, content_hash=digest, contents=contents)
    session.add(packet)
    loaded = await _reload(session, packet)
    assert loaded.contents == contents
    assert hashlib.sha256(loaded.contents.model_dump_json().encode()).hexdigest() == digest


async def test_application_events_append_only(session):
    job = await _job(session)
    app_row = Application(job_id=job.id)
    session.add(app_row)
    await session.flush()
    await session.execute(text("INSERT INTO application_event (id, application_id, kind, actor, detail) "
                               "VALUES (:id, :a, 'stage_change', 'owner', '{}')"),
                          {"id": uuid.uuid4(), "a": app_row.id})
    await session.commit()
    with pytest.raises(Exception, match="append-only"):
        await session.execute(text("UPDATE application_event SET actor = 'x'"))
    await session.rollback()
