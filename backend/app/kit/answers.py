"""The answer matcher (DESIGN.md 5.4): normalised similarity of a question to stored answers,
honouring scope, conditions, review dates and class. Pure: no database, no clock (``today`` is
passed in), no model.

Outcomes: ``value`` (reuse this answer), ``ask_owner`` (raise a pending action) or
``do_not_answer`` (the answer class is ``never``; pick ``select`` where a choice is forced).
Unknown is not yes: an unconfirmed answer, a missing condition fact, a due review date, an
ambiguous tie, or no match at all all mean ``ask_owner``.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from app.core.conditions import ConditionSet, Group, evaluate, lookup

Outcome = Literal["value", "ask_owner", "do_not_answer"]

SCOPE_RANK = {"this_application": 3, "this_employer": 2, "this_country": 1, "all_matching": 0}
TIE_MARGIN = 0.02


@dataclass(frozen=True)
class AnswerRecord:
    id: uuid.UUID
    patterns: tuple[str, ...]  # canonical first, then variants
    value: str | None
    answer_class: Literal["auto", "ask_first", "never", "owner_only"]
    conditions: ConditionSet
    scope: Literal["this_application", "this_employer", "this_country", "all_matching"] = "all_matching"
    scope_ref: str | None = None
    settled: bool = False
    confirmed: bool = True
    forced_choice: str | None = None
    review_after: date | None = None


@dataclass(frozen=True)
class MatchResult:
    outcome: Outcome
    answer_id: uuid.UUID | None = None
    value: str | None = None
    select: str | None = None
    similarity: float | None = None
    reason: str = ""


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    """Best of character-sequence ratio and word-order-insensitive ratio, on normalised text."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = " ".join(sorted(na.split())), " ".join(sorted(nb.split()))
    return max(seq, SequenceMatcher(None, ta, tb).ratio())


def _facets(group: Group) -> set[str]:
    out: set[str] = set()
    for c in group.conditions:
        out |= _facets(c) if isinstance(c, Group) else {c.facet} if hasattr(c, "facet") else set()
    return out


def _record(context: Mapping[str, str]) -> dict[str, object]:
    """Context keys become facet paths; ``country`` is also ``location.country``."""
    rec: dict[str, object] = {}
    for key, val in context.items():
        rec[key] = val
        cur = rec
        parts = key.split(".")
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        cur[parts[-1]] = val
    if "country" in context:
        loc = rec.get("location")
        if not isinstance(loc, dict):
            loc = {}
            rec["location"] = loc
        loc.setdefault("country", context["country"])
    return rec


def _in_scope(a: AnswerRecord, context: Mapping[str, str]) -> bool:
    if a.scope == "all_matching":
        return True
    key = {"this_application": "application_id", "this_employer": "employer", "this_country": "country"}[a.scope]
    ref, have = (a.scope_ref or "").strip().casefold(), context.get(key, "").strip().casefold()
    return bool(ref) and ref == have


def match(
    question: str,
    answers: Iterable[AnswerRecord],
    *,
    threshold: float,
    context: Mapping[str, str] | None = None,
    options: Sequence[str] | None = None,
    today: date,
) -> MatchResult:
    ctx = context or {}
    record = _record(ctx)
    scored: list[tuple[float, AnswerRecord]] = []
    for a in answers:
        score = max((similarity(question, p) for p in a.patterns), default=0.0)
        if score >= threshold and _in_scope(a, ctx):
            scored.append((score, a))
    if not scored:
        return MatchResult("ask_owner", reason="no stored answer matches")

    usable: list[tuple[float, AnswerRecord]] = []
    unknown_reason: str | None = None
    for score, a in scored:
        needed = _facets(a.conditions.root)
        if any(lookup(record, f) is None for f in needed):
            unknown_reason = "a condition depends on context that was not supplied"
            continue
        if evaluate(a.conditions, record):
            usable.append((score, a))
    if not usable:
        return MatchResult("ask_owner", similarity=max(s for s, _ in scored),
                           reason=unknown_reason or "no answer's conditions hold")

    usable.sort(key=lambda t: (SCOPE_RANK[t[1].scope], t[0]), reverse=True)
    top_score, top = usable[0]
    rivals = [a for s, a in usable[1:] if SCOPE_RANK[a.scope] == SCOPE_RANK[top.scope]
              and top_score - s <= TIE_MARGIN and (a.value, a.answer_class) != (top.value, top.answer_class)]
    if rivals:
        return MatchResult("ask_owner", similarity=top_score, reason="two answers match equally well")
    return _decide(top, top_score, options, today)


def _decide(a: AnswerRecord, score: float, options: Sequence[str] | None, today: date) -> MatchResult:
    if a.answer_class == "never":
        select = a.forced_choice
        if select and options and normalise(select) not in {normalise(o) for o in options}:
            select = None  # the forced option is not on this form; raise a pending action instead
        return MatchResult("do_not_answer", answer_id=a.id, select=select, similarity=score,
                           reason="owner never answers this")
    if not a.confirmed:
        return MatchResult("ask_owner", answer_id=a.id, similarity=score, reason="answer still needs review")
    if a.review_after is not None and a.review_after <= today:
        return MatchResult("ask_owner", answer_id=a.id, similarity=score, reason="answer is due for review")
    if a.answer_class == "owner_only":
        return MatchResult("ask_owner", answer_id=a.id, similarity=score, reason="owner answers this personally")
    if a.value is None:
        return MatchResult("ask_owner", answer_id=a.id, similarity=score, reason="answer has no value")
    if a.answer_class == "ask_first" and not a.settled:
        return MatchResult("ask_owner", answer_id=a.id, value=a.value, similarity=score,
                           reason="material answer: confirm for this use")
    return MatchResult("value", answer_id=a.id, value=a.value, similarity=score)
