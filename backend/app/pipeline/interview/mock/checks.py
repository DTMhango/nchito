"""Truth rules for mock interview feedback: the pack's checks, reused (DESIGN.md 5.3, 9, 10.3a).

- A suggested answer is built only from approved Kit facts and what the owner actually said in this session.
  The owner's answers join the Kit view as citable sources (code ``A<seq>``), so fact tracing accepts a figure
  the owner said and rejects one nobody said. Every sentence must cite something; one that fails a check is
  removed from the suggestion and kept as a flagged item, never shown as a suggestion. A flagged item that
  touched a keep-out fact keeps no text.
- An owner statement that no approved fact supports is never treated as verified: it becomes an
  ``unverified`` claim the owner may add to the library as a draft fact, or dismiss.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.kit.guardrails import Document
from app.pipeline.checks import guard, tracing
from app.pipeline.checks.findings import Finding
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.checks.service import CheckSettings
from app.pipeline.interview import shapes as sh
from app.pipeline.interview import truth
from app.pipeline.interview.mock.shapes import AnswerFeedback

OWNER_WORDS_KIND = "owner_words"
NO_CITATION = "cites no fact and none of your answers"
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")


def answer_code(seq: int) -> str:
    return f"A{seq}"


def with_owner_words(kit: KitView, answers: Mapping[int, str]) -> KitView:
    """The Kit view plus the owner's answers in this session as citable sources."""
    extra = {answer_code(seq): FactView(code=answer_code(seq), text=text, kind=OWNER_WORDS_KIND, experience_id=None,
                                        approved=True, confirmed=True, keep_out=False, hash="")
             for seq, text in answers.items()}
    return dataclasses.replace(kit, facts={**kit.facts, **extra})


def _reasons(findings: Sequence[Finding], kit: KitView) -> tuple[list[str], bool]:
    """Reasons safe to show, and whether the claim touched a keep-out fact (then its text is withheld)."""
    notes = truth.retry_notes(findings, kit)
    hidden = truth.KEEP_OUT_NOTE in notes
    return [n for n in notes if n != truth.KEEP_OUT_NOTE] or ["failed the truth checks"], hidden


def check_suggested(claims: Iterable[sh.Claim], kit: KitView, answers: Mapping[int, str], cfg: CheckSettings, *,
                    job_terms: Iterable[str], posting_terms: Sequence[str] = ()
                    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(kept, removed)``. Kept items carry their sources (Kit fact or "your words"); removed items carry the
    reasons, and no text when a keep-out fact was involved."""
    ext = with_owner_words(kit, answers)
    terms = list(job_terms)
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for claim in claims:
        if not claim.text.strip():
            continue
        result = truth.check("why_you", sh.WhyYou(points=[sh.TalkingPoint(point=claim)]), ext, cfg, job_terms=terms,
                             posting_terms=posting_terms)
        blocks = truth.blocking(result.findings)
        if not claim.fact_ids:
            blocks.append(Finding(tracing.TRACE, "block", NO_CITATION, "points[0].point"))
        if blocks:
            reasons, hidden = _reasons(blocks, kit)
            removed.append({"text": None if hidden else claim.text, "fact_ids": [] if hidden else claim.fact_ids,
                            "reasons": ["Used material you keep out of AI prompts."] if hidden else reasons})
            continue
        sources = [{"code": c, "kind": "your_words" if c in ext.facts and ext.facts[c].kind == OWNER_WORDS_KIND
                    else "fact", "text": ext.facts[c].text[:300] if c in ext.facts else ""} for c in claim.fact_ids]
        warn = [f.result().detail for f in result.findings if f.status == "warn"]
        kept.append({"text": claim.text, "fact_ids": claim.fact_ids, "sources": sources,
                     "status": "warn" if warn else "pass", "warnings": warn})
    return kept, removed


def clamp_scores(scores: Iterable[Any], dimensions: Sequence[str], top: int) -> dict[str, int]:
    """Only rubric dimensions, each between 1 and the top score; a model cannot award more."""
    out: dict[str, int] = {}
    for s in scores:
        if s.dimension in dimensions:
            out[s.dimension] = max(1, min(top, int(s.score)))
    return out


def checked_feedback(fb: AnswerFeedback, kit: KitView, answers: Mapping[int, str], cfg: CheckSettings, *,
                     job_terms: Iterable[str], dimensions: Sequence[str], top: int,
                     posting_terms: Sequence[str] = ()) -> dict[str, Any]:
    kept, removed = check_suggested(fb.suggested, kit, answers, cfg, job_terms=job_terms,
                                    posting_terms=posting_terms)
    other = "\n".join([fb.structure, fb.relevance, fb.specificity, *fb.strong, *fb.tighten])
    leaks = guard.keep_out_findings([], [Document(scope=truth.SCOPE, text=other, fact_codes=frozenset())], kit)
    data: dict[str, Any] = {
        "structure": fb.structure, "relevance": fb.relevance, "specificity": fb.specificity,
        "strong": fb.strong, "tighten": fb.tighten,
        "scores": clamp_scores(fb.scores, dimensions, top), "suggested": kept, "removed": removed,
    }
    if leaks:  # commentary quoting a keep-out fact is withheld, not shown
        data.update(structure="", relevance="", specificity="", strong=[], tighten=[],
                    withheld="Some commentary used material you keep out of AI prompts and is not shown.")
    return data


def _sentence_with(text: str, raw: str) -> str:
    for m in _SENTENCE_RE.finditer(text):
        if raw in m.group(0):
            return m.group(0).strip()[:300]
    return raw


def unverified_claims(answer: str, model_claims: Iterable[str], kit: KitView) -> list[dict[str, Any]]:
    """Statements in the owner's answer the approved facts do not contain: the model's list, plus every sentence
    with a figure that no usable fact states (code, so a model that misses one cannot hide it)."""
    source = "\n".join(f.text for f in kit.usable_facts())
    have = tracing.figures_in(source)
    out: list[str] = []
    for c in model_claims:
        c = c.strip()[:300]
        if c and c not in out:
            out.append(c)
    for fig in tracing.figures_in(answer):
        if fig.kind == "year" and fig.raw in source:
            continue
        if any(h.same_value(fig) and (h.kind == fig.kind or fig.kind == "plain") for h in have):
            continue
        if any(fig.raw in c for c in out):
            continue
        sentence = _sentence_with(answer, fig.raw)
        if sentence not in out:
            out.append(sentence)
    return [{"id": f"c{i + 1}", "text": t, "status": "unverified", "fact_code": None} for i, t in enumerate(out)]


def usable_codes(codes: Iterable[str], kit: KitView) -> list[str]:
    return sorted({c for c in codes if c in kit.facts and kit.facts[c].usable})
