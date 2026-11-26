"""Practice mode: a question, the owner's draft answer, and model feedback against the approved facts.

One budgeted call per attempt. The owner's draft may hold pasted text, so it goes to the model as data.
A suggested better answer is a claim about the owner: it goes through the same truth checks and, if it
fails, is kept with its findings and shown flagged, never as fine. A budget refusal stores the attempt
``paused`` without feedback; asking again retries it.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.settings import service as settings_service
from app.llm.client import BudgetExhausted, LLMClient, LLMError, Message, TextPart
from app.llm.prompts import active_prompt
from app.llm.untrusted import data_block
from app.models.applications import Application, InterviewPack, InterviewPractice
from app.models.search import Job
from app.pipeline.checks import service as checks
from app.pipeline.checks.findings import summarise
from app.pipeline.interview import shapes as sh
from app.pipeline.interview import truth
from app.pipeline.interview.prompt import CLAIM_RULE, kit_parts, posting_text
from app.pipeline.interview.service import STAGE, InterviewError, build_context, load_kit

RULES = ("Give honest, specific feedback on the candidate's draft answer to the interview question: what works, "
         "what to improve, and, if useful, a better answer built only from the approved facts. Judge the draft "
         f"against the facts: point out any claim the facts do not support. {CLAIM_RULE}")


async def attempt(session: AsyncSession, client: LLMClient, pack: InterviewPack, *, question: str,
                  draft: str, category: str | None, actor: str,
                  row: InterviewPractice | None = None) -> InterviewPractice:
    values = await settings_service.values(session)
    limit_chars = int(values["interview.practice_answer_max_chars"])
    if len(draft) > limit_chars:
        raise InterviewError(f"the answer is longer than {limit_chars} characters", 422, "too_long")
    if not question.strip() or not draft.strip():
        raise InterviewError("a question and an answer are needed", 422, "empty")
    job = await session.get(Job, pack.job_id)
    assert job is not None
    app = await session.get(Application, pack.application_id) if pack.application_id else None
    kit = await load_kit(session, app)
    ctx, _ = await build_context(session, job, app, kit, values)
    prompt = await active_prompt(session, STAGE)
    messages = [
        Message(role="system", parts=[TextPart("\n\n".join([prompt.text if prompt else "", RULES]))]),
        Message(role="user", parts=[*kit_parts(ctx), data_block(posting_text(job), "job posting"),
                                    data_block(question, "interview question"),
                                    data_block(draft, "candidate draft answer")]),
    ]
    if row is None:
        row = InterviewPractice(pack_id=pack.id, question=question, category=category, draft_answer=draft,
                                status="paused")
        session.add(row)
    model = str(values["interview.model_practice"])
    try:
        limit = await client.estimate_cost_micros(STAGE, messages, model=model, schema=sh.PracticeFeedback)
        out, usage = await client.complete(STAGE, messages, sh.PracticeFeedback, max_cost_micros=limit, model=model)
    except BudgetExhausted as exc:
        row.status, row.error = "paused", str(exc)[:2000]
        await session.flush()
        return row
    except LLMError as exc:
        row.status, row.error = "failed", str(exc)[:2000]
        await session.flush()
        return row
    findings = []
    if out.suggested_answer is not None:
        cfg = await checks.check_settings(session, values)
        content = sh.WhyYou(points=[sh.TalkingPoint(point=out.suggested_answer)])
        findings = truth.check("why_you", content, kit, cfg, job_terms=checks.job_terms(job)).findings
    row.feedback = out.model_dump(mode="json")
    row.check_results = summarise(findings, truth.CHECKS_RUN) if out.suggested_answer is not None else []
    row.status, row.error = "done", None
    row.model, row.cost_micros = usage.model, row.cost_micros + usage.cost_micros
    await session.flush()
    await audit.record(session, actor=actor, action="interview.practised", subject_type="interview_pack",
                       subject_id=pack.id, detail={"practice_id": str(row.id), "cost_micros": usage.cost_micros,
                                                   "flagged": any(r.status == "block" for r in row.check_results)})
    return row
