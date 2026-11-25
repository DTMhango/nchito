"""One condition engine for saved views, rule tags, campaign criteria and answer conditions.

DESIGN.md 6.1: views and campaign rules share this schema, so anything filterable is usable as
a rule and the reverse. A view only changes what is shown; a ``CampaignRule`` wraps the same
``ConditionSet`` with an effect (exclude, include, penalty, bonus).

Record shape: a plain dict. Facet values may be scalars, lists, or ``{"value": ..., "evidence": ...}``
wrappers (the evidence quote is ignored here). Paths are dotted (``facets.relocation_required``).
A missing key, ``None``, an empty list or the literal ``"not_stated"`` all mean **not stated**,
which is a value like any other: it can be included or excluded explicitly. A value filter
with an include list does not match a not-stated record unless ``"not_stated"`` is included.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NOT_STATED = "not_stated"

Scalar = str | int | float | bool


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValueFilter(_Base):
    """A facet chip set: include values, exclude values, ``any``/``all`` within the facet."""

    type: Literal["values"] = "values"
    facet: str = Field(min_length=1)
    include: list[Scalar] = Field(default_factory=list)
    exclude: list[Scalar] = Field(default_factory=list)
    match: Literal["any", "all"] = "any"

    @model_validator(mode="after")
    def _not_empty(self) -> ValueFilter:
        if not self.include and not self.exclude:
            raise ValueError("a value filter needs at least one include or exclude value")
        if set(map(_norm, self.include)) & set(map(_norm, self.exclude)):
            raise ValueError("a value cannot be both included and excluded")
        return self


class RangeFilter(_Base):
    """Numeric range on a facet (years asked, pay, posted age). ``not_stated`` says what a
    missing value does: ``exclude`` (default) fails the record, ``include`` passes it."""

    type: Literal["range"] = "range"
    facet: str = Field(min_length=1)
    min: float | None = None
    max: float | None = None
    not_stated: Literal["include", "exclude"] = "exclude"

    @model_validator(mode="after")
    def _bounds(self) -> RangeFilter:
        if self.min is None and self.max is None:
            raise ValueError("a range filter needs min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


class TextFilter(_Base):
    """Case-insensitive substring search over the named fields (all words must appear)."""

    type: Literal["text"] = "text"
    query: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=lambda: ["title", "employer", "raw_text"])


class Group(_Base):
    type: Literal["group"] = "group"
    op: Literal["and", "or"] = "and"
    negate: bool = False
    conditions: list[Condition] = Field(default_factory=list)


Condition = Annotated[ValueFilter | RangeFilter | TextFilter | Group, Field(discriminator="type")]
Group.model_rebuild()


class ConditionSet(_Base):
    """Root of a filter: facets combine with AND (the default), free text alongside."""

    version: Literal[1] = 1
    root: Group = Field(default_factory=Group)


class CampaignRule(_Base):
    """A condition set made binding on a campaign ("Use as campaign rule")."""

    effect: Literal["exclude", "include", "penalty", "bonus"]
    conditions: ConditionSet
    points: int | None = Field(default=None, ge=1, le=100)
    reason: str | None = None

    @model_validator(mode="after")
    def _points(self) -> CampaignRule:
        if self.effect in ("penalty", "bonus") and self.points is None:
            raise ValueError("penalty and bonus rules need points")
        if self.effect in ("exclude", "include") and self.points is not None:
            raise ValueError("only penalty and bonus rules carry points")
        return self


class ConditionResult(BaseModel):
    """Explanation tree for the "Why?" panel."""

    matched: bool
    kind: str
    facet: str | None = None
    actual: Any = None
    detail: str | None = None
    children: list[ConditionResult] = Field(default_factory=list)


# ----- evaluation -------------------------------------------------------------------------


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def lookup(record: Mapping[str, Any], path: str) -> Any:
    cur: Any = record
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    if isinstance(cur, Mapping) and "value" in cur:
        cur = cur["value"]
    return cur


def _values(raw: Any) -> list[Any]:
    """Normalised list of values; ``[NOT_STATED]`` when nothing is stated."""
    if raw is None or raw == NOT_STATED:
        return [NOT_STATED]
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        items = [_norm(v["value"] if isinstance(v, Mapping) and "value" in v else v) for v in raw]
        items = [v for v in items if v is not None and v != NOT_STATED]
        return items or [NOT_STATED]
    return [_norm(raw)]


def _eval_values(cond: ValueFilter, record: Mapping[str, Any]) -> ConditionResult:
    actual = _values(lookup(record, cond.facet))
    have = set(actual)
    excluded = have & {_norm(v) for v in cond.exclude}
    if excluded:
        return ConditionResult(matched=False, kind="values", facet=cond.facet, actual=actual,
                               detail=f"excluded value: {sorted(map(str, excluded))}")
    if cond.include:
        wanted = {_norm(v) for v in cond.include}
        ok = wanted <= have if cond.match == "all" else bool(wanted & have)
        detail = None if ok else f"needs {cond.match} of {sorted(map(str, wanted))}"
        return ConditionResult(matched=ok, kind="values", facet=cond.facet, actual=actual, detail=detail)
    return ConditionResult(matched=True, kind="values", facet=cond.facet, actual=actual)


def _eval_range(cond: RangeFilter, record: Mapping[str, Any]) -> ConditionResult:
    raw = lookup(record, cond.facet)
    if raw is None or raw == NOT_STATED or isinstance(raw, bool):
        ok = cond.not_stated == "include"
        return ConditionResult(matched=ok, kind="range", facet=cond.facet, actual=NOT_STATED,
                               detail=None if ok else "not stated")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return ConditionResult(matched=False, kind="range", facet=cond.facet, actual=raw, detail="not a number")
    ok = (cond.min is None or number >= cond.min) and (cond.max is None or number <= cond.max)
    return ConditionResult(matched=ok, kind="range", facet=cond.facet, actual=number,
                           detail=None if ok else f"outside [{cond.min}, {cond.max}]")


def _eval_text(cond: TextFilter, record: Mapping[str, Any]) -> ConditionResult:
    haystack = " ".join(str(lookup(record, f) or "") for f in cond.fields).casefold()
    words = cond.query.casefold().split()
    ok = all(w in haystack for w in words)
    return ConditionResult(matched=ok, kind="text", detail=None if ok else f"text not found: {cond.query!r}")


def _eval_group(cond: Group, record: Mapping[str, Any]) -> ConditionResult:
    children = [explain_condition(c, record) for c in cond.conditions]
    if not children:
        matched = True
    elif cond.op == "and":
        matched = all(c.matched for c in children)
    else:
        matched = any(c.matched for c in children)
    if cond.negate:
        matched = not matched
    return ConditionResult(matched=matched, kind=f"group:{cond.op}{':not' if cond.negate else ''}",
                           children=children)


def explain_condition(cond: ValueFilter | RangeFilter | TextFilter | Group,
                      record: Mapping[str, Any]) -> ConditionResult:
    if isinstance(cond, ValueFilter):
        return _eval_values(cond, record)
    if isinstance(cond, RangeFilter):
        return _eval_range(cond, record)
    if isinstance(cond, TextFilter):
        return _eval_text(cond, record)
    return _eval_group(cond, record)


def explain(conditions: ConditionSet, record: Mapping[str, Any]) -> ConditionResult:
    return explain_condition(conditions.root, record)


def evaluate(conditions: ConditionSet, record: Mapping[str, Any]) -> bool:
    return explain(conditions, record).matched


def filter_records(conditions: ConditionSet, records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [r for r in records if evaluate(conditions, r)]


def group_by(records: Sequence[Mapping[str, Any]], facet: str) -> dict[str, list[Mapping[str, Any]]]:
    """Group records by a facet's values (a multi-valued facet puts a record in several groups)."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        for value in _values(lookup(record, facet)):
            groups.setdefault(str(value), []).append(record)
    return groups
