"""``nchito demo-job``: one fictional role, scored with no provider call, refused in production."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_config
from app.models.applications import Application, Stage
from app.models.search import Assessment, AssessmentState, Job
from app.ops import demo
from tests.apply.helpers import setup_campaign
from tests.docs.helpers import load_example


async def test_demo_job_is_fictional_scored_and_ready_to_tailor(session):
    await load_example(session)
    campaign = await setup_campaign(session)
    made = await demo.create(session)
    job = await session.get(Job, made.job_id)
    assert job.employer.endswith("(fictional)") and demo.DEMO_TAG in job.tags
    assert job.apply_email == demo.APPLY_TO and job.apply_email.endswith(".example.com")
    assert job.apply_email_confirmed is None  # found in a posting: unconfirmed, like any other
    assert job.pay_state.value == "stated" and job.availability.value == "open"
    assessment = await session.scalar(select(Assessment).where(Assessment.job_id == job.id,
                                                               Assessment.campaign_id == campaign.id))
    assert assessment.state == AssessmentState.scored and assessment.model == demo.DEMO_MODEL
    assert assessment.score is not None and made.scores[campaign.name] == assessment.score
    app = await session.get(Application, made.application_id)
    assert app.stage == Stage.shortlisted and app.campaign_id == campaign.id and app.job_id == job.id


async def test_demo_job_without_a_campaign_still_opens_an_application(session):
    made = await demo.create(session)
    assert made.scores == {}
    assert (await session.get(Application, made.application_id)).campaign_id is None


async def test_demo_job_refuses_in_production(session, monkeypatch):
    monkeypatch.setattr(get_config(), "environment", "production")
    with pytest.raises(demo.DemoRefused):
        await demo.create(session)
    monkeypatch.setattr(get_config(), "environment", "development")
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(demo.DemoRefused):
        demo.refuse_in_production()
