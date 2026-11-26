"""Mock interview sessions: a turn-based chat driven by code, one budgeted model call per step.

Steps (``session.pending``): ``ask`` (the opening question), ``reply`` (after an answer or a skip: analyse the
answer, maybe probe, ask the next question, maybe give feedback) and ``final`` (feedback and scores). Code owns
the flow: how many questions, how many probes, when it ends. The model only fills in text, and its feedback goes
through the truth checks before it is stored.

Budget: before starting, an upper-bound estimate is shown and stored; the session may spend up to the estimate
times ``interview.mock.budget_headroom_pct`` (its own cap) and every call reserves its own estimate in the ledger
(through ``LLMClient``). A refusal (session cap or ledger) parks the session ``paused`` with the step still
pending; :func:`resume` runs that step again. Every turn has a unique ``step_key``, and a step writes only after
its call succeeds, so a resumed or repeated step never writes a turn twice.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm.client import BudgetExhausted, LLMClient, LLMError, Message
from app.models.applications import Application, InterviewMockSession, InterviewMockTurn, InterviewPack, InterviewRound
from app.models.search import Job
from app.pipeline.checks import service as checks
from app.pipeline.checks.kit import KitView
from app.pipeline.checks.service import CheckSettings
from app.pipeline.interview import shapes as sh
from app.pipeline.interview.mock import checks as mock_checks
from app.pipeline.interview.mock import prompt
from app.pipeline.interview.mock.shapes import MockAsk, MockFinal, MockReply
from app.pipeline.interview.prompt import PackContext
from app.pipeline.interview.service import InterviewError, build_context, current_versions, load_kit

STAGE = "interview"
MODES = tuple(prompt.MODES)
MODE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "behavioural": ("behavioural",), "technical": ("technical",), "role": ("role",),
    "mixed": ("behavioural", "technical", "role", "motivation"),
    "tough": ("behavioural", "technical", "role", "motivation"),
}
INTERVIEWER, OWNER, COACH = "interviewer", "owner", "coach"
ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class Options:
    mode: str
    length: int | None = None
    use_pack_questions: bool = True
    feedback_each: bool | None = None
    timer_seconds: int | None = None
    round_id: uuid.UUID | None = None


@dataclass
class Ctx:
    job: Job
    kit: KitView
    values: Mapping[str, Any]
    cfg: CheckSettings
    pack_ctx: PackContext
    round_info: prompt.RoundInfo | None


# ----- loading ---------------------------------------------------------------------------------------


async def _round(session: AsyncSession, pack: InterviewPack, round_id: uuid.UUID | None) -> InterviewRound | None:
    if round_id is None:
        return None
    row = await session.get(InterviewRound, round_id)
    if row is None or row.pack_id != pack.id:
        raise InterviewError("that round is not part of this pack", 404, "not_found")
    return row


def _round_info(row: InterviewRound | None) -> prompt.RoundInfo | None:
    if row is None:
        return None
    return prompt.RoundInfo(kind=row.kind or row.format, focus=list(row.focus or []), notes=row.notes,
                            interviewers=list(row.interviewers or []))


async def _context(session: AsyncSession, pack: InterviewPack, round_row: InterviewRound | None) -> Ctx:
    job = await session.get(Job, pack.job_id)
    assert job is not None
    app = await session.get(Application, pack.application_id) if pack.application_id else None
    values = await settings_service.values(session)
    kit = await load_kit(session, app)
    pack_ctx, _ = await build_context(session, job, app, kit, values)
    return Ctx(job=job, kit=kit, values=values, cfg=await checks.check_settings(session, values), pack_ctx=pack_ctx,
               round_info=_round_info(round_row))


async def turns_of(session: AsyncSession, session_id: uuid.UUID) -> list[InterviewMockTurn]:
    return list((await session.scalars(select(InterviewMockTurn).where(InterviewMockTurn.session_id == session_id)
                                       .order_by(InterviewMockTurn.seq))).all())


def transcript(turns: Sequence[InterviewMockTurn]) -> prompt.Transcript:
    lines: list[tuple[str, str, str]] = []
    for t in turns:
        if t.role == INTERVIEWER:
            lines.append((f"Q{t.question_index + 1}", "Interviewer", t.text))
        elif t.role == OWNER:
            lines.append((mock_checks.answer_code(t.seq), "Candidate",
                          t.text if t.kind == "answer" else "(skipped the question)"))
    return prompt.Transcript(lines)


def owner_answers(turns: Sequence[InterviewMockTurn]) -> dict[int, str]:
    return {t.seq: t.text for t in turns if t.role == OWNER and t.kind == "answer"}


# ----- plan and estimate -----------------------------------------------------------------------------


async def pack_questions(session: AsyncSession, pack: InterviewPack) -> list[sh.LikelyQuestion]:
    row = (await current_versions(session, pack.id)).get("questions")
    return sh.Questions.model_validate(row.content).items if row is not None else []


def make_plan(questions: Sequence[sh.LikelyQuestion], mode: str, length: int, use_pack: bool) -> list[dict[str, Any]]:
    """The main questions: the pack's likely questions for the mode first (round-robin across categories in a
    mixed mode), then questions the interviewer writes. Logistics questions belong to the pay sheet."""
    cats = MODE_CATEGORIES[mode]
    by_cat = {c: [q for q in questions if q.category == c] for c in cats} if use_pack else {c: [] for c in cats}
    chosen: list[dict[str, Any]] = []
    while len(chosen) < length and any(by_cat.values()):
        for c in cats:
            if by_cat[c] and len(chosen) < length:
                q = by_cat[c].pop(0)
                chosen.append({"question": q.question, "category": q.category, "source": "pack"})
    i = 0
    while len(chosen) < length:
        chosen.append({"question": None, "category": cats[i % len(cats)], "source": "model"})
        i += 1
    return chosen


def _model(values: Mapping[str, Any], which: str) -> str:
    return str(values[f"interview.mock.model_{which}"])


async def estimate(session: AsyncSession, client: LLMClient, pack: InterviewPack, opts: Options) -> dict[str, int]:
    """Upper-bound cost: the opening question (when the interviewer writes it), one reply per answer and probe at
    the longest answer, and the final feedback over the longest transcript."""
    round_row = await _round(session, pack, opts.round_id)
    ctx = await _context(session, pack, round_row)
    length = opts.length or int(ctx.values["interview.mock.default_length"])
    probes = int(ctx.values["interview.mock.max_probes"])
    longest = "x" * int(ctx.values["interview.mock.answer_max_chars"])
    plan = make_plan(await pack_questions(session, pack), opts.mode, length, opts.use_pack_questions)
    one = prompt.Transcript([("Q1", "Interviewer", "?" * 300), ("A2", "Candidate", longest)])
    full = prompt.Transcript([line for i in range(length * (1 + probes))
                              for line in (("Q", "Interviewer", "?" * 300), (f"A{i}", "Candidate", longest))])

    async def cost(t: prompt.Transcript, task: str, schema: type[BaseModel], which: str) -> int:
        messages = prompt.build(ctx.pack_ctx, ctx.values, mode=opts.mode, round_info=ctx.round_info, transcript=t,
                                task=task)
        return await client.estimate_cost_micros(STAGE, messages, model=_model(ctx.values, which), schema=schema)

    ask = await cost(prompt.Transcript(), prompt.ask_task(None, []), MockAsk, "interviewer") \
        if plan and plan[0]["source"] == "model" else 0
    reply = await cost(one, prompt.reply_task(ref="A2", skipped=False, probe_allowed=True, next_needed=True,
                                              next_category=None, feedback=True), MockReply, "interviewer")
    final = await cost(full, prompt.final_task(list(range(length))), MockFinal, "feedback")
    return {"ask": ask, "replies": reply * length * (1 + probes), "final": final}


# ----- turns and calls -------------------------------------------------------------------------------


async def _add_turn(session: AsyncSession, s: InterviewMockSession, *, key: str, role: str, kind: str, text: str,
                    category: str | None = None, **extra: Any) -> InterviewMockTurn:
    """Get-or-add by ``step_key``: a step run twice finds the turn it wrote and writes nothing."""
    existing = await session.scalar(select(InterviewMockTurn).where(InterviewMockTurn.session_id == s.id,
                                                                    InterviewMockTurn.step_key == key))
    if existing is not None:
        return existing
    seq = len(await turns_of(session, s.id)) + 1
    row = InterviewMockTurn(session_id=s.id, seq=seq, step_key=key, role=role, kind=kind, text=text,
                            question_index=s.question_index, category=category, claims=[], fact_ids=[], **extra)
    session.add(row)
    await session.flush()
    return row


async def _call(client: LLMClient, s: InterviewMockSession, ctx: Ctx, messages: list[Message],
                schema: type[ModelT], which: str) -> tuple[ModelT, str, int]:
    model = _model(ctx.values, which)
    est = await client.estimate_cost_micros(STAGE, messages, model=model, schema=schema)
    if s.budget_micros is not None and s.cost_micros + est > s.budget_micros:
        raise BudgetExhausted("session", needed_micros=est, available_micros=max(0, s.budget_micros - s.cost_micros),
                              currency=str(ctx.values["budget.currency"]))
    out, usage = await client.complete(STAGE, messages, schema, max_cost_micros=est, model=model)
    s.cost_micros += usage.cost_micros
    return out, usage.model, usage.cost_micros


def _messages(ctx: Ctx, s: InterviewMockSession, turns: Sequence[InterviewMockTurn], task: str) -> list[Message]:
    return prompt.build(ctx.pack_ctx, ctx.values, mode=s.mode, round_info=ctx.round_info,
                        transcript=transcript(turns), task=task)


def _dimensions(values: Mapping[str, Any]) -> list[str]:
    return [k for k, _ in prompt.rubric_lines(values)]


def _checked(fb: Any, ctx: Ctx, turns: Sequence[InterviewMockTurn]) -> dict[str, Any]:
    return mock_checks.checked_feedback(fb, ctx.kit, owner_answers(turns), ctx.cfg,
                                        job_terms=checks.job_terms(ctx.job), dimensions=_dimensions(ctx.values),
                                        top=int(ctx.values["interview.mock.score_max"]))


# ----- steps -----------------------------------------------------------------------------------------


async def _step_ask(session: AsyncSession, client: LLMClient, s: InterviewMockSession, ctx: Ctx) -> None:
    item = s.plan[s.question_index]
    model, cost, category = None, 0, item.get("category")
    text = item.get("question")
    if not text:
        turns = await turns_of(session, s.id)
        out, model, cost = await _call(client, s, ctx, _messages(ctx, s, turns, prompt.ask_task(category, [])),
                                       MockAsk, "interviewer")
        text, category = out.question, out.category
    await _add_turn(session, s, key=f"q{s.question_index}", role=INTERVIEWER, kind="question", text=text,
                    category=category, model=model, cost_micros=cost)
    s.pending = None


async def _step_reply(session: AsyncSession, client: LLMClient, s: InterviewMockSession, ctx: Ctx) -> None:
    pending = dict(s.pending or {})
    turns = await turns_of(session, s.id)
    owner = next(t for t in turns if t.step_key == pending["answer_key"])
    qi, probes = int(pending["qi"]), int(pending["probes"])
    skipped = owner.kind == "skip"
    probe_allowed = not skipped and probes < int(ctx.values["interview.mock.max_probes"])
    last = qi + 1 >= s.length
    next_item = None if last else s.plan[qi + 1]
    next_needed = next_item is not None and not next_item.get("question")
    out, model, cost = MockReply(), None, 0
    if not skipped or next_needed:
        task = prompt.reply_task(ref=mock_checks.answer_code(owner.seq), skipped=skipped, probe_allowed=probe_allowed,
                                 next_needed=next_needed, feedback=s.feedback_each,
                                 next_category=next_item.get("category") if next_item else None)
        out, model, cost = await _call(client, s, ctx, _messages(ctx, s, turns, task), MockReply, "interviewer")
    probe = out.probe.strip() if probe_allowed and out.probe and out.probe.strip() else None
    next_text = None
    if probe is None and next_item is not None:
        next_text = next_item.get("question") or (out.next_question or "").strip() or None
        if next_text is None:
            raise LLMError("the interviewer did not write the next question")
    # The call succeeded: write everything this step owns (get-or-add, so a rerun writes nothing twice).
    if not skipped:
        owner.fact_ids = mock_checks.usable_codes(out.analysis.fact_ids, ctx.kit)
        if not owner.claims:
            owner.claims = mock_checks.unverified_claims(owner.text, out.analysis.unstated, ctx.kit)
        if s.feedback_each and out.feedback is not None:
            await _add_turn(session, s, key=f"f{qi}.{probes}", role=COACH, kind="feedback", text="",
                            category=owner.category, feedback=_checked(out.feedback, ctx, turns), model=model)
    if probe is not None:
        s.probes = probes + 1
        await _add_turn(session, s, key=f"p{qi}.{probes + 1}", role=INTERVIEWER, kind="probe", text=probe,
                        category=owner.category, model=model, cost_micros=cost)
        s.pending = None
    elif next_item is not None:
        s.question_index, s.probes = qi + 1, 0
        await _add_turn(session, s, key=f"q{qi + 1}", role=INTERVIEWER, kind="question", text=next_text or "",
                        category=next_item.get("category") or out.next_category, model=model, cost_micros=cost)
        s.pending = None
    else:
        s.pending = {"step": "final"}
        await _step_final(session, client, s, ctx)


async def _step_final(session: AsyncSession, client: LLMClient, s: InterviewMockSession, ctx: Ctx) -> None:
    turns = await turns_of(session, s.id)
    answered = sorted({t.question_index for t in turns if t.role == OWNER and t.kind == "answer"})
    feedback: dict[str, Any] = {"summary": "", "answers": [], "overall": {}}
    if answered:
        out, _, _ = await _call(client, s, ctx, _messages(ctx, s, turns, prompt.final_task(answered)), MockFinal,
                                "feedback")
        questions = {t.question_index: t for t in turns if t.role == INTERVIEWER and t.kind == "question"}
        refs = {qi: [mock_checks.answer_code(t.seq) for t in turns
                     if t.role == OWNER and t.kind == "answer" and t.question_index == qi] for qi in answered}
        seen: set[int] = set()
        for item in out.answers:
            if item.question_index not in refs or item.question_index in seen:
                continue  # feedback for a question nobody answered, or a duplicate, is dropped
            seen.add(item.question_index)
            q = questions.get(item.question_index)
            feedback["answers"].append({"question_index": item.question_index, "question": q.text if q else "",
                                        "category": q.category if q else None, "answer_refs": refs[item.question_index],
                                        **_checked(item.feedback, ctx, turns)})
        dims, top = _dimensions(ctx.values), int(ctx.values["interview.mock.score_max"])
        overall = mock_checks.clamp_scores(out.overall, dims, top)
        if not overall:
            overall = average_scores([a["scores"] for a in feedback["answers"]])
        feedback.update(summary=out.summary, overall=overall)
    s.feedback = feedback
    s.scores = dict(feedback["overall"])
    s.status, s.pending, s.finished_at, s.error = "done", None, utcnow(), None


def average_scores(rows: Sequence[Mapping[str, int]]) -> dict[str, int]:
    sums: dict[str, list[int]] = {}
    for r in rows:
        for k, v in r.items():
            sums.setdefault(k, []).append(int(v))
    return {k: round(sum(v) / len(v)) for k, v in sums.items()}


Step = Callable[[AsyncSession, LLMClient, InterviewMockSession, Ctx], Awaitable[None]]
STEPS: dict[str, Step] = {"ask": _step_ask, "reply": _step_reply, "final": _step_final}


async def _run(session: AsyncSession, client: LLMClient, s: InterviewMockSession, pack: InterviewPack) -> None:
    if not s.pending:
        return
    ctx = await _context(session, pack, await _round(session, pack, s.round_id))
    s.status, s.error = "active", None
    try:
        await STEPS[str(s.pending["step"])](session, client, s, ctx)
    except BudgetExhausted as exc:
        s.status, s.error = "paused", str(exc)[:2000]
    except LLMError as exc:
        s.status, s.error = "failed", str(exc)[:2000]
    await session.flush()


# ----- owner actions ---------------------------------------------------------------------------------


async def start(session: AsyncSession, client: LLMClient, pack: InterviewPack, opts: Options, *,
                actor: str) -> InterviewMockSession:
    values = await settings_service.values(session)
    if opts.mode not in MODES:
        raise InterviewError(f"unknown mode {opts.mode!r}", 422, "invalid")
    length = opts.length or int(values["interview.mock.default_length"])
    if length > int(values["interview.mock.max_length"]):
        raise InterviewError(f"at most {values['interview.mock.max_length']} questions", 422, "too_long")
    await _round(session, pack, opts.round_id)
    per = await estimate(session, client, pack, Options(**{**opts.__dict__, "length": length}))
    total = sum(per.values())
    s = InterviewMockSession(
        pack_id=pack.id, round_id=opts.round_id, mode=opts.mode, length=length,
        use_pack_questions=opts.use_pack_questions,
        feedback_each=bool(values["interview.mock.feedback_each_default"]) if opts.feedback_each is None
        else opts.feedback_each, timer_seconds=opts.timer_seconds, status="active",
        plan=make_plan(await pack_questions(session, pack), opts.mode, length, opts.use_pack_questions),
        pending={"step": "ask"}, question_index=0, probes=0, estimate_micros=total,
        budget_micros=total * int(values["interview.mock.budget_headroom_pct"]) // 100, cost_micros=0, scores={},
        created_by=actor)
    session.add(s)
    await session.flush()
    await audit.record(session, actor=actor, action="interview.mock_started", subject_type="interview_pack",
                       subject_id=pack.id, detail={"session_id": str(s.id), "mode": s.mode, "length": length,
                                                   "round_id": str(opts.round_id) if opts.round_id else None,
                                                   "estimate_micros": total})
    await _run(session, client, s, pack)
    return s


async def _pack_of(session: AsyncSession, s: InterviewMockSession) -> InterviewPack:
    pack = await session.get(InterviewPack, s.pack_id)
    assert pack is not None
    return pack


async def answer(session: AsyncSession, client: LLMClient, s: InterviewMockSession, *, text: str, skip: bool,
                 turn_key: str | None, actor: str) -> InterviewMockSession:
    """The owner's answer (or a skip) to the open question. ``turn_key`` (the ``expects`` the client saw) makes a
    repeated submit harmless: the turn already exists, nothing is written or asked again."""
    expected = f"a{s.question_index}.{s.probes}"
    if (turn_key is not None and turn_key != expected) or s.status != "active" or s.pending:
        if turn_key is not None and await session.scalar(select(InterviewMockTurn.id).where(
                InterviewMockTurn.session_id == s.id, InterviewMockTurn.step_key == turn_key)):
            return s
        raise InterviewError("this session is not waiting for an answer", 409, "not_your_turn")
    values = await settings_service.values(session)
    limit = int(values["interview.mock.answer_max_chars"])
    if not skip and not text.strip():
        raise InterviewError("an answer is needed (or skip the question)", 422, "empty")
    if len(text) > limit:
        raise InterviewError(f"the answer is longer than {limit} characters", 422, "too_long")
    question = next((t for t in reversed(await turns_of(session, s.id)) if t.role == INTERVIEWER), None)
    await _add_turn(session, s, key=expected, role=OWNER, kind="skip" if skip else "answer",
                    text="" if skip else text, category=question.category if question else None)
    s.pending = {"step": "reply", "qi": s.question_index, "probes": s.probes, "answer_key": expected}
    await audit.record(session, actor=actor, action="interview.mock_answered", subject_type="interview_mock_session",
                       subject_id=s.id, detail={"turn": expected, "skipped": skip})
    await _run(session, client, s, await _pack_of(session, s))
    return s


async def finish(session: AsyncSession, client: LLMClient, s: InterviewMockSession, *,
                 actor: str) -> InterviewMockSession:
    """"I'm done": end now and get the final feedback on what was answered."""
    if s.status == "done":
        return s
    s.pending = {"step": "final"}
    await audit.record(session, actor=actor, action="interview.mock_finished", subject_type="interview_mock_session",
                       subject_id=s.id, detail={"early": True})
    await _run(session, client, s, await _pack_of(session, s))
    return s


async def resume(session: AsyncSession, client: LLMClient, s: InterviewMockSession, *, budget_micros: int | None,
                 actor: str) -> InterviewMockSession:
    """Run the pending step again (after a budget pause or a failure). ``budget_micros`` raises the session cap."""
    if budget_micros is not None:
        if s.budget_micros is not None and budget_micros < s.budget_micros:
            raise InterviewError("the session budget can only be raised", 422, "invalid")
        s.budget_micros = budget_micros
    if s.status not in ("paused", "failed") or not s.pending:
        return s
    await audit.record(session, actor=actor, action="interview.mock_resumed", subject_type="interview_mock_session",
                       subject_id=s.id, detail={"step": s.pending.get("step"), "budget_micros": s.budget_micros})
    await _run(session, client, s, await _pack_of(session, s))
    return s


async def delete(session: AsyncSession, s: InterviewMockSession, *, actor: str) -> None:
    await audit.record(session, actor=actor, action="interview.mock_deleted", subject_type="interview_pack",
                       subject_id=s.pack_id, detail={"session_id": str(s.id)})
    await session.delete(s)
    await session.flush()
