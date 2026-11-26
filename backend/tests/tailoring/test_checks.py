"""Pure tests of the code checks: every guardrail type, fact tracing, claim drift, keep-out, staleness."""

from __future__ import annotations

from typing import Any

import pytest

from app.kit.guardrails import Attachment, Document, Rule
from app.pipeline.checks.drift import DriftTerms, staleness
from app.pipeline.checks.findings import summarise, worst
from app.pipeline.checks.kit import ExperienceView, FactView, KitView, SkillView, TrackView
from app.pipeline.checks.service import CheckSettings, deterministic
from app.schemas.json_types import (
    ApplicationSpec,
    AttachPolicy,
    DraftAnswer,
    FormatRule,
    LimitRule,
    NeverMention,
    NeverTogether,
    OmitField,
    Positioning,
    Reframe,
    RequireWording,
)

pytestmark = pytest.mark.nodb

GLOBEX, INITECH = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def fact(code: str, text: str, exp: str | None = None, *, approved: bool = True, confirmed: bool = True,
         keep_out: bool = False) -> FactView:
    return FactView(code=code, text=text, kind="achievement", experience_id=exp, approved=approved,
                    confirmed=confirmed, keep_out=keep_out, hash=f"h-{code}-{len(text)}")


FACTS = [
    fact("F-1", "Cut monthly reporting time by 40% by automating the sales pack.", GLOBEX),
    fact("F-2", "Contributed to a pricing review that saved USD 120,000 per year.", INITECH),
    fact("F-3", "In 2023 grew active customers by 15%.", INITECH),
    fact("F-4", "In 2021 grew active customers by 10%.", GLOBEX),
    fact("F-5", "BSc in Statistics, University of Example."),
    fact("F-6", "Confidential: 3 of 47 analysts were let go in 2021.", keep_out=True),
    fact("F-7", "Draft idea: led a team of 9.", approved=False),
    fact("F-8", "Led the migration of 12 dashboards to the new warehouse.", GLOBEX, confirmed=False),
]
EXPERIENCES = {
    GLOBEX: ExperienceView(id=GLOBEX, org="Globex Example Ltd", titles=("Data Analyst",),
                           dates=("2019-03", "2022-06"), title_variants={"analytics": ("Analytics Specialist",)},
                           forbidden_titles=("Head of Data",)),
    INITECH: ExperienceView(id=INITECH, org="Initech Example", titles=("Senior Analyst",), dates=("2022-07",)),
}
SKILLS = {"sql": SkillView("SQL", "yes", True), "python": SkillView("Python", "yes", True),
          "tableau": SkillView("Tableau", "no", True)}
CFG = CheckSettings(
    qualification_terms=("bsc", "msc", "mba", "phd", "certified"),
    drift_terms=DriftTerms(weak=("contributed to", "supported"), strong=("led", "owned", "headed"),
                           scope=("global", "company-wide"), period=("per month", "monthly", "per year", "annually")),
    letter_paragraphs=4, bullets_per_role=3)
JOB_TERMS = ["Acme Example Corp", "Data Analyst"]


def kit(*rules: Rule) -> KitView:
    return KitView(facts={f.code: f for f in FACTS}, experiences=EXPERIENCES, skills=SKILLS, rules=tuple(rules),
                   track=TrackView(key="analytics", name="Analytics"))


def spec(**over: Any) -> ApplicationSpec:
    base: dict[str, Any] = {
        "summary": {"text": "Cut monthly reporting time by 40% at Globex Example Ltd.", "fact_ids": ["F-1"]},
        "experience": [
            {"experience_id": GLOBEX, "title": "Data Analyst",
             "bullets": [{"text": "Cut monthly reporting time by 40% by automating the sales pack.",
                          "fact_ids": ["F-1"]}]},
            {"experience_id": INITECH, "title": "Senior Analyst",
             "bullets": [{"text": "Contributed to a pricing review that saved USD 120,000 per year.",
                          "fact_ids": ["F-2"]}]}],
        "skills": ["SQL"],
        "letter": [{"text": "I am applying for the Data Analyst role at Acme Example Corp.", "fact_ids": []}],
    }
    base.update(over)
    return ApplicationSpec.model_validate(base)


