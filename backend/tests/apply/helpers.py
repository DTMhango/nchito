"""Builders for the apply tests (invented employers, example.com addresses only)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import packets
from app.models.applications import Application, Stage
from app.models.base import ReviewState
from app.models.search import Assessment, AssessmentState, Campaign, Job
from app.pipeline import conflicts
from app.schemas.json_types import AutomationPolicy, PacketEmail
from tests.pipeline.matching.fakes import add_campaign, add_job, add_rubric

FACETS = {"work_rights": {"value": "sponsorship_possible"}, "visa_sponsorship": {"value": "yes"},
          "work_model": {"value": "remote"}, "remote_scope": {"value": "worldwide"},
          "employment_type": {"value": "permanent"}}


async def setup_campaign(session: AsyncSession, mode: str = "ask_then_apply", **per_channel: str) -> Campaign:
    campaign = await add_campaign(session, await add_rubric(session),
                                  automation=AutomationPolicy(mode=mode, per_channel=per_channel),
                                  review_state=ReviewState.confirmed)
    campaign.confirmed_at = datetime(2026, 11, 1)
    await session.flush()
    return campaign


async def setup_app(session: AsyncSession, campaign: Campaign, *, title: str = "Data Analyst",
                    employer: str = "Acme Example", score: int = 90, now: datetime, function: str = "analytics",
                    stage: Stage = Stage.ready, resolve: bool = True) -> tuple[Job, Application]:
    job = await add_job(session, title, employer, function=function, facets=FACETS, deadline=date(2026, 12, 31),
                        apply_url="https://boards.greenhouse.io/acme/jobs/1",
                        pay_state="stated", pay_min_minor=50_000_00, pay_max_minor=60_000_00, pay_currency="USD",
                        pay_period="year", raw_text=f"{title} at {employer}. Apply to jobs@acme.example.com.")
    job.last_checked_at = now
    # The posting's address, confirmed by the owner (app.apply.target): the email channel may send to it.
    job.apply_email = job.apply_email_confirmed = "jobs@acme.example.com"
    assessment = Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored, score=score,
                            base_score=score, filter_results=[], rubric_id=campaign.rubric_id)
    session.add(assessment)
    await session.flush()
    app = Application(job_id=job.id, campaign_id=campaign.id, assessment_id=assessment.id, stage=stage)
    session.add(app)
    await session.flush()
    if resolve:
        await conflicts.resolve_employers(session, [employer], now=now)
        await session.refresh(job)
    return job, app


def email_draft(body: str = "Dear hiring team, please find my application attached.",
                to: str = "jobs@acme.example.com") -> packets.PacketDraft:
    return packets.PacketDraft(channel="email", destination_url="", sending_identity="owner@example.com",
                               email=PacketEmail(to=[to], subject="Application: Data Analyst", body=body))


def browser_draft(url: str = "https://boards.greenhouse.io/acme/jobs/1") -> packets.PacketDraft:
    return packets.PacketDraft(channel="browser", destination_url=url, sending_identity="owner@example.com",
                               answers=[packets.DraftAnswer(question="Notice period", value="One month")])
