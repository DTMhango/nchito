"""Which open applications still use an answer (DESIGN.md 5.4: changing an answer lists the pending
applications still using the old value).

An application uses an answer while it can still be sent with it: it is before submission
(shortlisted, tailoring, ready, applying) and either its current packet carries the answer, or an open
pending action refers to it. After submission the sent answers are a fixed snapshot.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application, ApplicationPacket, PendingAction, PendingStatus, Stage
from app.models.search import Job

PRE_SUBMIT = (Stage.shortlisted, Stage.tailoring, Stage.ready, Stage.applying)


@dataclass(frozen=True)
class AnswerUse:
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    employer: str
    stage: str
    via: Literal["packet", "pending_action"]


def _refs(detail: dict[str, Any]) -> set[str]:
    ids = {str(detail["answer_id"])} if detail.get("answer_id") else set()
    ids |= {str(i) for i in detail.get("answer_ids") or []}
    return ids


async def uses_of(session: AsyncSession, answer_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[AnswerUse]]:
    wanted = {str(i): i for i in answer_ids}
    out: dict[uuid.UUID, list[AnswerUse]] = defaultdict(list)
    if not wanted:
        return out
    apps = {a.id: (a, j) for a, j in (await session.execute(
        select(Application, Job).join(Job, Job.id == Application.job_id)
        .where(Application.stage.in_(PRE_SUBMIT)))).all()}
    if not apps:
        return out
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()

    def add(answer_key: str, app_id: uuid.UUID, via: Literal["packet", "pending_action"]) -> None:
        answer_id = wanted[answer_key]
        if (answer_id, app_id) in seen:
            return
        seen.add((answer_id, app_id))
        app, job = apps[app_id]
        out[answer_id].append(AnswerUse(app.id, job.id, job.title, job.employer, app.stage.value, via))

    # The newest live packet of each application.
    latest: dict[uuid.UUID, ApplicationPacket] = {}
    for packet in (await session.scalars(
            select(ApplicationPacket).where(ApplicationPacket.application_id.in_(list(apps)),
                                            ApplicationPacket.invalidated_at.is_(None))
            .order_by(ApplicationPacket.version))).all():
        latest[packet.application_id] = packet
    for app_id, packet in latest.items():
        for answer in packet.contents.answers:
            if answer.answer_id in wanted:
                add(answer.answer_id, app_id, "packet")
    for action in (await session.scalars(
            select(PendingAction).where(PendingAction.status == PendingStatus.open,
                                        PendingAction.application_id.in_(list(apps))))).all():
        for ref in _refs(action.detail or {}) & wanted.keys():
            if action.application_id is not None:
                add(ref, action.application_id, "pending_action")
    return out


async def counts(session: AsyncSession, answer_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    return {k: len(v) for k, v in (await uses_of(session, answer_ids)).items()}