def bullet(text: str, *codes: str, exp: str = GLOBEX, title: str | None = None) -> list[dict[str, Any]]:
    return [{"experience_id": exp, "title": title, "bullets": [{"text": text, "fact_ids": list(codes)}]}]


def run(s: ApplicationSpec, k: KitView | None = None, **kw: Any):
    outcome = deterministic(s, k or kit(), CFG, job_terms=JOB_TERMS, **kw)
    return outcome.findings, summarise(outcome.findings, outcome.checks_run)


def checks(findings) -> list[tuple[str, str]]:
    return [(f.check, f.status) for f in findings]


def test_a_traceable_spec_passes_every_check():
    findings, results = run(spec())
    assert findings == []
    assert worst(results) == "pass"
    assert {r.check for r in results} >= {"fact_trace", "claim_drift", "keep_out", "guardrails", "limits"}


# ----- fact tracing ------------------------------------------------------------------------------


def test_fact_tracing_catches_an_invented_number():
    findings, results = run(spec(summary={"text": "Cut monthly reporting time by 45%.", "fact_ids": ["F-1"]}))
    assert ("fact_trace", "block") in checks(findings)
    assert any("45%" in f.detail for f in findings)
    assert worst(results) == "block"


def test_a_figure_with_no_fact_cited_is_blocked():
    findings, _ = run(spec(competencies=[{"text": "Saved 2 million for clients", "fact_ids": []}]))
    assert any(f.check == "fact_trace" and "cites no fact" in f.detail for f in findings)


def test_invented_employer_date_and_qualification_are_blocked():
    findings, _ = run(spec(summary={"text": "Holds an MBA; cut reporting time by 40% at Hooli Example in 2018.",
                                    "fact_ids": ["F-1"]}))
    details = " | ".join(f.detail for f in findings if f.check == "fact_trace")
    assert "Hooli Example" in details and "2018" in details and "mba" in details


def test_a_known_employer_not_behind_the_cited_fact_is_blocked():
    findings, _ = run(spec(summary={"text": "Cut reporting time by 40% at Initech Example.", "fact_ids": ["F-1"]}))
    assert any("no cited fact is from there" in f.detail for f in findings)


def test_a_qualification_backed_by_a_cited_fact_passes():
    findings, _ = run(spec(competencies=[{"text": "BSc in Statistics", "fact_ids": ["F-5"]}]))
    assert findings == []


def test_titles_must_be_held_or_allowed_for_the_track_and_never_forbidden():
    ok, _ = run(spec(experience=bullet("Cut monthly reporting time by 40% by automating the sales pack.", "F-1",
                                       title="Analytics Specialist")))
    assert ok == []
    bad, _ = run(spec(experience=bullet("Cut monthly reporting time by 40%.", "F-1", title="Head of Data")))
    assert any("never held" in f.detail for f in bad)
    made_up, _ = run(spec(experience=bullet("Cut monthly reporting time by 40%.", "F-1", title="Chief Analyst")))
    assert any("not a title you held" in f.detail for f in made_up)
    free_text, _ = run(spec(headline={"text": "Head of Data", "fact_ids": ["F-1"]}))
    assert any("never held" in f.detail for f in free_text)


def test_citations_must_be_approved_confirmed_kit_facts():
    findings, _ = run(spec(competencies=[{"text": "Led a team of 9", "fact_ids": ["F-7"]},
                                         {"text": "Moved 12 dashboards", "fact_ids": ["F-8"]},
                                         {"text": "Grew sales", "fact_ids": ["F-99"]}]))
    details = [f.detail for f in findings if f.check == "fact_trace"]
    assert any("F-7, which is not approved" in d for d in details)
    assert any("F-8, which still needs your review" in d for d in details)
    assert any("F-99, which is not in your Kit" in d for d in details)


def test_skills_must_be_claimed_in_the_kit():
    findings, _ = run(spec(skills=["SQL", "Tableau", "Rust"]))
    details = [f.detail for f in findings if f.check == "skills"]
    assert len(details) == 2 and any("Tableau" in d for d in details) and any("Rust" in d for d in details)


# ----- claim drift (18.5) ------------------------------------------------------------------------


