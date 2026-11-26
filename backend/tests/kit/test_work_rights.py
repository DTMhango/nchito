"""Work rights from the Kit's confirmed answers: pass / fail / unknown against the job's facets."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.conditions import ConditionSet, Group, ValueFilter
from app.kit import work_rights
from app.kit.answers import AnswerRecord
from app.models.base import ReviewState
from app.models.kit import Answer, AnswerClass
from app.pipeline import filters
from app.pipeline.decisions import decide
from app.schemas.json_types import AnswerPatterns
from tests.pipeline.matching.helpers import campaign, data, default_settings, job

TODAY = date(2026, 11, 26)
NOW = datetime(2026, 11, 26, 10, tzinfo=UTC)


def rec(question: str, value: str, *, confirmed: bool = True, country: str | None = None, **kw) -> AnswerRecord:
    cond = ConditionSet()
    if country:
        cond = ConditionSet(root=Group(conditions=[ValueFilter(facet="location.country", include=[country])]))
    return AnswerRecord(id=__import__("uuid").uuid4(), patterns=(question,), value=value, answer_class="auto",
                        conditions=cond, confirmed=confirmed, **kw)


EXISTING = {"work_rights": "existing_right_required", "visa_sponsorship": "not_stated"}
RIGHT = "Are you legally authorised to work in this country?"
SPONSOR = "Will you now or in the future require visa sponsorship?"


def verdict(answers, facets, *, policy=None, loc_country="Examplestan"):
    kit = work_rights.resolve(answers, [loc_country], today=TODAY).to_record()
    camp = campaign(unknown_data_policy={"eligibility": policy} if policy else {})
    rec_ = job(facets=facets, location={"country": loc_country, "region": None, "city": None, "raw": None})
    rec_["kit_work_rights"] = kit
    d = decide(data(job_rec=rec_, camp=camp, settings=default_settings()))
    return next(g for g in d.gates if g.gate == "work_rights"), d


def test_sponsorship_offered_and_needed_passes_naming_the_answer():
    gate, _ = verdict([rec(SPONSOR, "yes"), rec(RIGHT, "no", country="Examplestan")],
                      {"work_rights": "sponsorship_possible", "visa_sponsorship": "yes"})
    assert gate.outcome == "pass" and "sponsorship is offered and you need it" in gate.reason
    assert SPONSOR in gate.reason


def test_existing_right_required_and_none_held_fails_naming_the_answer():
    gate, d = verdict([rec(RIGHT, "no", country="Examplestan")],
                      {"work_rights": "existing_right_required", "visa_sponsorship": "no"})
    assert gate.outcome == "fail" and RIGHT in gate.reason and d.verdict == "excluded"


def test_existing_right_required_and_right_held_passes():
    gate, _ = verdict([rec(RIGHT, "yes", country="Examplestan")], EXISTING)
    assert gate.outcome == "pass" and RIGHT in gate.reason


def test_unconfirmed_answer_never_counts():
    gate, _ = verdict([rec(RIGHT, "yes", confirmed=False, country="Examplestan")],
                      EXISTING)
    assert gate.outcome == "unknown"


def test_answer_for_another_country_or_due_for_review_is_unknown():
    gate, _ = verdict([rec(RIGHT, "yes", country="Elsewhere")], EXISTING)
    assert gate.outcome == "unknown"
    gate, _ = verdict([rec(RIGHT, "yes", review_after=date(2026, 1, 1))], EXISTING)
    assert gate.outcome == "unknown"


def test_disagreeing_answers_are_unknown():
    gate, _ = verdict([rec(RIGHT, "yes"), rec("Do you have the right to work here?", "no")],
                      EXISTING)
    assert gate.outcome == "unknown"


@pytest.mark.parametrize("policy,outcome,mandatory", [
    ("review", "unknown", True), ("pass_with_penalty", "unknown", False),
    ("pass_blocks_auto", "unknown", False), ("fail", "fail", True)])
def test_not_stated_is_unknown_under_each_policy(policy, outcome, mandatory):
    gate, d = verdict([], {"work_rights": "not_stated", "visa_sponsorship": "not_stated"},
                      policy=policy)
    assert gate.outcome == outcome and gate.mandatory is mandatory
    assert not d.auto_apply_allowed  # unknown is never yes


def test_classify_and_yes_no():
    assert work_rights.classify([RIGHT]) == "right" and work_rights.classify([SPONSOR]) == "sponsorship"
    assert work_rights.classify(["Would you relocate?"]) == "relocation"
    assert work_rights.classify(["Favourite colour"]) is None
    assert work_rights.yes_no(" Yes ") is True and work_rights.yes_no("maybe") is None


async def test_job_records_read_the_kit_answer_bank(session):
    from app.models.search import Job

    def ans(question, value, state):
        return Answer(patterns=AnswerPatterns(canonical=question), value=value, answer_class=AnswerClass.auto,
                      review_state=state)

    session.add_all([ans(RIGHT, "yes", ReviewState.confirmed), ans(SPONSOR, "no", ReviewState.needs_review)])
    j = Job(title="Analyst", employer="Example Co", canonical_employer="Example Co", content_hash="h")
    session.add(j)
    await session.flush()
    (_, record), = await filters.load_records(session, now=NOW, job_ids=[j.id])
    kit = record["kit_work_rights"]
    assert kit["right"]["value"] is True and kit["right"]["question"] == RIGHT  # no condition: applies anywhere
    assert kit["needs_sponsorship"]["value"] is None  # unconfirmed never counts
