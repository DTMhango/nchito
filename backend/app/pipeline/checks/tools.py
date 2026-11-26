"""Tool tracing (DESIGN.md 9, 18.5): every tool, technology or skill named in generated text as the
owner's must be in the facts the sentence cites or among the owner's confirmed skills. Pure.

Fact tracing catches invented figures, dates, employers, titles and qualifications; this catches an
invented tool in a sentence that otherwise cites a real fact ("Built the dashboard in Kafka" citing a fact
about a dashboard built in Excel). Terms come from four places:

- the Kit's skills and their aliases (an alias counts as its canonical skill, both ways);
- the posting's requirement terms (required, preferred and per-requirement skills): a term the owner does
  not have is keyword stuffing and is never passed as theirs;
- the ``tailoring.tool_terms`` list;
- optionally (``tailoring.tool_token_detection``) any technical-looking token: CamelCase (PostgreSQL),
  acronyms (AWS), ``C++``/``C#``, ``Node.js``/``.NET``, minus ``tailoring.tool_ignore_terms``, Kit
  employers and titles, and the job's own employer and title.

A sentence that names a tool as the role's or as a gap (``tailoring.tool_role_phrases``: "the role uses
X") does not claim it and passes. Untraced tools are ``fact_trace`` blocks, so like every code check the
model claim check can add to them but never clear them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.pipeline.checks.findings import Finding
from app.pipeline.checks.items import Item
from app.pipeline.checks.kit import KitView

TRACE = "fact_trace"  # same check as tracing.TRACE (kept literal here to avoid an import cycle)

# Token shapes, not business values: what a technical name looks like in running text.
_TOKEN_RE = re.compile(
    r"(?<![\w.#+])(?:"
    r"\.NET"                                   # .NET
    r"|[A-Za-z][A-Za-z0-9]*(?:\+\+|#)"         # C++, C#, F#
    r"|[A-Za-z][A-Za-z0-9]*\.(?:js|NET|io)"    # Node.js, ASP.NET, Socket.io
    r"|[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+"   # PostgreSQL, JavaScript, QuickBooks
    r"|[a-z]+[A-Z][A-Za-z0-9]*"                # iOS, macOS, jQuery
    r"|[A-Z][A-Z0-9]{1,7}s?"                   # SQL, AWS, IFRS, S3, EC2
    r")(?![\w+#])"
)
_SENTENCE_RE = re.compile(r"[^.!?;\n]+(?:[.!?;](?=\s|$)|$)")


@dataclass(frozen=True)
class ToolTerms:
    """The settings side of the check (from ``tailoring.tool_*``)."""

    terms: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    role_phrases: tuple[str, ...] = ()
    token_detection: bool = False


def posting_terms(facets_required: Iterable[str], facets_preferred: Iterable[str],
                  requirement_skills: Iterable[str | None]) -> list[str]:
    seen: dict[str, str] = {}
    for t in (*facets_required, *facets_preferred, *(s for s in requirement_skills if s)):
        t = t.strip()
        if t and t.casefold() not in seen:
            seen[t.casefold()] = t
    return list(seen.values())


def _pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w.#+]){re.escape(term)}(?![\w#+]|\.\w)", re.IGNORECASE)


def _found(text: str, term: str) -> bool:
    """Case-insensitive, but a term written with capitals does not match an all-lowercase word, so the
    verb "excel" is not the tool "Excel"."""
    has_upper = any(c.isupper() for c in term)
    for m in _pattern(term).finditer(text):
        if has_upper and m.group(0) == m.group(0).lower() and any(c.isalpha() for c in m.group(0)):
            continue
        return True
    return False


def _in(text: str, term: str) -> bool:
    return _pattern(term).search(text) is not None


@dataclass(frozen=True)
class _Vocab:
    canonical: dict[str, str]      # casefolded name or alias -> canonical display name
    spellings: dict[str, set[str]]  # casefolded canonical -> every spelling (canonical and aliases)
    owned: set[str]                # casefolded canonical of confirmed, claimed skills
    posting: set[str]              # casefolded canonical of posting terms
    known: list[str]               # every term to look for in text (names, aliases, posting, list)


def _vocab(kit: KitView, posting: Sequence[str], cfg: ToolTerms) -> _Vocab:
    canonical: dict[str, str] = {}
    spellings: dict[str, set[str]] = {}

    def add(name: str, canon: str) -> None:
        canonical.setdefault(name.casefold(), canon)
        spellings.setdefault(canon.casefold(), {canon}).add(name)

    for alias, canon in kit.skill_aliases.items():
        add(canon, canon)
        add(alias, canon)
    for s in kit.skills.values():
        add(s.name, canonical.get(s.name.casefold(), s.name))
    for t in (*posting, *cfg.terms):
        add(t, canonical.get(t.casefold(), t))
    owned = {canonical.get(s.name.casefold(), s.name).casefold() for s in kit.skills.values()
             if s.claim == "yes" and s.confirmed}
    posting_set = {canonical.get(t.casefold(), t).casefold() for t in posting}
    known = sorted({n for names in spellings.values() for n in names}, key=len, reverse=True)
    return _Vocab(canonical, spellings, owned, posting_set, known)


def _sentences(text: str) -> list[str]:
    return [m.group(0) for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()]


def _names_not_claims(sentence: str, phrases: Sequence[str]) -> bool:
    low = sentence.casefold()
    return any(re.search(rf"(?<!\w){re.escape(p.casefold())}(?!\w)", low) for p in phrases if p.strip())


def _supported(canon: str, source: str, vocab: _Vocab) -> bool:
    key = canon.casefold()
    if key in vocab.owned:
        return True
    return any(_in(source, s) for s in vocab.spellings.get(key, {canon}))


def tool_findings(items: Sequence[Item], sources: dict[str, str], kit: KitView, cfg: ToolTerms, *,
                  posting: Sequence[str] = (), job_terms: Iterable[str] = ()) -> list[Finding]:
    """Blocks for every tool named as the owner's that neither the item's cited facts (``sources`` keyed by
    item path) nor a confirmed skill supports."""
    vocab = _vocab(kit, posting, cfg)
    ignore = {t.casefold() for t in cfg.ignore}
    context = "\n".join([*(t for t in job_terms if t), *(e.org for e in kit.experiences.values()),
                         *(t for e in kit.experiences.values() for t in e.titles)])
    out: list[Finding] = []
    for item in items:
        source = sources.get(item.path, "")
        reported: set[str] = set()
        for sentence in _sentences(item.text):
            if _names_not_claims(sentence, cfg.role_phrases):
                continue
            named: list[str] = []
            rest = sentence
            for term in vocab.known:
                if _found(rest, term):
                    named.append(vocab.canonical.get(term.casefold(), term))
                    rest = _pattern(term).sub(" ", rest)  # "Power BI" is not also "BI"
            if cfg.token_detection:
                for m in _TOKEN_RE.finditer(rest):
                    tok = m.group(0)
                    if tok.casefold() in ignore or tok.casefold().rstrip("s") in ignore or _in(context, tok):
                        continue
                    named.append(tok)
            for canon in named:
                key = canon.casefold()
                if key in reported or _supported(canon, source, vocab):
                    continue
                reported.add(key)
                why = ("the posting asks for it, but no cited fact or confirmed skill of yours shows it"
                       if key in vocab.posting else "which no cited fact or confirmed skill supports")
                out.append(Finding(TRACE, "block", f"names the tool '{canon}', {why}", item.path))
    return out
