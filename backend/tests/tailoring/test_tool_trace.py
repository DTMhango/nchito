"""Tool tracing: an invented tool, technology or skill in a sentence that cites a real fact is a block in every
generator (CV/letter specs, interview pack sections, mock-interview suggested answers; follow-up messages are
covered in tests/followups/test_messages.py). Invented data only."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from app.pipeline.checks.items import Item
from app.pipeline.checks.service import deterministic, posting_terms
from app.pipeline.checks.tools import ToolTerms, tool_findings
from app.pipeline.interview import shapes as sh
from app.pipeline.interview import truth
from app.pipeline.interview.mock import checks as mock_checks
from tests.tailoring.test_checks import CFG, GLOBEX, JOB_TERMS, bullet, kit, spec

pytestmark = pytest.mark.nodb

TOOLS = ToolTerms(terms=("Kubernetes", "Power BI", "Excel"), ignore=("KPI", "CV"),
                  role_phrases=("the role uses", "have not used"), token_detection=True)
TCFG = dataclasses.replace(CFG, tools=TOOLS)
POSTING = ["Kafka", "Snowflake", "SQL"]


def blocks(findings) -> list[str]:
    return [f.detail for f in findings if f.check == "fact_trace" and f.status == "block" and "tool" in f.detail]


def cv(text: str, *codes: str, **kw: Any):
    return deterministic(spec(experience=bullet(text, *codes)), kw.pop("k", None) or kit(), TCFG,
                         job_terms=JOB_TERMS, posting_terms=kw.pop("posting", POSTING)).findings


# ----- CV and letter --------------------------------------------------------------------------------

def test_a_cv_bullet_with_an_invented_tool_citing_a_real_fact_is_blocked():
    found = blocks(cv("Cut monthly reporting time by 40% by automating the sales pack in Kubernetes.", "F-1"))
    assert found and "Kubernetes" in found[0]


def test_a_cv_bullet_whose_tools_are_confirmed_skills_or_in_the_fact_passes():
    assert blocks(cv("Cut monthly reporting time by 40% by automating the sales pack with SQL and Python.",
                     "F-1")) == []


def test_an_unknown_technical_token_is_caught_when_detection_is_on():
    found = blocks(cv("Cut monthly reporting time by 40% by automating the sales pack on DynamoDB.", "F-1"))
    assert any("DynamoDB" in d for d in found)
    off = dataclasses.replace(TCFG, tools=dataclasses.replace(TOOLS, token_detection=False))
    out = deterministic(spec(experience=bullet("Cut monthly reporting time by 40% by automating the sales pack "
                                               "on DynamoDB.", "F-1")), kit(), off, job_terms=JOB_TERMS).findings
    assert blocks(out) == []


def test_ignored_acronyms_and_the_verb_excel_are_not_tools():
    assert blocks(cv("Cut monthly reporting time by 40% by automating the sales pack, a KPI the team tracked.",
                     "F-1")) == []
    letter = [{"text": "I excel at automating reporting at Acme Example Corp.", "fact_ids": []}]
    out = deterministic(spec(letter=letter), kit(), TCFG, job_terms=JOB_TERMS).findings
    assert blocks(out) == []


def test_posting_keyword_stuffing_is_caught():
    competencies = [{"text": "Kafka, Snowflake and SQL pipelines", "fact_ids": ["F-1"]}]
    found = blocks(deterministic(spec(competencies=competencies), kit(), TCFG, job_terms=JOB_TERMS,
                                 posting_terms=POSTING).findings)
    assert any("Kafka" in d and "posting asks for it" in d for d in found)
    assert any("Snowflake" in d for d in found)
    assert not any("'SQL'" in d for d in found)  # a confirmed skill


def test_the_role_uses_phrasing_names_a_tool_without_claiming_it():
    letter = [{"text": "I understand the role uses Kafka and Snowflake.", "fact_ids": []},
              {"text": "I have not used Kafka yet, but I automated our sales pack.", "fact_ids": ["F-1"]}]
    out = deterministic(spec(letter=letter), kit(), TCFG, job_terms=JOB_TERMS, posting_terms=POSTING).findings
    assert blocks(out) == []


def test_an_alias_matches_its_canonical_skill_both_ways():
    k = dataclasses.replace(kit(), skill_aliases={"postgres": "PostgreSQL", "ms excel": "Excel"})
    # The fact says PostgreSQL; the draft says Postgres.
    from tests.tailoring.test_checks import fact
    facts = {**k.facts, "F-9": fact("F-9", "Moved 12 reports to PostgreSQL.", GLOBEX)}
    k = dataclasses.replace(k, facts=facts)
    assert blocks(cv("Moved 12 reports to Postgres.", "F-9", k=k)) == []
    # A confirmed skill named by an alias passes too.
    from app.pipeline.checks.kit import SkillView
    k2 = dataclasses.replace(k, skills={**k.skills, "excel": SkillView("Excel", "yes", True)})
    assert blocks(cv("Cut monthly reporting time by 40% by automating the sales pack in MS Excel.", "F-1",
                     k=k2)) == []


def test_a_skill_the_owner_does_not_claim_is_blocked_unless_the_fact_names_it():
    found = blocks(cv("Cut monthly reporting time by 40% by automating the sales pack in Tableau.", "F-1"))
    assert any("Tableau" in d for d in found)


def test_the_kit_employer_and_job_title_are_not_tools():
    items = [Item("letter[0]", "letter", "I joined Globex Example Ltd as a Data Analyst using SQL.", ("F-1",))]
    assert tool_findings(items, {"letter[0]": "x"}, kit(), TOOLS, job_terms=["ACME", "BI Analyst"]) == []
    items = [Item("letter[0]", "letter", "I want to bring my work to ACME.", ())]
    assert tool_findings(items, {}, kit(), TOOLS, job_terms=["ACME"]) == []


def test_posting_terms_come_from_facets_and_requirements():
    from types import SimpleNamespace

    from app.schemas.json_types import JobFacets, Requirement
    job = SimpleNamespace(facets=JobFacets(required_skills=["Kafka"], preferred_skills=["kafka", "dbt"]),
                          requirements=[Requirement(text="Snowflake experience", skill="Snowflake")])
    assert posting_terms(job) == ["Kafka", "dbt", "Snowflake"]


# ----- interview pack -------------------------------------------------------------------------------

def test_an_invented_tool_in_an_interview_pack_section_is_blocked():
    content = sh.WhyYou(points=[sh.TalkingPoint(point=sh.Claim(
        text="I cut monthly reporting time by 40% with Kubernetes.", fact_ids=["F-1"]), requirement="Automation")])
    found = blocks(truth.check("why_you", content, kit(), TCFG, job_terms=JOB_TERMS,
                               posting_terms=POSTING).findings)
    assert any("Kubernetes" in d for d in found)
    gaps = sh.Gaps(items=[sh.Gap(requirement="Kafka", gap="No Kafka in the Kit", answer=sh.Claim(
        text="I have not used Kafka, but I automated the sales pack.", fact_ids=["F-1"]))])
    assert blocks(truth.check("gaps", gaps, kit(), TCFG, job_terms=JOB_TERMS, posting_terms=POSTING).findings) == []


# ----- mock interview -------------------------------------------------------------------------------

def test_an_invented_tool_in_a_mock_interview_suggested_answer_is_removed():
    claims = [sh.Claim(text="I cut monthly reporting time by 40% using Kafka.", fact_ids=["F-1"]),
              sh.Claim(text="I automated the sales pack in Snowflake.", fact_ids=["A1"])]
    kept, removed = mock_checks.check_suggested(claims, kit(), {1: "I automated the sales pack in Snowflake."},
                                                TCFG, job_terms=JOB_TERMS, posting_terms=POSTING)
    assert [k["text"] for k in kept] == ["I automated the sales pack in Snowflake."]  # the owner said it
    assert len(removed) == 1 and any("Kafka" in r for r in removed[0]["reasons"])
