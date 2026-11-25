from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.conditions import (
    NOT_STATED,
    CampaignRule,
    ConditionSet,
    Group,
    RangeFilter,
    TextFilter,
    ValueFilter,
    evaluate,
    explain,
    filter_records,
    group_by,
)

pytestmark = pytest.mark.nodb


def cs(*conds, op="and", negate=False) -> ConditionSet:
    return ConditionSet(root=Group(op=op, negate=negate, conditions=list(conds)))


JOBS = [
    {"id": 1, "title": "Senior Data Analyst", "employer": "Acme", "raw_text": "Python and SQL",
     "facets": {"visa_sponsorship": {"value": "yes", "evidence": "We sponsor visas."},
                "required_skills": ["python", "sql"], "years_experience": {"value": 5}}},
    {"id": 2, "title": "Data Scientist", "employer": "Beta", "raw_text": "R and Python",
     "facets": {"visa_sponsorship": {"value": "no", "evidence": "No sponsorship."},
                "required_skills": ["r", "python"], "years_experience": {"value": None}}},
    {"id": 3, "title": "BI Lead", "employer": "Gamma", "raw_text": "Power BI",
     "facets": {"visa_sponsorship": {"value": "not_stated"}, "required_skills": []}},
    {"id": 4, "title": "Analyst", "employer": "Delta", "raw_text": "", "facets": {}},
]


def ids(conditions: ConditionSet) -> list[int]:
    return [j["id"] for j in filter_records(conditions, JOBS)]


def test_include_exclude_and_not_stated_are_distinct():
    include_yes = cs(ValueFilter(facet="facets.visa_sponsorship", include=["yes"]))
    exclude_no = cs(ValueFilter(facet="facets.visa_sponsorship", exclude=["no"]))
    only_not_stated = cs(ValueFilter(facet="facets.visa_sponsorship", include=[NOT_STATED]))
    exclude_not_stated = cs(ValueFilter(facet="facets.visa_sponsorship", exclude=[NOT_STATED]))
    assert ids(include_yes) == [1]
    assert ids(exclude_no) == [1, 3, 4]  # not stated passes an exclusion of "no"
    assert ids(only_not_stated) == [3, 4]  # missing key and explicit not_stated are the same value
    assert ids(exclude_not_stated) == [1, 2]


def test_any_versus_all_within_a_facet():
    any_ = cs(ValueFilter(facet="facets.required_skills", include=["sql", "r"], match="any"))
    all_ = cs(ValueFilter(facet="facets.required_skills", include=["python", "sql"], match="all"))
    assert ids(any_) == [1, 2]
    assert ids(all_) == [1]


def test_values_are_case_insensitive():
    assert ids(cs(ValueFilter(facet="facets.required_skills", include=["PYTHON"]))) == [1, 2]


def test_facets_combine_with_and():
    both = cs(ValueFilter(facet="facets.required_skills", include=["python"]),
              ValueFilter(facet="facets.visa_sponsorship", exclude=["no"]))
    assert ids(both) == [1]


def test_range_and_not_stated_policy():
    at_most_5 = cs(RangeFilter(facet="facets.years_experience", max=5))
    lenient = cs(RangeFilter(facet="facets.years_experience", max=5, not_stated="include"))
    assert ids(at_most_5) == [1]
    assert ids(lenient) == [1, 2, 3, 4]


def test_text_and_or_and_negate():
    assert ids(cs(TextFilter(query="python sql"))) == [1]
    either = cs(TextFilter(query="power bi"), TextFilter(query="data scientist"), op="or")
    assert ids(either) == [2, 3]
    assert ids(cs(TextFilter(query="python"), negate=True)) == [3, 4]


def test_empty_set_matches_everything():
    assert ids(ConditionSet()) == [1, 2, 3, 4]


def test_explain_gives_reasons():
    tree = explain(cs(ValueFilter(facet="facets.visa_sponsorship", include=["yes"])), JOBS[1])
    assert tree.matched is False
    child = tree.children[0]
    assert child.facet == "facets.visa_sponsorship" and child.actual == ["no"] and "needs any" in child.detail


def test_group_by_counts():
    groups = group_by(JOBS, "facets.visa_sponsorship")
    assert {k: [j["id"] for j in v] for k, v in groups.items()} == {"yes": [1], "no": [2], NOT_STATED: [3, 4]}
    skills = group_by(JOBS, "facets.required_skills")
    assert [j["id"] for j in skills["python"]] == [1, 2]


def test_view_copied_to_campaign_rule_matches_same_jobs():
    view = cs(ValueFilter(facet="facets.visa_sponsorship", include=["yes", NOT_STATED]))
    rule = CampaignRule(effect="include", conditions=ConditionSet.model_validate_json(view.model_dump_json()))
    assert [j["id"] for j in JOBS if evaluate(rule.conditions, j)] == ids(view)


def test_schema_validation():
    with pytest.raises(ValidationError):
        ValueFilter(facet="x")  # neither include nor exclude
    with pytest.raises(ValidationError):
        ValueFilter(facet="x", include=["a"], exclude=["A"])
    with pytest.raises(ValidationError):
        RangeFilter(facet="x", min=5, max=1)
    with pytest.raises(ValidationError):
        CampaignRule(effect="penalty", conditions=ConditionSet())
    with pytest.raises(ValidationError):
        CampaignRule(effect="exclude", conditions=ConditionSet(), points=3)
    with pytest.raises(ValidationError):
        ConditionSet.model_validate({"root": {"type": "group", "conditions": [{"type": "bogus"}]}})
    nested = ConditionSet.model_validate({"root": {"type": "group", "op": "or", "conditions": [
        {"type": "group", "conditions": [{"type": "values", "facet": "a", "include": [1]}]},
        {"type": "text", "query": "x"}]}})
    assert evaluate(nested, {"a": 1}) is True
