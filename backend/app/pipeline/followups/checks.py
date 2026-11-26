"""The checks a message passes before it can be approved: the same code checks as the documents (fact
tracing, claim drift, keep-out, guardrails over the whole outgoing email, length), the optional model claim
check, and one of its own, **commitments**: a message that touches pay, notice or relocation (setting
``followups.commitment_topics``) must use the owner's confirmed answer to that topic word for word. Anything
else is blocked and turned into a question for the owner; nothing is promised on the owner's behalf.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kit.answers import AnswerRecord, match
from app.kit.guardrails import Document
from app.kit.work_rights import to_record
from app.llm.client import LLMClient
from app.models.followups import OutboundMessage
from app.models.kit import Answer
from app.pipeline.checks import claim_check
from app.pipeline.checks import service as checks
from app.pipeline.checks.findings import Finding, summarise
from app.pipeline.checks.kit import KitView
from app.pipeline.followups.context import MessageContext
from app.pipeline.tailoring.answers import context_for
from app.schemas.json_types import ApplicationSpec, CheckResult, SpecItem

COMMITMENT = "commitment"
RECIPIENTS = "recipients"
QUESTIONS = "questions"
CODE_CHECKS = ("fact_trace", "claim_drift", "keep_out", "guardrails", "limits")


def body_of(paragraphs: Sequence[SpecItem]) -> str:
    return "\n\n".join(p.text.strip() for p in paragraphs if p.text.strip())


def paragraphs_from(body: str, previous: Sequence[SpecItem] = ()) -> list[SpecItem]:
    """An owner's edited body back into paragraphs; a paragraph left word for word keeps its cited facts."""
    cited = {p.text.strip(): list(p.fact_ids) for p in previous}
    return [SpecItem(text=t.strip(), fact_ids=cited.get(t.strip(), [])) for t in body.split("\n\n") if t.strip()]


