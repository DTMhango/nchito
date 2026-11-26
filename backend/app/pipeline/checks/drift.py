"""Claim drift (DESIGN.md 18.5): every number can be real and the claim still false. Pure.

Wording checks, each against the facts an item cites (term lists are settings):

- **ownership**: leading wording ("led") when no cited fact uses leading wording, more so when one
  uses supporting wording ("contributed to");
- **scope**: widening wording ("company-wide") no cited fact uses;
- **period**: a period ("per month") no cited fact states;
- **combined periods**: figures from facts about different years in one sentence (a warning).

Units are compared by fact tracing. :func:`staleness` is the other kind of drift: a stored check no
longer applies because the spec or the facts it rests on changed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.pipeline.checks.findings import Finding
from app.pipeline.checks.items import Item
from app.pipeline.checks.kit import FactView
from app.pipeline.checks.tracing import DRIFT, figures_in

_PERIOD_CLASSES = (("year", ("year", "annum", "annual")), ("quarter", ("quarter",)), ("month", ("month",)),
                   ("week", ("week",)), ("day", ("day", "daily")))


@dataclass(frozen=True)
class DriftTerms:
    weak: tuple[str, ...]
    strong: tuple[str, ...]
    scope: tuple[str, ...]
    period: tuple[str, ...]


def _hits(text: str, terms: Sequence[str]) -> list[str]:
    low = text.casefold()
    return [t for t in terms if re.search(rf"(?<!\w){re.escape(t.casefold())}(?!\w)", low)]


def _period_class(term: str) -> str:
    low = term.casefold()
    for name, keys in _PERIOD_CLASSES:
        if any(k in low for k in keys):
            return name
    return low


def ownership(item: Item, facts: Sequence[FactView], terms: DriftTerms) -> list[Finding]:
    claimed = _hits(item.text, terms.strong)
    if not claimed or not facts:
        return []
    source = "\n".join(f.text for f in facts)
    if _hits(source, terms.strong):
        return []
    weak = _hits(source, terms.weak)
    said = f"the fact says '{weak[0]}'" if weak else "no cited fact claims that role"
    return [Finding(DRIFT, "block", f"'{claimed[0]}' overstates ownership: {said}", item.path)]


def scope(item: Item, facts: Sequence[FactView], terms: DriftTerms) -> list[Finding]:
    if not facts:
        return []
    source = "\n".join(f.text for f in facts)
    return [Finding(DRIFT, "block", f"'{t}' widens the scope beyond the cited facts", item.path)
            for t in _hits(item.text, terms.scope) if not _hits(source, [t])]


def period(item: Item, facts: Sequence[FactView], terms: DriftTerms) -> list[Finding]:
    if not facts:
        return []
    have = {_period_class(t) for t in _hits("\n".join(f.text for f in facts), terms.period)}
    return [Finding(DRIFT, "block", f"'{t}' states a period no cited fact states", item.path)
            for t in _hits(item.text, terms.period) if _period_class(t) not in have]


def combined_periods(item: Item, facts: Sequence[FactView]) -> list[Finding]:
    """Figures in one sentence drawn from facts about different years."""
    years_by_fact: dict[str, frozenset[float]] = {}
    for f in facts:
        years_by_fact[f.code] = frozenset(x.value for x in figures_in(f.text) if x.kind == "year")
    used: set[frozenset[float]] = set()
    for fig in figures_in(item.text):
        if fig.kind == "year":
            continue
        for f in facts:
            if any(x.same_value(fig) and x.kind == fig.kind for x in figures_in(f.text)) and years_by_fact[f.code]:
                used.add(years_by_fact[f.code])
    if len(used) > 1:
        return [Finding(DRIFT, "warn", "combines figures from facts about different periods", item.path)]
    return []


def drift(items: Sequence[Item], cited: Mapping[str, Sequence[FactView]], terms: DriftTerms) -> list[Finding]:
    out: list[Finding] = []
    for item in items:
        facts = cited.get(item.path, ())
        out += ownership(item, facts, terms)
        out += scope(item, facts, terms)
        out += period(item, facts, terms)
        out += combined_periods(item, facts)
    return out


def staleness(*, content_hash: str, checked_hash: str | None, checked_facts: Mapping[str, str],
              current_facts: Mapping[str, str]) -> list[str]:
    """Why a stored check no longer applies (empty when it still does)."""
    if checked_hash is None:
        return ["not checked yet"]
    reasons: list[str] = []
    if checked_hash != content_hash:
        reasons.append("the spec changed after it was checked")
    for code, digest in sorted(checked_facts.items()):
        now = current_facts.get(code, "missing")
        if now == "missing":
            reasons.append(f"{code} is no longer an approved Kit fact")
        elif now != digest:
            reasons.append(f"{code} changed after the check")
    return reasons
