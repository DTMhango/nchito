"""Fact selection and the tailor prompt.

Only usable facts (approved, confirmed, not kept out of prompts) are ever selected, so a keep-out fact
never reaches a provider. Everything taken from the job posting (title, employer, requirements, text)
goes in one untrusted data block; the owner's own Kit data and guardrails are the instructions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import Field

from app.kit.guardrails import Rule
from app.llm.client import Message, TextPart
from app.llm.untrusted import data_block
from app.models.search import Job
from app.pipeline.checks.kit import FactView, KitView
from app.schemas.json_types import (
    ApplicationSpec,
    FormatRule,
    LimitRule,
    NeverMention,
    NeverTogether,
    OmitField,
    Positioning,
    Reframe,
    RequireWording,
)

_WORD = re.compile(r"[a-z][a-z0-9+#.-]{2,}")


class TailorReply(ApplicationSpec):
    """What the model returns: the spec, plus the screening questions the posting asks (verbatim).
    The questions are data: they are matched against the answer bank, never answered by the model."""

    screening_questions: list[str] = Field(default_factory=list)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold()))


def job_keywords(job: Job) -> set[str]:
    parts = [job.title, *(r.text for r in job.requirements), *(r.skill or "" for r in job.requirements)]
    return _words(" ".join(parts))


def select_facts(kit: KitView, job: Job, *, limit: int) -> list[FactView]:
    """Lead facts of the track first, then the facts sharing most words with the role; facts tied to
    other tracks are left out."""
    track = kit.track
    usable = [f for f in kit.usable_facts() if track is None or not f.tracks or track.key in f.tracks]
    by_code = {f.code: f for f in usable}
    lead = [by_code[c] for c in ((track.lead_fact_codes if track else ()) + (
        (track.summary_fact_code,) if track and track.summary_fact_code else ())) if c in by_code]
    keywords = job_keywords(job)
    rest = sorted((f for f in usable if f not in lead),
                  key=lambda f: (-len(keywords & (_words(f.text) | {t.casefold() for t in f.tags})), f.code))
    seen: set[str] = set()
    out: list[FactView] = []
    for f in [*lead, *rest]:
        if f.code not in seen:
            seen.add(f.code)
            out.append(f)
    return out[:limit]


def guardrail_instructions(rules: Sequence[Rule]) -> list[str]:
    lines: list[str] = []
    for r in rules:
        if not r.enabled:
            continue
        p = r.params
        if isinstance(p, NeverMention) and p.terms:
            lines.append(f"Never mention: {', '.join(p.terms)}.")
        elif isinstance(p, NeverTogether):
            lines.append(f"Never put any of [{', '.join(p.group_a)}] together with any of [{', '.join(p.group_b)}].")
        elif isinstance(p, RequireWording):
            lines.append(f"Write '{p.use}', never {', '.join(repr(x) for x in p.instead_of)}.")
        elif isinstance(p, Reframe):
            lines.append(f"Prefer '{p.prefer}' over '{p.over}'.")
        elif isinstance(p, OmitField):
            lines.append(f"Leave out: {', '.join(f.replace('_', ' ') for f in p.fields)}.")
        elif isinstance(p, FormatRule):
            extra = ", ".join(f"{k}={v}" for k, v in sorted(p.params.items()))
            lines.append(f"Format rule {p.rule}{f' ({extra})' if extra else ''}.")
        elif isinstance(p, Positioning):
            lines.append(p.instruction)
        elif isinstance(p, LimitRule):
            bits = [f"{p.pages} pages" if p.pages else "", f"{p.paragraphs} paragraphs" if p.paragraphs else ""]
            lines.append(f"{p.document}: at most {' and '.join(b for b in bits if b)}.")
    return lines


OUTPUT_RULES = (
    "Return the spec as JSON. Every headline, summary, competency, bullet and letter paragraph lists in "
    "fact_ids the codes of the facts it rests on; use only codes given here. Experience blocks use the "
    "experience ids given here and one of that experience's allowed titles. Skills come only from the "
    "skills list. In screening_questions, copy any questions the posting asks applicants to answer, "
    "word for word; do not answer them."
)


def build_messages(prompt: str, kit: KitView, facts: Sequence[FactView], job: Job, *, letter_paragraphs: int,
                   cv_pages: int, bullets_per_role: int | None) -> list[Message]:
    system = [prompt, OUTPUT_RULES]
    rules = guardrail_instructions(kit.rules)
    if rules:
        system.append("The owner's guardrails (a code checker enforces them):\n" + "\n".join(f"- {x}" for x in rules))
    track = kit.track
    exp_ids = {f.experience_id for f in facts if f.experience_id}
    exps = [e for e in kit.experiences.values() if e.id in exp_ids]
    exp_lines = "\n".join(
        f"{e.id} | {e.org} | allowed titles: {'; '.join(e.allowed_titles(track.key if track else None))} | "
        f"{' to '.join(e.dates[:2])}" for e in exps) or "(none)"
    orgs = {e.id: e.org for e in kit.experiences.values()}
    fact_lines = "\n".join(
        f"{f.code} [{f.kind}]{f' ({orgs[f.experience_id]})' if f.experience_id in orgs else ''}: {f.text}"
        for f in facts) or "(no approved facts)"
    skills = ", ".join(sorted(s.name for s in kit.skills.values() if s.claim == "yes" and s.confirmed)) or "(none)"
    limits = [f"letter: at most {letter_paragraphs} paragraphs", f"CV: at most {cv_pages} pages"]
    if bullets_per_role:
        limits.append(f"at most {bullets_per_role} bullets per role")
    user: list[TextPart] = []
    if track is not None:
        user.append(TextPart(f"Track: {track.name}." + (f" Tone: {track.tone_notes}" if track.tone_notes else "")))
    user += [TextPart("Limits: " + "; ".join(limits) + "."), TextPart(f"Experiences:\n{exp_lines}"),
             TextPart(f"Approved facts:\n{fact_lines}"), TextPart(f"Skills the owner claims: {skills}")]
    requirements = "\n".join(f"- ({r.kind}) {r.text}" for r in job.requirements)
    posting = (f"Title: {job.title}\nEmployer: {job.employer}\n"
               + (f"Requirements:\n{requirements}\n" if requirements else "") + f"\n{job.raw_text or ''}")
    return [Message(role="system", parts=[TextPart("\n\n".join(system))]),
            Message(role="user", parts=[*user, data_block(posting, "job posting")])]
