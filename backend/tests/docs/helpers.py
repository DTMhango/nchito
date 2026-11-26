"""Shared setup for the render tests: the fictional example kit plus an application with a spec."""

from __future__ import annotations

import json

from sqlalchemy import delete, select, update

from app.kit.loader import load_kit
from app.kit.schema import KitFile
from app.models.applications import Application
from app.models.base import ReviewState
from app.models.kit import Experience, Fact, Template
from app.schemas.json_types import ApplicationSpec, SpecExperience, SpecItem
from tests.conftest import REPO
from tests.tracking.helpers import make_app, make_job

KIT = REPO / "kits" / "example"


async def load_example(session) -> dict[str, str]:
    """Load the example kit, confirm its facts, return org first word -> experience id."""
    kit = KitFile.model_validate(json.loads((KIT / "kit.json").read_text(encoding="utf-8")))
    await load_kit(session, kit)
    await session.execute(update(Fact).values(review_state=ReviewState.confirmed))
    await session.execute(delete(Template))  # the sample kit's template rows would override the built-ins
    await session.commit()
    rows = (await session.scalars(select(Experience))).all()
    return {e.org.split()[0]: str(e.id) for e in rows}


def example_spec(exp: dict[str, str], *, extra_bullets: int = 0) -> ApplicationSpec:
    bullets = [SpecItem(text="Cut monthly reporting time from 5 days to 1 day by automating 40 reports in "
                             "Python and Power BI.", fact_ids=["F-2"])]
    bullets += [SpecItem(text=f"Delivered forecasting improvement number {i} for the finance team. " * 3)
                for i in range(extra_bullets)]
    return ApplicationSpec(
        headline=SpecItem(text="Senior Data Analyst | Forecasting and automation"),
        summary=SpecItem(text="Data analyst with eight years in insurance and consumer analytics.",
                         fact_ids=["F-1"]),
        competencies=[SpecItem(text="Forecasting"), SpecItem(text="Dashboard design")],
        experience=[
            SpecExperience(experience_id=exp["Kafue"], bullets=bullets),
            SpecExperience(experience_id=exp["Zambezi"], title="Actuarial Assistant",
                           bullets=[SpecItem(text="Built claims reserving workbooks used by the actuarial team.")]),
        ],
        skills=["Python", "SQL", "Power BI"],
        letter=[SpecItem(text="I am applying for the Senior Data Analyst role at Acme Ltd."),
                SpecItem(text="At Kafue Analytics I cut reporting time from 5 days to 1 day."),
                SpecItem(text="I would welcome the chance to discuss how I can help your team.")],
    )


async def make_application(session, spec: ApplicationSpec) -> Application:
    app = await make_app(session, await make_job(session, "Senior Data Analyst", "Acme Ltd"), spec=spec)
    await session.commit()
    return app
