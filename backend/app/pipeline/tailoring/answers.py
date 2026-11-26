"""Screening answers from the answer bank (DESIGN.md 5.4). Unknown is not yes.

Each question goes through :func:`app.kit.answers.match` with the application's context (application,
employer, country), so conditions and scopes are honoured. Only a ``value`` outcome carries an answer.
Anything else (no match, unconfirmed, due for review, material and not settled, owner-only, a condition
on missing context) becomes an ``unknown_question`` pending action for the owner, raised once per
question per application. A ``never`` answer is not answered.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import service as settings_service
from app.kit.answers import match, normalise
from app.kit.work_rights import to_record
from app.models.applications import Application, PendingAction, PendingActionType, PendingStatus
from app.models.kit import Answer
from app.models.search import Job
from app.schemas.json_types import DraftAnswer

MAX_QUESTION_CHARS = 500  # stored text bound; the question is data, never instructions


def context_for(app: Application, job: Job) -> dict[str, str]:
    ctx = {"application_id": str(app.id), "employer": job.canonical_employer}
    if job.location.country:
        ctx["country"] = job.location.country
    return ctx


def clean_questions(questions: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in questions:
        text = " ".join(q.split())[:MAX_QUESTION_CHARS]
        key = normalise(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


async def _pending_for(session: AsyncSession, app: Application, question: str, detail: dict[str, object]) -> str:
    key = f"question:{normalise(question)[:180]}"
    existing = await session.scalar(select(PendingAction).where(
        PendingAction.application_id == app.id, PendingAction.type == PendingActionType.unknown_question,
        PendingAction.group_key == key, PendingAction.status == PendingStatus.open))
    if existing is not None:
        return str(existing.id)
    action = PendingAction(type=PendingActionType.unknown_question, application_id=app.id, group_key=key,
                           title=f"Answer needed: {question[:250]}", detail={"question": question, **detail})
    session.add(action)
    await session.flush()
    return str(action.id)


async def draft_answers(session: AsyncSession, app: Application, job: Job, questions: Sequence[str], *,
                        today: date) -> list[DraftAnswer]:
    values = await settings_service.values(session)
    rows = list((await session.scalars(select(Answer))).all())
    records = [to_record(a) for a in rows]
    material = {a.id: bool(a.material) for a in rows}
    ctx = context_for(app, job)
    out: list[DraftAnswer] = []
    for q in clean_questions(questions):
        r = match(q, records, threshold=float(values["answers.match_similarity"]), context=ctx, today=today)
        pending = None
        if r.outcome == "ask_owner":
            pending = await _pending_for(session, app, q, {
                "reason": r.reason, "answer_id": str(r.answer_id) if r.answer_id else None,
                "proposed_value": r.value, "source": "tailoring"})
        out.append(DraftAnswer(
            question=q, outcome=r.outcome, value=r.value if r.outcome == "value" else None, select=r.select,
            answer_id=str(r.answer_id) if r.answer_id else None,
            material=material.get(r.answer_id, False) if r.answer_id else False, reason=r.reason,
            pending_action_id=pending))
    return out
