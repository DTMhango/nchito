"""Fictional Kit and job for the tailoring tests (invented people and employers only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conditions import ConditionSet
from app.models.applications import Application, Stage
from app.models.base import Origin, ReviewState
from app.models.kit import (
    Answer,
    AnswerClass,
    Experience,
    Fact,
    FactKind,
    FactStatus,
    Guardrail,
    GuardrailType,
    Severity,
    Skill,
    SkillClaim,
    Strictness,
    Track,
)
from app.models.search import Campaign, Job
from app.schemas.json_types import AnswerPatterns, GuardrailParams, Requirement, StructuredLocation, TitleSpan

CONFIRMED: dict[str, Any] = {"review_state": ReviewState.confirmed, "origin": Origin.owner}


@dataclass
class World:
    job: Job
    app: Application
    globex: Experience
    initech: Experience
    track: Track


async def add_fact(session: AsyncSession, code: str, text: str, *, exp: Experience | None = None,
                   kind: FactKind = FactKind.achievement, status: FactStatus = FactStatus.approved,
                   confirmed: bool = True, keep_out: bool = False, tracks: list[str] | None = None) -> Fact:
    fact = Fact(code=code, kind=kind, text=text, experience_id=exp.id if exp else None, status=status,
                keep_out_of_prompts=keep_out, tracks=tracks or [], tags=[],
                review_state=ReviewState.confirmed if confirmed else ReviewState.needs_review, origin=Origin.owner)
    session.add(fact)
    await session.flush()
    return fact


async def add_guardrail(session: AsyncSession, params: GuardrailParams, *, name: str = "rule",
                        strictness: Strictness = Strictness.always_block, severity: Severity = Severity.block,
                        scope: list[str] | None = None) -> Guardrail:
    row = Guardrail(type=GuardrailType(params.type), name=name, params=params, scope=scope or ["everywhere"],
                    severity=severity, strictness=strictness, enabled=True, **CONFIRMED)
    session.add(row)
    await session.flush()
    return row


async def add_answer(session: AsyncSession, question: str, value: str | None, *,
                     klass: AnswerClass = AnswerClass.auto, confirmed: bool = True, settled: bool = False,
                     material: bool = False, conditions: ConditionSet | None = None,
                     forced_choice: str | None = None) -> Answer:
    row = Answer(patterns=AnswerPatterns(canonical=question), value=value, answer_class=klass, settled=settled,
                 material=material, conditions=conditions or ConditionSet(), forced_choice=forced_choice,
                 review_state=ReviewState.confirmed if confirmed else ReviewState.needs_review, origin=Origin.owner)
    session.add(row)
    await session.flush()
    return row


async def world(session: AsyncSession, *, raw_text: str = "We need a data analyst with SQL.",
                stage: Stage = Stage.shortlisted) -> World:
    track = Track(key="analytics", name="Analytics", lead_fact_codes=["F-1"], **CONFIRMED)
    session.add(track)
    globex = Experience(org="Globex Example Ltd", titles=[TitleSpan(title="Data Analyst", start="2019-03",
                                                                    end="2022-06")],
                        start_date="2019-03", end_date="2022-06", forbidden_titles=["Head of Data"],
                        title_variants={"analytics": ["Analytics Specialist"]}, **CONFIRMED)
    initech = Experience(org="Initech Example", titles=[TitleSpan(title="Senior Analyst", start="2022-07")],
                         start_date="2022-07", **CONFIRMED)
    session.add_all([globex, initech])
    await session.flush()
    await add_fact(session, "F-1", "Cut monthly reporting time by 40% by automating the sales pack.", exp=globex)
    await add_fact(session, "F-2", "Contributed to a pricing review that saved USD 120,000 per year.", exp=initech)
    await add_fact(session, "F-3", "In 2023 grew active customers by 15%.", exp=initech)
    await add_fact(session, "F-4", "In 2021 grew active customers by 10%.", exp=globex)
    await add_fact(session, "F-5", "BSc in Statistics, University of Example.", kind=FactKind.education)
    await add_fact(session, "F-6", "Confidential: 3 of 47 analysts were let go in 2021.", keep_out=True)
    await add_fact(session, "F-7", "Draft idea: led a team of 9.", status=FactStatus.draft)
    session.add_all([Skill(name="SQL", claim=SkillClaim.yes, **CONFIRMED),
                     Skill(name="Python", claim=SkillClaim.yes, **CONFIRMED),
                     Skill(name="Tableau", claim=SkillClaim.no, **CONFIRMED),
                     Skill(name="COBOL", claim=SkillClaim.never, **CONFIRMED)])
    campaign = Campaign(name="Analytics roles", track_id=track.id)
    session.add(campaign)
    job = Job(title="Data Analyst", employer="Acme Example Corp", canonical_employer="Acme Example Corp",
              content_hash=uuid.uuid4().hex.ljust(64, "0"), raw_text=raw_text,
              requirements=[Requirement(text="SQL and reporting automation", skill="SQL")],
              location=StructuredLocation(country="ZM"))
    session.add(job)
    await session.flush()
    app = Application(job_id=job.id, campaign_id=campaign.id, stage=stage)
    session.add(app)
    await session.flush()
    return World(job=job, app=app, globex=globex, initech=initech, track=track)


def good_spec(w: World) -> dict[str, Any]:
    """A draft that passes every code check against :func:`world`."""
    return {
        "headline": {"text": "Data analyst who automates reporting", "fact_ids": ["F-1"]},
        "summary": {"text": "Cut monthly reporting time by 40% at Globex Example Ltd.", "fact_ids": ["F-1"]},
        "competencies": [{"text": "Reporting automation", "fact_ids": ["F-1"]}],
        "experience": [
            {"experience_id": str(w.globex.id), "title": "Data Analyst",
             "bullets": [{"text": "Cut monthly reporting time by 40% by automating the sales pack.",
                          "fact_ids": ["F-1"]}]},
            {"experience_id": str(w.initech.id), "title": "Senior Analyst",
             "bullets": [{"text": "Contributed to a pricing review that saved USD 120,000 per year.",
                          "fact_ids": ["F-2"]}]},
        ],
        "skills": ["SQL", "Python"],
        "letter": [{"text": "I am applying for the Data Analyst role at Acme Example Corp.", "fact_ids": []},
                   {"text": "At Globex Example Ltd I cut monthly reporting time by 40%.", "fact_ids": ["F-1"]}],
        "requirement_match": [{"requirement": "SQL", "strength": "strong", "evidence_fact_ids": ["F-1"]}],
    }
