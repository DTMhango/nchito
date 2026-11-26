from __future__ import annotations

import pytest

from app.kit import guardrails as g
from app.schemas.json_types import (
    AttachPolicy,
    FormatRule,
    LimitRule,
    NeverMention,
    NeverTogether,
    OmitField,
    Positioning,
    RequireWording,
)

pytestmark = pytest.mark.nodb


def rule(params, *, scope=("everywhere",), strictness="always_block", severity="block", id="r1"):
    return g.Rule(id=id, name=f"rule {id}", params=params, scope=scope, strictness=strictness, severity=severity)


def cv(text, **kw):
    return g.Document(scope="cv", text=text, **kw)


def test_never_mention_terms_and_regex_word_boundaries():
    r = rule(NeverMention(terms=["Tableau"], regex=[r"\b19\d\d\b"]))
    hits = g.check([r], [cv("Built dashboards in tableau."), g.Document("letter", "Born in 1987.")])
    assert {(v.document_scope, v.type) for v in hits} == {("cv", "never_mention"), ("letter", "never_mention")}
    assert g.check([r], [cv("Tableaux of results")]) == []  # not the whole word


def test_never_mention_respects_scope():
    r = rule(NeverMention(terms=["secret"]), scope=("cv",))
    assert g.check([r], [g.Document("letter", "a secret")]) == []
    assert len(g.check([r], [cv("a secret")])) == 1


def test_never_together_pair_split_across_two_documents():
    r = rule(NeverTogether(group_a=["12 enterprise clients"], group_b=["USD 3 million"]))
    cv_doc = cv("Managed 12 enterprise clients.")
    letter = g.Document("letter", "We billed USD 3 million last year.")
    assert g.check([r], [cv_doc]) == []
    assert g.check([r], [letter]) == []
    hits = g.check([r], [cv_doc, letter])
    assert len(hits) == 1 and hits[0].status == "block" and hits[0].type == "never_together"


def test_never_together_matches_fact_codes_and_file_names():
    r = rule(NeverTogether(group_a=["F-7"], group_b=["acme-fees"]))
    docs = [cv("x", fact_codes=frozenset({"F-7"}))]
    assert g.check([r], docs) == []
    assert len(g.check([r], docs, file_names=["acme-fees.pdf"])) == 1


def test_require_wording():
    r = rule(RequireWording(use="Senior Data Analyst", instead_of=["Lead Analyst"]))
    hits = g.check([r], [cv("Lead Analyst at Acme")])
    assert len(hits) == 1 and "Senior Data Analyst" in hits[0].detail
    assert g.check([r], [cv("Senior Data Analyst at Acme")]) == []


def test_omit_field_by_label_and_structured_field():
    r = rule(OmitField(fields=["national_id", "date_of_birth"]), scope=("cv",))
    assert len(g.check([r], [cv("Date of birth: 1 Jan 1990")])) == 1
    assert len(g.check([r], [cv("hello", fields={"national_id": "123"})])) == 1
    assert g.check([r], [cv("hello", fields={"national_id": ""})]) == []
    assert g.check([r], [g.Document("form_answers", "date of birth 1990")]) == []  # out of scope


def test_format_money_usd_first():
    r = rule(FormatRule(rule="money_usd_first", params={"local_currency": "ZMW"}))
    assert len(g.check([r], [cv("Saved ZMW 500,000 for the client.")])) == 1
    assert len(g.check([r], [cv("Saved ZMW 500,000 (USD 25,000).")])) == 1  # local first
    assert g.check([r], [cv("Saved USD 25,000 (ZMW 500,000).")]) == []
    assert g.check([r], [cv("No money here.")]) == []


def test_unknown_format_rule_is_left_to_the_model():
    assert g.check([rule(FormatRule(rule="something_new"))], [cv("anything")]) == []


def test_limit_paragraphs_and_pages():
    r = rule(LimitRule(document="letter", pages=1, paragraphs=2), scope=("letter",))
    long = g.Document("letter", "one\n\ntwo\n\nthree", pages=2)
    assert len(g.check([r], [long])) == 2
    assert g.check([r], [g.Document("letter", "one\n\ntwo", pages=1)]) == []
    assert g.check([r], [cv("one\n\ntwo\n\nthree")]) == []  # other document kind


def test_attach_policy():
    never = rule(AttachPolicy(document_type="id", when="never"), id="a")
    after = rule(AttachPolicy(document_type="id", when="after_offer"), id="b")
    asked = rule(AttachPolicy(document_type="degree", when="when_asked"), id="c")
    att = [g.Attachment("id", "id.pdf"), g.Attachment("degree", "degree.pdf")]
    rules = [never, after, asked]
    assert {v.guardrail_id for v in g.check(rules, [], attachments=att)} == {"a", "b", "c"}
    assert {v.guardrail_id for v in g.check(rules, [], attachments=att, released={"asked"})} == {"a", "b"}
    assert {v.guardrail_id for v in g.check(rules, [], attachments=att, released={"after_offer"})} == {"a"}


def test_model_enforced_types_never_violate():
    assert g.check([rule(Positioning(instruction="lead with outcomes"))], [cv("anything")]) == []


def test_disabled_rule_is_skipped():
    r = g.Rule(id="x", name="x", params=NeverMention(terms=["a"]), enabled=False)
    assert g.check([r], [cv("a")]) == []


def test_strictness_levels_and_waiver():
    params = NeverMention(terms=["bad"])
    always = rule(params, id="always")
    waivable = rule(params, strictness="block_waivable_once", id="waiv")
    advise = rule(params, strictness="advise", id="adv")
    warn = rule(params, severity="warn", id="warn")
    hits = {v.guardrail_id: v for v in g.check([always, waivable, advise, warn], [cv("bad")])}
    assert hits["always"].status == "block" and not hits["always"].waivable
    assert hits["waiv"].status == "block" and hits["waiv"].waivable
    assert hits["adv"].status == "warn" and hits["warn"].status == "warn"
    assert g.blocked(hits.values())
    assert not g.blocked([hits["waiv"], hits["adv"]], waived=["waiv"])
    assert g.blocked([hits["always"]], waived=["always"])  # always_block cannot be waived
    assert not g.blocked([hits["adv"], hits["warn"]])


def test_never_skills_become_rules():
    assert len(g.check(g.never_skill_rules(["Tableau"]), [cv("Expert in Tableau")])) == 1


def test_invalid_regex_is_reported_not_raised():
    hits = g.check([rule(NeverMention(regex=["("]))], [cv("x")])
    assert len(hits) == 1 and "invalid" in hits[0].detail
