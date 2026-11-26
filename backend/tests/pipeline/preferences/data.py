"""An invented dataset for preference learning and the policy preview (example employers only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application, Stage
from app.models.base import ReviewState
from app.models.preferences import PreferenceFeedback
from app.models.search import Assessment, AssessmentState, Campaign, ConflictState, Job, Rubric
from app.pipeline import scoring
from app.schemas.json_types import AutomationPolicy, CampaignCriteria, CriterionRating, RubricBody
from tests.pipeline.matching.fakes import add_campaign, add_job, add_rubric
from tests.pipeline.matching.helpers import NOW

BODY = RubricBody.model_validate({"criteria": [
    {"name": "skills", "weight": 30}, {"name": "domain", "weight": 30}, {"name": "growth", "weight": 20},
    {"name": "Seniority fit", "weight": 20}]})
LIKED = {"skills": 3, "domain": 5, "growth": 3, "Seniority fit": 5}  # 80
DISLIKED = {"skills": 3, "domain": 1, "growth": 3, "Seniority fit": 0}  # 36
BORDER = {"skills": 4, "domain": 3, "growth": 3, "Seniority fit": 3}  # 66
OPEN = {"work_rights": {"value": "sponsorship_possible"}}


@dataclass
class Dataset:
    campaign: Campaign
    rubric: Rubric
    jobs: dict[str, Job] = field(default_factory=dict)
    feedback: dict[str, PreferenceFeedback] = field(default_factory=dict)


async def scored_job(s: AsyncSession, campaign: Campaign, rubric: Rubric, name: str, ratings: dict[str, int], *,
                     facets: dict[str, Any] | None = None, days_ago: int = 1, conflict: str = "winner",
                     **kw: Any) -> Job:
    job = await add_job(s, f"Role {name}", f"{name} Example", facets={**OPEN, **(facets or {})},
                        deadline=date(2026, 12, 31), created_at=NOW - timedelta(days=days_ago),
                        conflict_state=ConflictState(conflict), **kw)
    rated = [CriterionRating(criterion=k, rating=v, evidence_fact_ids=["F-1"]) for k, v in ratings.items()]
    base = scoring.weighted_score(rubric.body, rated)
    s.add(Assessment(job_id=job.id, campaign_id=campaign.id, rubric_id=rubric.id, rubric_version=rubric.version,
                     state=AssessmentState.scored, ratings=rated, base_score=base, score=base))
    await s.flush()
    return job


async def campaign_with_rubric(s: AsyncSession, *, mode: str = "auto_apply",
                               criteria: CampaignCriteria | None = None) -> tuple[Campaign, Rubric]:
    rubric = await add_rubric(s, BODY)
    campaign = await add_campaign(s, rubric, criteria=criteria, automation=AutomationPolicy(mode=mode),
                                  review_state=ReviewState.confirmed, confirmed_at=NOW - timedelta(days=10))
    return campaign, rubric


async def thumb(s: AsyncSession, data: Dataset, name: str, verdict: str, reasons: list[str] | None = None,
                note: str | None = None) -> None:
    row = PreferenceFeedback(job_id=data.jobs[name].id, campaign_id=data.campaign.id, verdict=verdict,
                             reasons=reasons or [], note=note, actor="owner")
    s.add(row)
    await s.flush()
    data.feedback[name] = row


async def seed_feedback(s: AsyncSession, *, criteria: CampaignCriteria | None = None) -> Dataset:
    """Four liked fintech remote roles, four disliked gambling on-site roles, two disliked as too senior,
    and one gambling role without feedback that the owner applied to."""
    campaign, rubric = await campaign_with_rubric(s, criteria=criteria)
    data = Dataset(campaign, rubric)
    for i in range(4):
        name = f"L{i}"
        data.jobs[name] = await scored_job(s, campaign, rubric, name, LIKED, facets={
            "industry": "Fintech", "work_model": {"value": "remote"},
            "relocation_required": {"value": "yes"}, "visa_sponsorship": {"value": "yes"}})
        await thumb(s, data, name, "up", ["more_like_this"] if i == 0 else [], note="Great team" if i == 0 else None)
    for i in range(4):
        name = f"D{i}"
        data.jobs[name] = await scored_job(s, campaign, rubric, name, DISLIKED, facets={
            "industry": "Gambling", "work_model": {"value": "on_site"}})
        await thumb(s, data, name, "down", ["employer_type"] if i < 2 else [])
    for i in range(2):
        name = f"S{i}"
        data.jobs[name] = await scored_job(s, campaign, rubric, name, BORDER, level="director")
        await thumb(s, data, name, "down", ["too_senior"])
    data.jobs["G"] = await scored_job(s, campaign, rubric, "G", BORDER, facets={"industry": "Gambling"})
    s.add(Application(job_id=data.jobs["G"].id, campaign_id=campaign.id, stage=Stage.submitted,
                      applied_at=NOW - timedelta(hours=2)))
    await s.flush()
    return data


def new_id() -> uuid.UUID:
    return uuid.uuid4()
