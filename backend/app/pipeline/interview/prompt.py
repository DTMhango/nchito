"""Messages for each generated pack section.

Instructions are the stage prompt, the section's rules and the owner's guardrails. The owner's approved,
usable facts (never keep-out ones: selection reuses :func:`app.pipeline.tailoring.prompt.select_facts`)
are given as plain text. Everything that came from outside or may echo it goes in data blocks: the posting,
the documents and answers sent, employer mail, the owner's notes (which may hold pasted interviewer
notes), and the findings of a failed attempt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import DataBlock, Message, TextPart
from app.llm.untrusted import data_block
from app.models.search import Job
from app.pipeline.checks.items import items as spec_items
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.interview.basis import Basis
from app.pipeline.tailoring.prompt import guardrail_instructions
from app.schemas.json_types import ApplicationSpec, PacketAnswer

CLAIM_RULE = ("Every sentence about the candidate lists in fact_ids the codes of the approved facts it rests on; "
              "use only codes given here. Never add a number, employer, job title, date or qualification that "
              "is not in the cited facts, and never strengthen the candidate's role (for example 'contributed "
              "to' must not become 'led').")


def section_rules(section: str, values: Mapping[str, Any]) -> str:
    per_cat = int(values["interview.questions_per_category"])
    stories = int(values["interview.max_stories"])
    rules = {
        "role_brief": (
            "Write the role brief from the job posting only: a plain summary of the job, what the posting "
            "emphasises, its requirements as stated, what to expect at this level, and company notes taken only "
            "from the posting or the owner's notes. Do not use outside knowledge of the employer. Say nothing "
            "about the candidate."),
        "why_you": (
            "Write talking points on why the candidate fits, each tied to a requirement of the posting and "
            f"built only from the approved facts. {CLAIM_RULE}"),
        "questions": (
            "List likely interview questions in the categories behavioural, technical (only for the tools and "
            "stack the posting names), role (the role and its domain), motivation and logistics (pay, notice, "
            f"right to work, relocation, start date). At most {per_cat} per category. Give each a suggested answer "
            "as a short story (situation, action, result) built only from the approved facts. For logistics, "
            "the suggested answer says to use the pay and logistics sheet and gives no figures. "
            f"{CLAIM_RULE}"),
        "stories": (
            f"Build at most {stories} STAR stories (situation, task, action, result) with ids s1, s2, ..., each "
            "mapped to a requirement of the posting and resting on the approved facts listed in its fact_ids. "
            f"{CLAIM_RULE}"),
        "questions_to_ask": (
            "Suggest good questions for the candidate to ask the interviewers, grounded in the posting, with a "
            "short reason for each. Say nothing about the candidate."),
        "gaps": (
            "List the posting's requirements the approved facts do not cover, or cover weakly. For each, state "
            "the gap plainly and how to address it honestly, consistent with the letter that was sent. Never "
            f"claim experience the facts do not show. {CLAIM_RULE}"),
    }
    return rules[section]


@dataclass
class PackContext:
    job: Job
    kit: KitView
    facts: Sequence[FactView]
    basis: Basis
    spec: ApplicationSpec | None = None
    answers: Sequence[PacketAnswer] = ()
    mail: Sequence[str] = ()
    notes: Sequence[str] = ()
    extra: dict[str, str] = field(default_factory=dict)


def posting_text(job: Job) -> str:
    requirements = "\n".join(f"- ({r.kind}) {r.text}" for r in job.requirements)
    return (f"Title: {job.title}\nEmployer: {job.employer}\n"
            + (f"Requirements:\n{requirements}\n" if requirements else "") + f"\n{job.raw_text or ''}")


def sent_text(spec: ApplicationSpec) -> str:
    lines = [f"{it.path} [{', '.join(it.fact_ids) or 'no facts'}]: {it.text}" for it in spec_items(spec)]
    if spec.skills:
        lines.append(f"skills: {', '.join(spec.skills)}")
    return "\n".join(lines)


def kit_parts(ctx: PackContext) -> list[TextPart]:
    kit = ctx.kit
    track = kit.track
    orgs = {e.id: e.org for e in kit.experiences.values()}
    exp_ids = {f.experience_id for f in ctx.facts if f.experience_id}
    exp_lines = "\n".join(
        f"{e.org} | titles: {'; '.join(e.allowed_titles(track.key if track else None))} | "
        f"{' to '.join(e.dates[:2])}" for e in kit.experiences.values() if e.id in exp_ids) or "(none)"
    fact_lines = "\n".join(
        f"{f.code} [{f.kind}]{f' ({orgs[f.experience_id]})' if f.experience_id in orgs else ''}: {f.text}"
        for f in ctx.facts) or "(no approved facts)"
    skills = ", ".join(sorted(s.name for s in kit.skills.values() if s.claim == "yes" and s.confirmed)) or "(none)"
    return [TextPart(f"Experiences:\n{exp_lines}"), TextPart(f"Approved facts:\n{fact_lines}"),
            TextPart(f"Skills the candidate claims: {skills}")]


def build_messages(prompt: str, section: str, ctx: PackContext, values: Mapping[str, Any], *,
                   retry_problems: Sequence[str] = ()) -> list[Message]:
    system = [prompt, section_rules(section, values)]
    rules = guardrail_instructions(ctx.kit.rules)
    if rules:
        system.append("The owner's guardrails (a code checker enforces them):\n" + "\n".join(f"- {x}" for x in rules))
    user: list[TextPart | DataBlock] = []
    if section != "role_brief" and section != "questions_to_ask":
        user += kit_parts(ctx)
    user.append(data_block(posting_text(ctx.job), "job posting"))
    if ctx.spec is not None and section != "role_brief":
        user.append(TextPart("The CV and letter the employer has are in the next data block."))
        user.append(data_block(sent_text(ctx.spec), "documents sent"))
    if ctx.answers and section in ("questions", "gaps"):
        user.append(data_block("\n".join(f"Q: {a.question}\nA: {a.value}" for a in ctx.answers), "answers given"))
    if ctx.mail:
        user.append(data_block("\n".join(ctx.mail), "employer mail"))
    if ctx.notes:
        user.append(data_block("\n\n".join(ctx.notes), "owner notes"))
    for label, text in ctx.extra.items():
        user.append(data_block(text, label))
    if retry_problems:
        user.append(TextPart("A previous attempt failed the code checks for the reasons in the next data block. "
                             "Write the section again so that every claim is supported by its cited facts."))
        user.append(data_block("\n".join(retry_problems), "failed checks"))
    return [Message(role="system", parts=[TextPart("\n\n".join(system))]), Message(role="user", parts=user)]
