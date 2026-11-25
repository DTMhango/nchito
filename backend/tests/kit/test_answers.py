from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.conditions import ConditionSet, Group, ValueFilter
from app.kit import answers as a

pytestmark = pytest.mark.nodb

TODAY = date(2026, 11, 26)
T = 0.85


def not_in(*countries):
    return ConditionSet(root=Group(conditions=[ValueFilter(facet="location.country", exclude=list(countries))]))


def only_in(*countries):
    return ConditionSet(root=Group(conditions=[ValueFilter(facet="location.country", include=list(countries))]))


def rec(question="What is your notice period?", value="One month", cls="auto", **kw):
    return a.AnswerRecord(id=uuid.uuid4(), patterns=(question,), value=value, answer_class=cls,
                          conditions=kw.pop("conditions", ConditionSet()), **kw)


def run(question, answers, **kw):
    return a.match(question, answers, threshold=T, today=TODAY, **kw)


def test_normalised_similarity_ignores_case_punctuation_and_order():
    assert a.similarity("What is your notice period?", "what is your NOTICE period") == 1.0
    assert a.similarity("notice period your what is", "What is your notice period?") > 0.95
    assert a.similarity("Notice period", "Favourite colour") < 0.5


def test_auto_returns_value_on_variant_match():
    r = a.AnswerRecord(id=uuid.uuid4(), patterns=("What is your notice period?", "When can you start?"),
                       value="One month", answer_class="auto", conditions=ConditionSet())
    out = run("when can you start", [r])
    assert out.outcome == "value" and out.value == "One month" and out.answer_id == r.id


def test_no_match_asks_owner():
    out = run("Describe your favourite colour", [rec()])
    assert out.outcome == "ask_owner" and out.answer_id is None


def test_ask_first_asks_until_settled():
    q = "Expected salary?"
    assert run(q, [rec(q, "K50,000", "ask_first")]).outcome == "ask_owner"
    out = run(q, [rec(q, "K50,000", "ask_first", settled=True)])
    assert out.outcome == "value" and out.value == "K50,000"


def test_never_class_does_not_answer_and_picks_forced_choice():
    q = "What is your gender?"
    r = rec(q, None, "never", forced_choice="Prefer not to say")
    out = run(q, [r], options=["Male", "Female", "Prefer not to say"])
    assert out.outcome == "do_not_answer" and out.select == "Prefer not to say"
    out = run(q, [r], options=["Male", "Female"])
    assert out.outcome == "do_not_answer" and out.select is None
    assert run(q, [r]).outcome == "do_not_answer"


def test_owner_only_class_asks_owner():
    q = "Please sign the declaration"
    out = run(q, [rec(q, "x", "owner_only")])
    assert out.outcome == "ask_owner" and out.value is None


def test_country_condition_picks_the_answer_that_holds():
    q = "Will you require visa sponsorship?"
    answers = [rec(q, "No", "auto", conditions=only_in("ZM")), rec(q, "Yes", "auto", conditions=not_in("ZM"))]
    assert run(q, answers, context={"country": "ZM"}).value == "No"
    assert run(q, answers, context={"country": "GB"}).value == "Yes"


def test_missing_context_for_a_condition_is_not_yes():
    q = "Will you require visa sponsorship?"
    only_zm = [rec(q, "No", "auto", conditions=only_in("ZM"))]
    assert run(q, only_zm).outcome == "ask_owner"
    assert run(q, only_zm, context={"country": "GB"}).outcome == "ask_owner"


def test_unconfirmed_answer_cannot_drive_automation():
    out = run("What is your notice period?", [rec(confirmed=False)])
    assert out.outcome == "ask_owner" and out.answer_id is not None


def test_review_due_pauses_the_answer():
    assert run("What is your notice period?", [rec(review_after=date(2026, 11, 26))]).outcome == "ask_owner"
    assert run("What is your notice period?", [rec(review_after=date(2027, 1, 1))]).outcome == "value"


def test_scope_must_match_context():
    q = "Why do you want to work here?"
    r = rec(q, "Because", "auto", scope="this_employer", scope_ref="Acme Ltd")
    assert run(q, [r], context={"employer": "acme ltd"}).outcome == "value"
    assert run(q, [r], context={"employer": "Other"}).outcome == "ask_owner"
    assert run(q, [r]).outcome == "ask_owner"


def test_narrower_scope_wins_over_all_matching():
    q = "Expected salary?"
    general = rec(q, "K40,000", "auto")
    specific = rec(q, "K60,000", "auto", scope="this_country", scope_ref="ZM")
    assert run(q, [general, specific], context={"country": "ZM"}).value == "K60,000"
    assert run(q, [general, specific], context={"country": "GB"}).value == "K40,000"


def test_equal_conflicting_answers_ask_owner():
    q = "Do you hold a driving licence?"
    assert run(q, [rec(q, "Yes", "auto"), rec(q, "No", "auto")]).outcome == "ask_owner"


def test_threshold_is_respected():
    q = "What is your notice period?"
    asked = "What is your current notice period?"
    assert a.match(asked, [rec(q)], threshold=0.99, today=TODAY).outcome == "ask_owner"
    assert a.match(asked, [rec(q)], threshold=0.7, today=TODAY).outcome == "value"
