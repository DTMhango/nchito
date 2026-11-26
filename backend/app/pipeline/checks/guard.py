"""Guardrails, limits, skills and keep-out facts over the spec (DESIGN.md 5.3). Pure.

The code-enforced guardrail types run through :func:`app.kit.guardrails.check` over the whole set of
documents, so a ``never_together`` pair split across CV and letter is caught. ``reframe`` is checked
here as a warning (the disfavoured wording is present); ``positioning`` is an instruction to the model
and is reported only by the model pass. Waivers apply only to ``block, waivable once`` rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from app.kit import guardrails
from app.kit.guardrails import Attachment, Document
from app.pipeline.checks.findings import Finding
from app.pipeline.checks.items import Item
from app.pipeline.checks.kit import KitView
from app.pipeline.checks.tracing import figures_in
from app.schemas.json_types import ApplicationSpec, Reframe

GUARDRAILS = "guardrails"
LIMITS = "limits"
SKILLS = "skills"
KEEP_OUT = "keep_out"
MATCH = "requirement_match"


def guardrail_findings(kit: KitView, docs: Sequence[Document], *, waived: Iterable[str] = (),
                       file_names: Sequence[str] = (), attachments: Sequence[Attachment] = (),
                       released: Iterable[str] = ()) -> list[Finding]:
    waived_ids = set(waived)
    out: list[Finding] = []
    for v in guardrails.check(kit.rules, docs, file_names=file_names, attachments=attachments, released=released):
        is_waived = v.waivable and v.guardrail_id in waived_ids
        detail = f"{v.name}: {v.detail}" + (" (waived for this application)" if is_waived else "")
        out.append(Finding(f"{GUARDRAILS}.{v.type}", v.status, detail, v.document_scope,
                           guardrail_id=None if v.guardrail_id.startswith("skill:") else v.guardrail_id,
                           waived=is_waived))
    for rule in kit.rules:
        if rule.enabled and isinstance(rule.params, Reframe):
            over = re.compile(rf"(?<!\w){re.escape(rule.params.over.strip())}(?!\w)", re.IGNORECASE)
            for d in docs:
                if rule.params.over.strip() and ("everywhere" in rule.scope or d.scope in rule.scope) \
                        and over.search(d.text):
                    out.append(Finding(f"{GUARDRAILS}.reframe", "warn",
                                       f"{rule.name}: prefer '{rule.params.prefer}' over '{rule.params.over}'",
                                       d.scope, guardrail_id=rule.id))
    return out


def limit_findings(spec: ApplicationSpec, *, letter_paragraphs: int, bullets_per_role: int | None) -> list[Finding]:
    """Counted limits. Page counts come from the renderer and are checked there."""
    out: list[Finding] = []
    if len(spec.letter) > letter_paragraphs:
        out.append(Finding(LIMITS, "block", f"{len(spec.letter)} paragraphs, limit {letter_paragraphs}", "letter"))
    if bullets_per_role is not None:
        for i, exp in enumerate(spec.experience):
            if len(exp.bullets) > bullets_per_role:
                out.append(Finding(LIMITS, "warn", f"{len(exp.bullets)} bullets, template limit {bullets_per_role}",
                                   f"experience[{i}]"))
    return out


def skill_findings(spec: ApplicationSpec, kit: KitView) -> list[Finding]:
    out: list[Finding] = []
    for i, name in enumerate(spec.skills):
        skill = kit.skills.get(name.strip().casefold())
        path = f"skills[{i}]"
        if skill is None:
            out.append(Finding(SKILLS, "block", f"'{name}' is not in your skills list", path))
        elif skill.claim == "never":
            continue  # reported by the never-claim guardrail
        elif skill.claim != "yes":
            out.append(Finding(SKILLS, "block", f"you do not claim '{skill.name}'", path))
        elif not skill.confirmed:
            out.append(Finding(SKILLS, "block", f"'{skill.name}' still needs your review", path))
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def keep_out_findings(items: Sequence[Item], docs: Sequence[Document], kit: KitView) -> list[Finding]:
    """A fact kept out of AI prompts must never appear: not cited, not quoted, and none of the figures
    found only in such facts."""
    keep_out = kit.keep_out_facts()
    if not keep_out:
        return []
    out: list[Finding] = []
    codes = {f.code for f in keep_out}
    for item in items:
        for code in item.fact_ids:
            if code in codes:
                out.append(Finding(KEEP_OUT, "block", f"cites {code}, which is kept out of AI prompts", item.path))
    public = [x for f in kit.facts.values() if not f.keep_out for x in figures_in(f.text)]
    for fact in keep_out:
        private = [x for x in figures_in(fact.text) if x.kind != "year"
                   and not any(p.same_value(x) and p.kind == x.kind for p in public)]
        for d in docs:
            if _norm(fact.text) and _norm(fact.text) in _norm(d.text):
                out.append(Finding(KEEP_OUT, "block", f"quotes {fact.code}, which is kept out", d.scope))
                continue
            for fig in figures_in(d.text):
                if any(p.same_value(fig) and p.kind == fig.kind for p in private):
                    out.append(Finding(KEEP_OUT, "block", f"'{fig.raw}' comes from {fact.code}, which is kept out",
                                       d.scope))
    return out


def match_findings(spec: ApplicationSpec, kit: KitView) -> list[Finding]:
    out: list[Finding] = []
    for i, m in enumerate(spec.requirement_match):
        path = f"requirement_match[{i}]"
        bad = [c for c in m.evidence_fact_ids if c not in kit.facts or not kit.facts[c].usable]
        if bad:
            out.append(Finding(MATCH, "warn", f"evidence {', '.join(bad)} is not an approved, usable fact", path))
        if m.strength != "gap" and not [c for c in m.evidence_fact_ids if c not in bad]:
            out.append(Finding(MATCH, "warn", f"'{m.requirement}' marked {m.strength} without evidence", path))
    return out