def test_claim_drift_ownership_contributed_to_becomes_led():
    findings, _ = run(spec(experience=bullet("Led a pricing review that saved USD 120,000 per year.", "F-2",
                                             exp=INITECH)))
    drift = [f for f in findings if f.check == "claim_drift"]
    assert drift and drift[0].status == "block" and "contributed to" in drift[0].detail
    assert not [f for f in findings if f.check == "fact_trace"]  # every number is real


def test_claim_drift_scope_and_period():
    scope, _ = run(spec(experience=bullet("Cut global monthly reporting time by 40%.", "F-1")))
    assert any(f.check == "claim_drift" and "global" in f.detail for f in scope)
    period, _ = run(spec(experience=bullet("Contributed to a pricing review that saved USD 120,000 per month.",
                                           "F-2", exp=INITECH)))
    assert any(f.check == "claim_drift" and "per month" in f.detail for f in period)
    same_period, _ = run(spec(experience=bullet("Contributed to a pricing review saving USD 120,000 annually.",
                                                "F-2", exp=INITECH)))
    assert not [f for f in same_period if f.check == "claim_drift"]


def test_claim_drift_units():
    findings, _ = run(spec(experience=bullet("Cut monthly reporting cost by USD 40.", "F-1")))
    assert any(f.check == "claim_drift" and "unit" in f.detail for f in findings)


def test_claim_drift_figures_combined_across_periods():
    findings, _ = run(spec(competencies=[{"text": "Grew active customers by 10% and 15%.",
                                          "fact_ids": ["F-3", "F-4"]}]))
    assert ("claim_drift", "warn") in checks(findings)
    summed, _ = run(spec(competencies=[{"text": "Grew active customers by 25% over 2021 and 2023.",
                                        "fact_ids": ["F-3", "F-4"]}]))
    assert any(f.check == "fact_trace" and "25%" in f.detail for f in summed)


def test_claim_drift_achievement_moved_to_another_employer():
    findings, _ = run(spec(experience=bullet("Grew active customers by 15%.", "F-3", exp=GLOBEX)))
    assert any(f.check == "claim_drift" and "Initech Example" in f.detail for f in findings)


def test_staleness_spec_or_facts_changed_after_the_check():
    assert staleness(content_hash="a", checked_hash="a", checked_facts={"F-1": "x"}, current_facts={"F-1": "x"}) == []
    assert staleness(content_hash="b", checked_hash="a", checked_facts={}, current_facts={}) == [
        "the spec changed after it was checked"]
    assert staleness(content_hash="a", checked_hash="a", checked_facts={"F-1": "x"},
                     current_facts={"F-1": "y"}) == ["F-1 changed after the check"]
    assert staleness(content_hash="a", checked_hash="a", checked_facts={"F-1": "x"},
                     current_facts={"F-1": "missing"}) == ["F-1 is no longer an approved Kit fact"]
    assert staleness(content_hash="a", checked_hash=None, checked_facts={}, current_facts={}) == ["not checked yet"]


# ----- keep-out facts ----------------------------------------------------------------------------


def test_keep_out_facts_never_appear():
    cited, _ = run(spec(competencies=[{"text": "Restructured a team", "fact_ids": ["F-6"]}]))
    assert ("keep_out", "block") in checks(cited)
    figure, _ = run(spec(letter=[{"text": "I worked with 47 analysts.", "fact_ids": []}]))
    assert any(f.check == "keep_out" and "F-6" in f.detail for f in figure)


# ----- guardrails: every type --------------------------------------------------------------------


def rule(params: Any, **kw: Any) -> Rule:
    return Rule(id=kw.pop("id", "g-1"), name=kw.pop("name", "rule"), params=params, **kw)


def guard_findings(s: ApplicationSpec, *rules: Rule, **kw: Any):
    findings, results = run(s, kit(*rules), **kw)
    return [f for f in findings if f.check.startswith("guardrails")], results


def test_never_mention():
    found, _ = guard_findings(spec(), rule(NeverMention(terms=["sales pack"])))
    assert found and found[0].check == "guardrails.never_mention" and found[0].status == "block"


def test_never_together_across_cv_and_letter():
    s = spec(letter=[{"text": "I am applying for the Data Analyst role at Acme Example Corp.", "fact_ids": []},
                     {"text": "At Globex Example Ltd I cut monthly reporting time by 40%.", "fact_ids": ["F-1"]}])
    found, _ = guard_findings(s, rule(NeverTogether(group_a=["F-2"], group_b=["Globex Example Ltd"]),
                                      scope=("letter",)))
    assert found == []  # the letter alone has only one side
    found, _ = guard_findings(s, rule(NeverTogether(group_a=["F-2"], group_b=["Globex Example Ltd"])))
    assert found and found[0].check == "guardrails.never_together"