def content_hash(msg: OutboundMessage) -> str:
    """What the checks ran on: recipients, subject and paragraphs with their cited facts."""
    raw = json.dumps({"to": sorted(msg.to), "cc": sorted(msg.cc), "subject": msg.subject,
                      "paragraphs": [p.model_dump(mode="json") for p in msg.paragraphs]},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def topics(lines: Sequence[str]) -> list[tuple[str, str, list[str]]]:
    out = []
    for line in lines:
        topic, question, terms = (p.strip() for p in str(line).split("|"))
        out.append((topic, question, [t.strip().casefold() for t in terms.split(",") if t.strip()]))
    return out


def confirmed_values(topic_lines: Sequence[str], answers: Sequence[AnswerRecord], *, threshold: float,
                     context: Mapping[str, str], today: date) -> list[tuple[str, str, list[str], str | None]]:
    """Each commitment topic with its terms and the owner's confirmed answer (None when there is none)."""
    out = []
    for topic, question, terms in topics(topic_lines):
        r = match(question, answers, threshold=threshold, context=context, today=today)
        out.append((topic, question, terms, r.value if r.outcome == "value" and r.value else None))
    return out


def commitment_findings(paragraphs: Sequence[SpecItem], confirmed: Sequence[tuple[str, str, list[str], str | None]]
                        ) -> tuple[list[Finding], list[str]]:
    """Blocks (and owner questions) for every paragraph that touches a commitment topic without using the
    confirmed answer to it word for word. Pure."""
    findings: list[Finding] = []
    questions: list[str] = []
    for topic, question, terms, value in confirmed:
        for i, p in enumerate(paragraphs):
            text = p.text.casefold()
            if not any(t in text for t in terms):
                continue
            if value is not None and value.casefold() in text:
                continue
            why = (f"mentions {topic.lower()} without your confirmed answer ({value!r})" if value is not None
                   else f"mentions {topic.lower()} and you have no confirmed answer to '{question}'")
            findings.append(Finding(COMMITMENT, "block", f"{why}: decide what to say, or take it out",
                                    f"letter[{i}]"))
            ask = f"{topic}: {question}" if value is None else f"{topic}: say exactly '{value}', or take it out"
            if ask not in questions:
                questions.append(ask)
    return findings, questions


def mask(paragraphs: Sequence[SpecItem], owner_text: Sequence[str]) -> list[SpecItem]:
    """For fact tracing only: the owner's own words (the slot as typed, confirmed answers) are not claims that
    need a Kit fact, so they are blanked out of the traced copy. Guardrails still read the real text."""
    out = []
    for p in paragraphs:
        text = p.text
        for t in sorted((t for t in owner_text if t.strip()), key=len, reverse=True):
            idx = text.casefold().find(t.casefold())
            while idx >= 0:
                text = text[:idx] + "[owner]" + text[idx + len(t):]
                idx = text.casefold().find(t.casefold())
        out.append(SpecItem(text=text, fact_ids=list(p.fact_ids)))
    return out


def recipient_findings(msg: OutboundMessage) -> list[Finding]:
    out: list[Finding] = []
    if not msg.to:
        out.append(Finding(RECIPIENTS, "block", "no recipient"))
    known = {a.lower() for a in [*msg.known_recipients, *msg.confirmed_recipients]}
    for a in [*msg.to, *msg.cc]:
        if a.lower() not in known:
            out.append(Finding(RECIPIENTS, "block", f"{a} is not an address this application has used: confirm it"))
    return out


async def _answers(session: AsyncSession) -> list[AnswerRecord]:
    return [to_record(a) for a in (await session.scalars(select(Answer))).all()]


async def run(session: AsyncSession, msg: OutboundMessage, ctx: MessageContext, kit: KitView,
              values: Mapping[str, Any], *, today: date, client: LLMClient | None = None
              ) -> tuple[list[CheckResult], int]:
    """Check ``msg`` as it stands, store the results and the open questions on it, and return them with the
    model claim check's cost (micros). The model's own questions (``context.model_questions``) block until the
    owner edits the message."""
    owner_questions = [str(q) for q in msg.context.get("model_questions", [])]
    cfg = dataclasses.replace(await checks.check_settings(session, values),
                              letter_paragraphs=int(values["followups.max_paragraphs"]))
    confirmed = confirmed_values(values["followups.commitment_topics"], await _answers(session),
                                 threshold=float(values["answers.match_similarity"]),
                                 context=context_for(ctx.app, ctx.job), today=today)
    owner_text = [str(msg.context.get("slot") or ""), *(v for *_, v in confirmed if v)]
    spec = ApplicationSpec(letter=mask(msg.paragraphs, owner_text))
    email = Document(scope="email", text=f"{msg.subject}\n\n{body_of(msg.paragraphs)}")
    outcome = checks.deterministic(spec, kit, cfg, job_terms=checks.job_terms(ctx.job),
                                  posting_terms=checks.posting_terms(ctx.job), extra_documents=[email])
    findings = [f for f in outcome.findings if f.check.split(".", 1)[0] in CODE_CHECKS]
    found, asks = commitment_findings(msg.paragraphs, confirmed)
    findings += found + recipient_findings(msg)
    run_checks = [*CODE_CHECKS, COMMITMENT, RECIPIENTS]
    questions = [*asks, *(q for q in owner_questions if q not in asks)]
    if questions:
        findings += [Finding(QUESTIONS, "block", f"needs your answer: {q}") for q in owner_questions]
        run_checks.append(QUESTIONS)
    cost = 0
    if client is not None and cfg.claim_check_enabled and outcome.items:
        extra, cost = await claim_check.run(session, client, outcome.items, outcome.cited,
                                            severity=cfg.claim_check_severity, model=values["ai.model_claim_check"])
        findings += extra
        run_checks.append(claim_check.CHECK)
    results = summarise(findings, run_checks)
    msg.check_results, msg.questions, msg.checked_hash = results, questions, content_hash(msg)
    await session.flush()
    return results, cost


def is_checked(msg: OutboundMessage) -> bool:
    return msg.checked_hash is not None and msg.checked_hash == content_hash(msg)
