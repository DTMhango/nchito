"""Work rights from the Kit's answer bank (DESIGN.md 5.4, 7).

The eligibility filter used to read the owner's work rights as unknown. This module reads them from
the **confirmed** answers about right to work, sponsorship and relocation, honouring each answer's
conditions (a country, for example) for the country the job requires. Pure: no database here
except ``load_answers``.

Rules that keep it honest:

- An answer that is not confirmed, is due for review, is class ``never``, or whose conditions need a
  fact the job does not give, never counts: that is *unknown*, not yes.
- Two applicable answers that disagree are *unknown*.
- Nothing here names a country or a default: every fact comes from an answer the owner confirmed.
- Only answers that apply generally (all matching roles, or this country) count. An answer scoped to
  one application or employer is about that use, not about the owner's rights.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conditions import evaluate, lookup
from app.kit.answers import AnswerRecord, _facets, _in_scope, _record, normalise
from app.models.base import ReviewState
from app.models.kit import Answer

Kind = Literal["right", "sponsorship", "relocation"]

# How a stored question is recognised. Matched against the normalised canonical text and variants.
# The right-to-work words come first: "authorised to work without sponsorship" is a right question.
_KEYWORDS: tuple[tuple[Kind, tuple[str, ...]], ...] = (
    ("right", ("right to work", "authorised to work", "authorized to work", "eligible to work",
               "permitted to work", "legally work", "work permit", "work authorisation", "work authorization")),
    ("sponsorship", ("sponsor", "visa")),
    ("relocation", ("relocat", "move to")),
)
_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}


def classify(patterns: Iterable[str]) -> Kind | None:
    texts = [normalise(p) for p in patterns]
    for kind, words in _KEYWORDS:
        if any(w in t for t in texts for w in words):
            return kind
    return None


def yes_no(value: str | None) -> bool | None:
    if value is None:
        return None
    word = normalise(value)
    return True if word in _YES else False if word in _NO else None


@dataclass(frozen=True)
class Fact:
    """One resolved fact: ``value`` is True / False, or None when the Kit cannot say."""

    value: bool | None = None
    answer_id: str | None = None
    question: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class KitWorkRights:
    right: Fact = Fact()
    needs_sponsorship: Fact = Fact()
    will_relocate: Fact = Fact()

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def to_record(a: Answer) -> AnswerRecord:
    return AnswerRecord(
        id=a.id, patterns=(a.patterns.canonical, *a.patterns.variants), value=a.value,
        answer_class=a.answer_class.value, conditions=a.conditions, scope=a.scope.value, scope_ref=a.scope_ref,
        settled=a.settled, confirmed=a.review_state == ReviewState.confirmed, forced_choice=a.forced_choice,
        review_after=a.review_after)


async def load_answers(session: AsyncSession) -> list[AnswerRecord]:
    """Only answers that could be about work rights, as matcher records."""
    rows = (await session.scalars(select(Answer))).all()
    return [to_record(a) for a in rows if classify((a.patterns.canonical, *a.patterns.variants)) is not None]


def _applies(a: AnswerRecord, context: Mapping[str, str], today: date) -> bool:
    if not a.confirmed or a.answer_class == "never" or a.value is None:
        return False
    if a.review_after is not None and a.review_after <= today:
        return False
    if a.scope in ("this_application", "this_employer"):
        return False
    if not _in_scope(a, context):
        return False
    record = _record(context)
    if any(lookup(record, f) is None for f in _facets(a.conditions.root)):
        return False  # the job does not say what this answer's condition needs: unknown, not yes
    return bool(evaluate(a.conditions, record))


def _resolve(kind: Kind, answers: Sequence[AnswerRecord], countries: Sequence[str | None], today: date) -> Fact:
    """Any country that yields a yes counts as yes; a disagreement inside one country is unknown."""
    best: Fact | None = None
    for country in countries or [None]:
        context = {"country": country} if country else {}
        hits = [a for a in answers if classify(a.patterns) == kind and _applies(a, context, today)
                and yes_no(a.value) is not None]
        if not hits:
            continue
        values = {yes_no(a.value) for a in hits}
        if len(values) > 1:
            return Fact(None, note="your confirmed answers disagree")
        hit = max(hits, key=lambda a: {"this_country": 1}.get(a.scope, 0))
        fact = Fact(yes_no(hit.value), str(hit.id), hit.patterns[0])
        if fact.value:
            return fact
        best = best or fact
    return best or Fact()


def resolve(answers: Sequence[AnswerRecord], countries: Sequence[str | None], *, today: date) -> KitWorkRights:
    """What the confirmed answers say for a job that requires living in one of ``countries``."""
    return KitWorkRights(right=_resolve("right", answers, countries, today),
                         needs_sponsorship=_resolve("sponsorship", answers, countries, today),
                         will_relocate=_resolve("relocation", answers, countries, today))


def job_countries(job: Mapping[str, Any]) -> list[str]:
    """Places the job requires you to be in: ``where you must live``, else where the job is."""
    facets = job.get("facets") or {}
    where = facets.get("where_must_live")
    places: list[str] = []
    if isinstance(where, Mapping):
        places = [p for p in where.get("places") or [] if p]
    if not places:
        loc = job.get("location") or {}
        places = [p for p in (loc.get("country"),) if p]
    return places
