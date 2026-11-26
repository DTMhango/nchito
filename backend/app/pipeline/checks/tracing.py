"""Fact tracing (DESIGN.md 9): every figure, employer, title, date and qualification in the text must
exist in a fact the item cites. Pure. An item that makes such a claim and cites nothing fails, and so
does an item citing a fact that is unknown, not approved, unconfirmed or kept out of prompts.

A figure whose value is in a cited fact but with a different unit or currency is claim drift (18.5),
reported by :func:`figures` with check ``claim_drift``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.pipeline.checks.findings import Finding
from app.pipeline.checks.items import Item
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.checks.tools import ToolTerms, tool_findings
from app.schemas.json_types import ApplicationSpec

TRACE = "fact_trace"
DRIFT = "claim_drift"

# Parsing aids, not business values: how currencies and magnitudes are written.
_CURRENCY = {"us$": "USD", "$": "USD", "usd": "USD", "zmw": "ZMW", "k": "ZMW", "£": "GBP", "gbp": "GBP",
             "€": "EUR", "eur": "EUR", "zar": "ZAR", "r": "ZAR", "kes": "KES", "mwk": "MWK"}
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<cur>US\$|\$|£|€|(?:USD|ZMW|GBP|EUR|ZAR|KES|MWK)\s?|K(?=\d))?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<pct>%|percent\b|per cent\b)|\s?(?P<scale>thousand|million|billion|bn|mn|k|m)\b)?"
    r"(?:\s?(?P<cur2>USD|ZMW|GBP|EUR|ZAR|KES|MWK)\b)?",
    re.IGNORECASE)
_YEAR_RE = re.compile(r"^(19|20)\d\d$")
_ORG_RE = re.compile(
    r"\b(?:at|joined)\s+(?P<org>(?:[A-Z][\w&'.-]*)(?:\s+(?:&|of|and|[A-Z][\w&'.-]*))*)")


@dataclass(frozen=True)
class Figure:
    raw: str
    value: float
    kind: str  # percent, money:<CUR>, year, plain

    def same_value(self, other: Figure) -> bool:
        return abs(self.value - other.value) < 1e-9 * max(1.0, abs(self.value))


def figures_in(text: str) -> list[Figure]:
    out: list[Figure] = []
    for m in _NUMBER_RE.finditer(text):
        num = m.group("num")
        value = float(num.replace(",", ""))
        cur = (m.group("cur") or m.group("cur2") or "").strip().casefold()
        scale = (m.group("scale") or "").casefold()
        if scale:
            value *= _SCALE[scale]
        if m.group("pct"):
            kind = "percent"
        elif cur:
            kind = f"money:{_CURRENCY.get(cur, cur.upper())}"
        elif _YEAR_RE.match(num):
            kind = "year"
        else:
            kind = "plain"
        out.append(Figure(raw=m.group(0).strip(), value=value, kind=kind))
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _has(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", text.casefold()) is not None


def cited_facts(item: Item, kit: KitView) -> tuple[list[FactView], list[Finding]]:
    """The usable facts an item cites, and findings for citations that are not usable."""
    usable: list[FactView] = []
    problems: list[Finding] = []
    for code in item.fact_ids:
        fact = kit.facts.get(code)
        if fact is None:
            problems.append(Finding(TRACE, "block", f"cites {code}, which is not in your Kit", item.path))
        elif fact.keep_out:
            continue  # reported by the keep-out check
        elif not fact.approved:
            problems.append(Finding(TRACE, "block", f"cites {code}, which is not approved", item.path))
        elif not fact.confirmed:
            problems.append(Finding(TRACE, "block", f"cites {code}, which still needs your review", item.path))
        else:
            usable.append(fact)
    return usable, problems


def _source_text(facts: Sequence[FactView], kit: KitView, item: Item) -> str:
    """Everything the cited facts vouch for: their text, and their experiences' org, titles and dates."""
    parts = [f.text for f in facts]
    exp_ids = {f.experience_id for f in facts if f.experience_id}
    if item.experience_id:
        exp_ids.add(item.experience_id)
    for eid in exp_ids:
        exp = kit.experiences.get(eid)
        if exp is not None:
            parts += [exp.org, *exp.titles, *exp.dates]
    return "\n".join(parts)


def figures(item: Item, source: str) -> list[Finding]:
    have = figures_in(source)
    out: list[Finding] = []
    for fig in figures_in(item.text):
        if fig.kind == "year":
            if not any(f.kind in ("year", "plain") and f.same_value(fig) for f in have) and fig.raw not in source:
                out.append(Finding(TRACE, "block", f"date '{fig.raw}' is not in the cited facts", item.path))
            continue
        exact = [f for f in have if f.same_value(fig) and f.kind == fig.kind]
        if exact:
            continue
        loose = [f for f in have if f.same_value(fig)]
        if loose:
            out.append(Finding(DRIFT, "block", f"'{fig.raw}' changes the unit of '{loose[0].raw}' in the cited "
                                               "facts", item.path))
        else:
            out.append(Finding(TRACE, "block", f"figure '{fig.raw}' is not in the cited facts", item.path))
    return out


