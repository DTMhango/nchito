"""``find_answer``: one form question, answered from the approved packet or the answer bank (DESIGN.md 5.4,
8.3). Invariants, never settings:

- **Never invents.** A value comes only from the approved packet or a stored answer whose scope,
  conditions, review date and class allow it (``app.kit.answers.match``).
- ``never`` answers are ``do_not_answer`` (with the forced option where the form offers it), and so are
  ``owner_only`` answers: the runner leaves them for the owner, who is asked through a pending action.
- Anything else the bank cannot settle is ``ask_owner`` and raises one ``unknown_question`` pending action
  per question and application.
- The question text comes from a web page: it is stored as data, bounded, and never followed.
- A bank answer that is not in the approved packet is still a packet change: the permit asks the owner.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.gateway.common import (
    GatewayError,
    approved_packet,
    clip,
    own_task,
    require_active,
    require_scope,
    setting,
    task_application,
)
from app.gateway.tools import FindAnswerIn, FindAnswerOut
from app.kit.answers import match, normalise, similarity
from app.kit.work_rights import to_record
from app.models.applications import (
    AgentTask,
    AgentTaskType,
    Application,
    PendingAction,
    PendingActionType,
    PendingStatus,
)
from app.models.kit import Answer, AnswerClass
from app.models.platform import ApiToken
from app.pipeline.tailoring.answers import MAX_QUESTION_CHARS, context_for


async def raise_question(session: AsyncSession, app: Application, task: AgentTask, question: str,
                         detail: dict[str, object]) -> uuid.UUID:
    key = f"question:{normalise(question)[:180]}"
    existing = await session.scalar(select(PendingAction).where(
        PendingAction.application_id == app.id, PendingAction.type == PendingActionType.unknown_question,
        PendingAction.group_key == key, PendingAction.status == PendingStatus.open))
    if existing is not None:
        return existing.id
    action = PendingAction(type=PendingActionType.unknown_question, application_id=app.id, agent_task_id=task.id,
                           group_key=key, title=f"Answer needed: {question[:250]}",
                           detail={"question": question, "source": "gateway", **detail},
                           checkpoint=task.checkpoint)
    session.add(action)
    await session.flush()
    return action.id


async def find_answer(session: AsyncSession, token: ApiToken, body: FindAnswerIn, *, at: datetime) -> FindAnswerOut:
    require_active(token)
    require_scope(token, "gateway:packets")
    task = await own_task(session, token, body.task_id, at=at, types=(AgentTaskType.apply,))
    app, job = await task_application(session, task)
    question = " ".join((clip(body.question, MAX_QUESTION_CHARS) or "").split())
    if not question:
        raise GatewayError("empty_question", "the question is empty")
    options = [o[:200] for o in (body.options or [])[:100]] or None
    threshold = float(await setting(session, "answers.match_similarity"))
    rows = list((await session.scalars(select(Answer))).all())
    result = match(question, [to_record(a) for a in rows], threshold=threshold, context=context_for(app, job),
                   options=options, today=at.date())
    by_id = {a.id: a for a in rows}
    found = by_id.get(result.answer_id) if result.answer_id else None
    out: FindAnswerOut
    if result.outcome == "do_not_answer":
        out = FindAnswerOut(outcome="do_not_answer", select=result.select)
    elif found is not None and found.answer_class == AnswerClass.owner_only:
        await raise_question(session, app, task, question, {"reason": "the owner answers this personally",
                                                            "answer_id": str(found.id)})
        out = FindAnswerOut(outcome="do_not_answer")
    else:
        packet = await approved_packet(session, app)
        in_packet = None
        for a in packet.contents.answers if packet else []:
            if normalise(a.question) == normalise(question) or similarity(a.question, question) >= threshold:
                in_packet = a
                break
        if in_packet is not None:
            out = FindAnswerOut(outcome="value", value=in_packet.value)
        elif result.outcome == "value":
            out = FindAnswerOut(outcome="value", value=result.value)
        else:
            pending = await raise_question(session, app, task, question, {
                "reason": result.reason, "answer_id": str(result.answer_id) if result.answer_id else None,
                "options": options})
            out = FindAnswerOut(outcome="ask_owner")
            task.payload = {**task.payload, "asked": [*(task.payload.get("asked") or []), str(pending)]}
    await audit.record(session, actor=f"runner:{token.name}", action="gateway.answer_looked_up",
                       subject_type="agent_task", subject_id=task.id,
                       detail={"question": question, "outcome": out.outcome,
                               "answer_id": str(result.answer_id) if result.answer_id else None})
    return out
