"""Drafting a message about an application from Kit facts and the thread, through the budgeted model.

The model sees: the owner's own data (approved, usable facts only; confirmed answers on the commitment
topics; the owner's note and, for a slot answer, the slot as the owner typed it) as instructions, and
everything from outside (the posting, the employer's subject, sender and message excerpt, interview round
details) only inside untrusted data blocks. It returns paragraphs citing fact codes plus questions for the
owner; the subject, recipients and thread are set by code. The result is a draft: nothing is sent from here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.kit.answers import match
from app.kit.work_rights import to_record
from app.llm.client import BudgetExhausted, LLMClient, LLMError, Message, TextPart
from app.llm.untrusted import data_block
from app.models.applications import Application
from app.models.followups import OutboundMessage
from app.models.kit import Answer, Person
from app.pipeline.checks import service as check_service
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.followups import checks
from app.pipeline.followups import context as ctx_mod
from app.pipeline.followups.context import MessageContext
from app.pipeline.tailoring.answers import context_for
from app.pipeline.tailoring.prompt import guardrail_instructions, select_facts
from app.schemas.json_types import MessageKind, SpecItem

log = logging.getLogger(__name__)

STAGE = "followup"
NEEDS_SLOT = frozenset({"slot_accept", "slot_decline"})

OUTPUT_RULES = (
    "Return JSON: paragraphs (each with its text and fact_ids, the codes of the facts it rests on; use only "
    "codes given here; a greeting or sign-off paragraph cites none) and questions_for_owner. Write plain, short, "
    "polite email paragraphs, greeting first and sign-off last. Never invent a fact, number, date, name or "
    "promise. Never state or agree to pay, a notice period, a start date or relocation unless it is one of the "
    "owner's confirmed answers below, word for word: when the message would need one, leave it out and add a "
    "question for the owner instead. Never accept or decline anything the owner has not stated."
)


class MessageReply(BaseModel):
    paragraphs: list[SpecItem] = Field(default_factory=list)
    questions_for_owner: list[str] = Field(default_factory=list)


class DraftError(ValueError):
    def __init__(self, message: str, code: str = "refused", status: int = 422) -> None:
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def brief_for(kind: str, lines: Sequence[str]) -> str:
    for line in lines:
        k, _, text = str(line).partition("|")
        if k.strip() == kind:
            return text.strip()
    raise DraftError(f"no instruction for message kind {kind!r} (setting followups.kind_briefs)", "refused", 422)


async def _confirmed_answers(session: AsyncSession, ctx: MessageContext, values: Mapping[str, Any],
                             now: datetime) -> list[str]:
    records = [to_record(a) for a in (await session.scalars(select(Answer))).all()]
    out = []
    for topic, question, _ in checks.topics(values["followups.commitment_topics"]):
        r = match(question, records, threshold=float(values["answers.match_similarity"]),
                  context=context_for(ctx.app, ctx.job), today=now.date())
        if r.outcome == "value" and r.value:
            out.append(f"{topic}: {r.value}")
    return out


async def _signature(session: AsyncSession) -> str | None:
    person = await session.scalar(select(Person).limit(1))
    if person is None:
        return None
    name = person.preferred_name or person.full_name
    return name.value if name and name.value else None


def build_messages(kind: str, brief: str, kit: KitView, facts: Sequence[FactView], ctx: MessageContext, *,
                   inputs: Mapping[str, str], confirmed: Sequence[str], signature: str | None, max_paragraphs: int,
                   excerpt_chars: int) -> list[Message]:
    system = [f"You draft one email for a job seeker about an application they have already made. Purpose: {brief}",
              OUTPUT_RULES, f"At most {max_paragraphs} paragraphs."]
    rules = guardrail_instructions(kit.rules)
    if rules:
        system.append("The owner's guardrails (a code checker enforces them):\n" + "\n".join(f"- {x}" for x in rules))
    fact_lines = "\n".join(f"{f.code} [{f.kind}]: {f.text}" for f in facts) or "(no approved facts)"
    user: list[Any] = [TextPart(f"Message kind: {kind}. Application stage: {ctx.app.stage.value}."),
                       TextPart(f"Approved facts:\n{fact_lines}"),
                       TextPart("The owner's confirmed answers:\n" + ("\n".join(confirmed) or "(none)"))]
    if signature:
        user.append(TextPart(f"Sign off as: {signature}"))
    if inputs.get("note"):
        user.append(TextPart(f"The owner's note for this message: {inputs['note']}"))
    if kind in NEEDS_SLOT and inputs.get("slot"):
        user.append(TextPart(f"The interview slot, exactly as the owner gave it: {inputs['slot']}"))
    user.append(data_block(f"Title: {ctx.job.title}\nEmployer: {ctx.job.employer}", "job posting"))
    thread = ctx.thread
    if thread is not None:
        user.append(data_block(f"Subject: {thread.subject or ''}\nFrom: {thread.sender or ''}\n"
                               f"Classified as: {thread.classification.value}", "employer email thread"))
    if inputs.get("excerpt"):
        user.append(data_block(inputs["excerpt"][:excerpt_chars], "employer email excerpt"))
    if ctx.round is not None and kind == "thank_you":
        r = ctx.round
        user.append(data_block(
            f"Round {r.round_number}; format: {r.format or 'not recorded'}; interviewers: "
            f"{', '.join(r.interviewers) or 'not recorded'}; notes: {r.notes or 'none'}", "interview round"))
    return [Message(role="system", parts=[TextPart("\n\n".join(system))]), Message(role="user", parts=user)]


def _inputs(raw: Mapping[str, Any] | None) -> dict[str, str]:
    return {k: str(v).strip() for k, v in (raw or {}).items() if k in ("note", "slot", "excerpt") and v
            and str(v).strip()}


async def create(session: AsyncSession, client: LLMClient, app: Application, kind: MessageKind, *,
                 inputs: Mapping[str, Any] | None = None, actor: str = "owner", sequence: int | None = None,
                 automatic: bool = False, now: datetime | None = None) -> OutboundMessage:
    """Draft a message (one model call, budgeted, then the checks). A budget refusal or model failure still
    returns the message (``budget_paused`` / ``failed``) so the owner can see it and draft again."""
    now = now or utcnow()
    given = _inputs(inputs)
    if kind in NEEDS_SLOT and not given.get("slot"):
        raise DraftError("give the interview slot exactly as you want it written", "refused", 422)
    ctx = await ctx_mod.load(session, app)
    values = await settings_service.values(session)
    thread_id, thread_ref = await ctx_mod.thread_ref(session, ctx)
    msg = OutboundMessage(
        application_id=app.id, kind=kind, status="draft", thread_id=thread_id, thread_ref=thread_ref,
        to=ctx_mod.default_recipients(ctx), cc=[], known_recipients=ctx.known, confirmed_recipients=[],
        subject=ctx_mod.reply_subject(ctx_mod.base_subject(ctx), str(values["followups.subject_prefix"])),
        paragraphs=[], context={**given, "model_questions": []}, questions=[], check_results=[],
        sequence=sequence, automatic=automatic, origin="generated", created_by=actor)
    session.add(msg)
    await session.flush()
    await generate(session, client, msg, ctx=ctx, values=values, now=now)
    await audit.record(session, actor=actor, action="message.drafted", subject_type="application", subject_id=app.id,
                       detail={"message_id": str(msg.id), "kind": kind, "status": msg.status, "automatic": automatic,
                               "sequence": sequence, "recipients": msg.to, "cost_micros": msg.cost_micros})
    return msg


async def generate(session: AsyncSession, client: LLMClient, msg: OutboundMessage, *,
                   ctx: MessageContext | None = None, values: Mapping[str, Any] | None = None,
                   now: datetime | None = None) -> OutboundMessage:
    """(Re)write the paragraphs of ``msg`` with the model and check them."""
    now = now or utcnow()
    app = await session.get(Application, msg.application_id)
    assert app is not None
    ctx = ctx or await ctx_mod.load(session, app)
    values = values or await settings_service.values(session)
    _, kit = await check_service.context(session, app)
    facts = select_facts(kit, ctx.job, limit=int(values["followups.max_facts"]))
    messages = build_messages(
        msg.kind, brief_for(msg.kind, values["followups.kind_briefs"]), kit, facts, ctx,
        inputs={k: str(v) for k, v in msg.context.items() if isinstance(v, str)},
        confirmed=await _confirmed_answers(session, ctx, values, now), signature=await _signature(session),
        max_paragraphs=int(values["followups.max_paragraphs"]),
        excerpt_chars=int(values["followups.context_max_chars"]))
    model = values["ai.model_tailor"]
    try:
        limit = await client.estimate_cost_micros(STAGE, messages, model=model, schema=MessageReply)
        reply, usage = await client.complete(STAGE, messages, MessageReply, max_cost_micros=limit, model=model)
    except BudgetExhausted as exc:
        msg.status, msg.error = "budget_paused", str(exc)[:2000]
        await session.flush()
        return msg
    except LLMError as exc:
        msg.status, msg.error = "failed", str(exc)[:2000]
        await session.flush()
        return msg
    msg.paragraphs = [SpecItem(text=p.text.strip(), fact_ids=list(p.fact_ids)) for p in reply.paragraphs
                      if p.text.strip()]
    msg.context = {**msg.context, "model_questions": [q.strip() for q in reply.questions_for_owner if q.strip()],
                   "facts_sent": [f.code for f in facts]}
    msg.status, msg.error, msg.origin, msg.model = "draft", None, "generated", usage.model
    _, cost = await checks.run(session, msg, ctx, kit, values, today=now.date(), client=client)
    msg.cost_micros = msg.cost_micros + usage.cost_micros + cost
    await session.flush()
    return msg
