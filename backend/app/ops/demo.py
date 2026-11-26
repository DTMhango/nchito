"""``nchito demo-job``: one fictional open role for manual testing (never in production).

Inserts a made-up posting (an ``example.com`` employer and application address), normalised by the same
parser as any source, scores it against the campaigns with an in-process stand-in for the score model (no
provider is called, nothing is spent), and opens a shortlisted application so a fresh instance with the example
kit has something to tailor in the Studio. The posting's address stays unconfirmed, exactly as a real one would.
Nothing here is personal data and nothing here runs in the pipeline.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.llm.fake import FakeCall, FakeLLMClient
from app.models.applications import Application, Stage
from app.models.search import Assessment, Campaign, JobSighting
from app.pipeline import normalise, scoring
from app.schemas.json_types import JobFacets
from app.sources.base import RawJob

DEMO_TAG = "demo"
DEMO_MODEL = "demo (no model call)"
DEMO_RATING = 4  # out of 5 on every criterion: a role worth tailoring, not an automatic yes
EMPLOYER = "Example Analytics Co (fictional)"
APPLY_TO = "careers@analytics-co.example.com"


class DemoRefused(RuntimeError):
    pass


@dataclass
class DemoJob:
    job_id: uuid.UUID
    application_id: uuid.UUID
    scores: dict[str, int | None]


def refuse_in_production() -> None:
    if get_config().is_production or os.environ.get("ENV", "").lower() == "production":
        raise DemoRefused("demo-job is for manual testing only and refuses to run in production")


def _posting(deadline: str) -> str:
    return (
        f"Senior Data Analyst at {EMPLOYER}\n\n"
        "We are a fictional analytics firm. You will build forecasting models, automate reporting in Python and "
        "SQL, and present findings to regional teams.\n\n"
        "Requirements: 5+ years in data analysis; SQL and Python; Power BI or a similar tool; clear writing.\n"
        "This is a permanent, fully remote role open worldwide; visa sponsorship is not needed.\n"
        "Salary: USD 50,000 - 60,000 per year.\n"
        f"To apply, email your CV and a cover letter to {APPLY_TO} by {deadline}.\n"
    )


def _stand_in(kit: scoring.KitSnapshot):
    """Rates every criterion the same and cites the first approved facts: no provider, no spend."""
    cited = list(kit.facts)[:2]

    def reply(call: FakeCall) -> dict[str, Any]:
        text = "\n".join(getattr(p, "text", "") for m in call.messages for p in m.parts)
        names = [line[2:].split(" (weight", 1)[0] for line in text.splitlines() if line.startswith("- ")
                 and " (weight " in line]
        return {"ratings": [{"criterion": n, "rating": DEMO_RATING, "evidence_fact_ids": cited,
                             "note": "demo score: no model was called"} for n in names],
                "gaps": ["demo score: rate this role yourself before relying on it"]}

    return reply


async def create(session: AsyncSession) -> DemoJob:
    """Insert, score and shortlist one fictional role. The caller commits."""
    refuse_in_production()
    now = utcnow()
    deadline = (now + timedelta(days=30)).date()
    marker = uuid.uuid4().hex[:8]
    raw = RawJob(source_url=f"https://careers.analytics-co.example.com/jobs/demo-{marker}",
                 title="Senior Data Analyst", employer=EMPLOYER, raw_text=_posting(deadline.isoformat()),
                 location_raw="Remote", posted_at=now, deadline=deadline, requisition_id=f"DEMO-{marker}",
                 pay_text="USD 50,000 - 60,000 per year", remote_hint="worldwide", extra={"listing_open": True})
    job = (await normalise.parse_with_aliases(session, raw)).to_job(now)
    job.tags = [DEMO_TAG]
    job.function = "analytics"
    job.facets = JobFacets.model_validate({
        "work_model": {"value": "remote", "evidence": "fully remote role open worldwide"},
        "remote_scope": {"value": "worldwide", "evidence": "fully remote role open worldwide"},
        "employment_type": {"value": "permanent", "evidence": "This is a permanent, fully remote role"},
        "work_rights": {"value": "sponsorship_possible", "evidence": "visa sponsorship is not needed"},
        "visa_sponsorship": {"value": "not_stated"},
        "required_skills": ["SQL", "Python"], "preferred_skills": ["Power BI"]})
    session.add(job)
    await session.flush()
    session.add(JobSighting(job_id=job.id, url=raw.source_url, first_seen_at=now, last_seen_at=now))

    campaigns = list((await session.scalars(select(Campaign).order_by(Campaign.priority.desc(),
                                                                       Campaign.created_at))).all())
    client = FakeLLMClient(provider="demo", default_model=DEMO_MODEL)
    client.default = _stand_in(await scoring.kit_snapshot(session))
    if campaigns:
        await scoring.score_jobs(session, None, [job.id], client=client, now=now,
                                 campaign_ids=[c.id for c in campaigns])
    assessments = list((await session.scalars(select(Assessment).where(Assessment.job_id == job.id))).all())
    for a in assessments:
        if a.model:
            a.model = DEMO_MODEL
    best = max(assessments, key=lambda a: a.score or -1, default=None)
    app = Application(job_id=job.id, campaign_id=best.campaign_id if best else None,
                      assessment_id=best.id if best else None, stage=Stage.shortlisted, origin="system")
    session.add(app)
    job.triage = "shortlisted"
    await session.flush()
    await audit.record(session, actor="system", action="job.demo_created", subject_type="job", subject_id=job.id,
                       detail={"application_id": str(app.id), "calls": len(client.calls), "provider": "none"})
    names = {c.id: c.name for c in campaigns}
    return DemoJob(job.id, app.id, {names[a.campaign_id]: a.score for a in assessments})