def _vocabulary(kit: KitView) -> list[str]:
    words = [s.name for s in kit.skills.values()]
    for exp in kit.experiences.values():
        words += [exp.org, *exp.titles]
    return words


def employers(item: Item, source: str, kit: KitView, job_terms: Iterable[str]) -> list[Finding]:
    """Organisations named after "at" or "joined" must be in the cited facts (letters may also
    name the employer and role being applied to)."""
    allowed_extra = [t for t in job_terms if t] if item.scope == "letter" else []
    known_orgs = {e.org.casefold() for e in kit.experiences.values()}
    skills = {s.casefold() for s in kit.skills}
    out: list[Finding] = []
    for m in _ORG_RE.finditer(item.text):
        org = m.group("org").strip(" .,'")
        if (_norm(org) in _norm(source) or any(_norm(org) in _norm(t) or _norm(t) in _norm(org)
                                               for t in allowed_extra) or org.casefold() in skills):
            continue
        if org.casefold() in known_orgs:
            out.append(Finding(TRACE, "block", f"names '{org}', but no cited fact is from there", item.path))
        elif not any(_norm(org) == _norm(w) for w in _vocabulary(kit)):
            out.append(Finding(TRACE, "block", f"names '{org}', which is not in your Kit", item.path))
    return out


def qualifications(item: Item, source: str, terms: Sequence[str]) -> list[Finding]:
    return [Finding(TRACE, "block", f"mentions '{t}', which no cited fact supports", item.path)
            for t in terms if _has(item.text, t) and not _has(source, t)]


def forbidden_titles(item: Item, kit: KitView) -> list[Finding]:
    titles = {t for e in kit.experiences.values() for t in e.forbidden_titles}
    return [Finding(TRACE, "block", f"uses the title '{t}', which you never held", item.path)
            for t in sorted(titles) if _has(item.text, t)]


def experience_titles(spec: ApplicationSpec, kit: KitView) -> list[Finding]:
    """Each experience block must be a Kit experience, with a title the owner held (or allowed for the
    track), and its bullets must cite facts from that experience."""
    out: list[Finding] = []
    track = kit.track.key if kit.track else None
    for i, block in enumerate(spec.experience):
        path = f"experience[{i}]"
        exp = kit.experiences.get(block.experience_id)
        if exp is None:
            out.append(Finding(TRACE, "block", "is not an experience in your Kit", path))
            continue
        if block.title is not None:
            if any(block.title.casefold() == t.casefold() for t in exp.forbidden_titles):
                out.append(Finding(TRACE, "block", f"title '{block.title}' is one you never held", path))
            elif not any(block.title.casefold() == t.casefold() for t in exp.allowed_titles(track)):
                out.append(Finding(TRACE, "block", f"title '{block.title}' is not a title you held at {exp.org}",
                                   path))
        for j, bullet in enumerate(block.bullets):
            for code in bullet.fact_ids:
                fact = kit.facts.get(code)
                if fact and fact.experience_id and fact.experience_id != exp.id:
                    other = kit.experiences.get(fact.experience_id)
                    out.append(Finding(DRIFT, "block", f"{code} is from {other.org if other else 'another role'}, "
                                                       f"not {exp.org}", f"{path}.bullets[{j}]"))
    return out


_CLAIM_TOKEN = re.compile(r"\d")


def trace(spec: ApplicationSpec, items: Sequence[Item], kit: KitView, *, qualification_terms: Sequence[str],
          job_terms: Iterable[str] = (), tools: ToolTerms | None = None,
          posting_terms: Sequence[str] = ()) -> tuple[list[Finding], Mapping[str, list[FactView]]]:
    """All fact-tracing findings, and the usable facts each item cites (keyed by path). Tool tracing
    (:mod:`app.pipeline.checks.tools`) always runs: with no ``tools`` settings it still checks the Kit's
    skills and the posting's ``posting_terms``."""
    job_terms = list(job_terms)
    out = experience_titles(spec, kit)
    cited: dict[str, list[FactView]] = {}
    sources: dict[str, str] = {}
    for item in items:
        facts, problems = cited_facts(item, kit)
        cited[item.path] = facts
        out += problems
        out += forbidden_titles(item, kit)
        if not facts:
            claims = bool(_CLAIM_TOKEN.search(item.text)) or any(_has(item.text, t) for t in qualification_terms)
            if claims and not problems:
                out.append(Finding(TRACE, "block", "states figures or credentials but cites no fact", item.path))
            out += employers(item, "", kit, job_terms)
            continue
        source = _source_text(facts, kit, item)
        sources[item.path] = source
        out += figures(item, source)
        out += employers(item, source, kit, job_terms)
        out += qualifications(item, source, qualification_terms)
    out += tool_findings(items, sources, kit, tools or ToolTerms(), posting=posting_terms, job_terms=job_terms)
    return out, cited