def test_require_wording():
    found, _ = guard_findings(spec(), rule(RequireWording(use="sales report pack", instead_of=["sales pack"])))
    assert found and "use 'sales report pack'" in found[0].detail


def test_reframe_warns():
    found, results = guard_findings(spec(), rule(Reframe(prefer="streamlined", over="cut")))
    assert found and found[0].status == "warn" and found[0].check == "guardrails.reframe"
    assert worst(results) == "warn"


def test_omit_field():
    found, _ = guard_findings(spec(letter=[{"text": "Date of birth: 1990.", "fact_ids": []}]),
                              rule(OmitField(fields=["date_of_birth"])))
    assert any(f.check == "guardrails.omit_field" for f in found)


def test_format_money_usd_first():
    s = spec(experience=bullet("Contributed to a pricing review that saved ZMW 3,000,000 (USD 120,000) per year.",
                               "F-2", exp=INITECH))
    found, _ = guard_findings(s, rule(FormatRule(rule="money_usd_first", params={"local_currency": "ZMW"})))
    assert any(f.check == "guardrails.format" for f in found)


def test_limit_paragraphs_from_a_guardrail_and_from_settings():
    letter = [{"text": f"Paragraph {i}.", "fact_ids": []} for i in range(5)]
    found, _ = guard_findings(spec(letter=letter), rule(LimitRule(document="letter", paragraphs=3)))
    assert any(f.check == "guardrails.limit" for f in found)
    findings, _ = run(spec(letter=letter))
    assert any(f.check == "limits" and "limit 4" in f.detail for f in findings)


def test_attach_policy_in_the_packet_check():
    r = rule(AttachPolicy(document_type="id", when="after_offer"))
    found, _ = guard_findings(spec(), r, attachments=[Attachment("id", "passport.pdf")])
    assert any(f.check == "guardrails.attach_policy" and f.status == "block" for f in found)
    ok, _ = guard_findings(spec(), r, attachments=[Attachment("id", "passport.pdf")], released=["after_offer"])
    assert ok == []


def test_positioning_is_for_the_model_only():
    found, _ = guard_findings(spec(), rule(Positioning(instruction="Lead with scope.")))
    assert found == []


def test_whole_packet_extra_documents_and_file_names():
    r = rule(NeverMention(terms=["salary history"]))
    found, _ = guard_findings(spec(), r, extra_documents=[Document(scope="email", text="My salary history is...")])
    assert found and found[0].path == "email"
    named, _ = guard_findings(spec(), rule(NeverMention(terms=["confidential"])), file_names=["confidential cv.pdf"])
    assert named


def test_strictness_waivable_once_always_block_and_advise():
    waivable = rule(NeverMention(terms=["sales pack"]), id="g-w", strictness="block_waivable_once")
    found, results = guard_findings(spec(), waivable, waived=["g-w"])
    assert found[0].waived and worst(results) == "warn"
    found, results = guard_findings(spec(), waivable)
    assert not found[0].waived and worst(results) == "block"
    always = rule(NeverMention(terms=["sales pack"]), id="g-a", strictness="always_block")
    found, results = guard_findings(spec(), always, waived=["g-a"])
    assert not found[0].waived and worst(results) == "block"
    advise = rule(NeverMention(terms=["sales pack"]), id="g-adv", strictness="advise")
    found, results = guard_findings(spec(), advise)
    assert found[0].status == "warn" and worst(results) == "warn"


def test_never_claim_skill_rule_blocks():
    from app.kit.guardrails import never_skill_rules

    found, _ = guard_findings(spec(skills=["SQL", "COBOL"]), *never_skill_rules(["COBOL"]))
    assert found and found[0].guardrail_id is None and "COBOL" in found[0].detail


def test_unanswered_questions_are_reported_never_answered():
    answers = [DraftAnswer(question="Expected salary?", outcome="ask_owner", reason="material answer")]
    findings, _ = run(spec(), answers=answers)
    assert ("answers", "warn") in checks(findings)
