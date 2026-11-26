"""Truth checks for pack sections: the document checks, reused, not forked (DESIGN.md 5.3, 9, 18.5).

Each section is walked into located :class:`~app.pipeline.checks.items.Item` rows (one per claim about the
owner) and plain text (everything else). The claims go through :func:`app.pipeline.checks.tracing.trace`
and :func:`app.pipeline.checks.drift.drift`, exactly as CV bullets do; every text goes through the
keep-out check and the guardrails. An invented figure, employer or qualification is a ``block``.

Claim items use the letter's scope for tracing: like a letter, the pack may name the employer and the
role being interviewed for. Guardrails see the pack as scope ``interview``, so rules scoped
``everywhere`` apply and rules written for one outgoing document (a CV-only ``omit_field``) do not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.kit.guardrails import Document
from app.pipeline.checks import guard, tracing
from app.pipeline.checks.drift import drift
from app.pipeline.checks.findings import Finding
from app.pipeline.checks.items import Item
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.checks.service import CheckSettings
from app.pipeline.interview import shapes as sh
from app.schemas.json_types import ApplicationSpec

SCOPE = "interview"
CLAIM_SCOPE = "letter"
CHECKS_RUN = (tracing.TRACE, tracing.DRIFT, guard.KEEP_OUT, guard.GUARDRAILS)


def _claim(path: str, c: sh.Claim) -> Item:
    return Item(path, CLAIM_SCOPE, c.text, tuple(c.fact_ids))


def claim_items(section: str, content: sh.Shape) -> list[Item]:
    """Every sentence about the owner, with the facts it cites."""
    out: list[Item] = []
    if isinstance(content, sh.WhyYou):
        out += [_claim(f"points[{i}]", p.point) for i, p in enumerate(content.points)]
    elif isinstance(content, sh.Questions):
        out += [_claim(f"items[{i}].answer", q.answer) for i, q in enumerate(content.items)]
    elif isinstance(content, sh.Stories):
        for i, s in enumerate(content.items):
            codes = tuple(s.fact_ids)
            out += [Item(f"items[{i}].{part}", CLAIM_SCOPE, getattr(s, part), codes)
                    for part in ("title", "situation", "task", "action", "result") if getattr(s, part).strip()]
    elif isinstance(content, sh.Gaps):
        out += [_claim(f"items[{i}].answer", g.answer) for i, g in enumerate(content.items)]
    elif isinstance(content, sh.CribSheet):
        pass  # built from checked sections; its text still goes through keep-out and guardrails
    return out


def other_texts(content: sh.Shape) -> list[str]:
    """Text that is not a claim about the owner (posting-derived wording, questions, notes)."""
    if isinstance(content, sh.RoleBrief):
        return [content.summary, *content.emphasised, *content.requirements, content.level_notes,
                *content.company_notes]
    if isinstance(content, sh.WhyYou):
        return [p.requirement for p in content.points]
    if isinstance(content, sh.Questions):
        return [t for q in content.items for t in (q.question, q.why_asked)]
    if isinstance(content, sh.Stories):
        return [s.requirement for s in content.items]
    if isinstance(content, sh.QuestionsToAsk):
        return [t for q in content.items for t in (q.question, q.why)]
    if isinstance(content, sh.Gaps):
        return [t for g in content.items for t in (g.requirement, g.gap)]
    if isinstance(content, sh.PaySheet):
        return [t for line in content.lines for t in (line.kit_answer or "", line.told_them or "", line.note)]
    if isinstance(content, sh.CribSheet):
        return [content.role, *content.points, *content.stories, *content.questions_to_ask, *content.pay,
                *content.gaps]
    return []


def fact_ids(content: sh.Shape, section: str) -> list[str]:
    return sorted({c for it in claim_items(section, content) for c in it.fact_ids})


@dataclass
class SectionCheck:
    findings: list[Finding]
    items: list[Item]
    cited: Mapping[str, list[FactView]]


def check(section: str, content: sh.Shape, kit: KitView, cfg: CheckSettings, *,
          job_terms: Iterable[str] = (), posting_terms: Sequence[str] = ()) -> SectionCheck:
    """Pure: the same content, Kit and settings always give the same findings."""
    located = claim_items(section, content)
    findings, cited = tracing.trace(ApplicationSpec(), located, kit, qualification_terms=cfg.qualification_terms,
                                    job_terms=job_terms, tools=cfg.tools, posting_terms=posting_terms)
    findings += drift(located, cited, cfg.drift_terms)
    text = "\n".join([*(it.text for it in located), *(t for t in other_texts(content) if t)])
    docs: Sequence[Document] = [Document(scope=SCOPE, text=text,
                                         fact_codes=frozenset(c for it in located for c in it.fact_ids))]
    findings += guard.keep_out_findings(located, docs, kit)
    findings += guard.guardrail_findings(kit, docs)
    return SectionCheck(findings=findings, items=located, cited={k: list(v) for k, v in cited.items()})


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.status == "block" and not f.waived]


KEEP_OUT_NOTE = "A sentence used material that is not among the approved facts listed. Use only those facts."


def retry_notes(findings: Iterable[Finding], kit: KitView) -> list[str]:
    """What a regeneration is told about the failed checks. Nothing about a keep-out fact is repeated:
    no code, no figure, no quote; a keep-out finding becomes one generic line."""
    private = [x for f in kit.keep_out_facts() for x in tracing.figures_in(f.text) if x.kind != "year"]
    codes = {f.code for f in kit.keep_out_facts()}
    notes: list[str] = []
    hidden = False
    for f in blocking(findings):
        detail = f.result().detail or f.check
        leaks = (f.check == guard.KEEP_OUT or any(c in detail for c in codes)
                 or any(p.same_value(x) for x in tracing.figures_in(detail) for p in private))
        if leaks:
            hidden = True
        elif detail not in notes:
            notes.append(detail)
    return [*notes, KEEP_OUT_NOTE] if hidden else notes
