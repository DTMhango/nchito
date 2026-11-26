"""A runner's task history, read-only, for the owner's runner activity view (DESIGN.md 8.3, 18.1).

Built from what is already recorded: the task itself (its latest checkpoint, result and evidence uploads), the
pending actions its blockers raised, and the append-only audit (claims and every permit decision with its
reason). Nothing here changes state. Runner-supplied text (checkpoint, result detail) is page-derived data,
returned as data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import AgentTask, Application, PendingAction
from app.models.platform import AuditEvent
from app.models.search import Job
from app.schemas.json_types import AgentTaskState

PERMIT_ACTIONS = {"gateway.permit_granted": "granted", "gateway.permit_denied": "denied",
                  "gateway.permit_wait_for_owner": "wait_for_owner"}


class TaskBlockerOut(BaseModel):
    pending_action_id: uuid.UUID
    kind: str | None
    title: str
    status: str
    raised_at: datetime
    resolution: dict[str, Any] | None = None


class PermitDecisionOut(BaseModel):
    at: datetime
    decision: Literal["granted", "wait_for_owner", "denied"]
    reason: str | None = None
    changes: list[str] = Field(default_factory=list)
    permit_id: str | None = None


class TaskResultOut(BaseModel):
    outcome: str | None = None
    detail: str | None = None
    reference: str | None = None
    confirmation_text: str | None = None
    at: str | None = None


class RunnerTaskOut(BaseModel):
    task_id: uuid.UUID
    type: str
    status: str
    title: str = Field(description="The role (title at employer), or the site for a sweep")
    application_id: uuid.UUID | None
    claimed_at: datetime | None = Field(description="This runner's latest claim of the task")
    steps_used: int
    attempts: int
    dry_run: bool
    checkpoint: AgentTaskState | None
    blockers: list[TaskBlockerOut]
    permit_decisions: list[PermitDecisionOut]
    result: TaskResultOut | None
    evidence_refs: list[str] = Field(description="Screenshots and files the runner uploaded or cited "
                                                 "(``evidence:<task>/<id>``)")


async def task_title(session: AsyncSession, task: AgentTask) -> str:
    if task.application_id:
        row = (await session.execute(select(Job.title, Job.employer).join(Application, Application.job_id == Job.id)
                                     .where(Application.id == task.application_id))).first()
        if row is not None:
            return f"{row[0]} at {row[1]}"
    return str(task.payload.get("domain") or task.payload.get("posting_url") or task.type.value)


def _evidence(task: AgentTask) -> list[str]:
    refs = [f"evidence:{task.id}/{ref}" for ref in (task.payload.get("uploads") or {})]
    checkpoint_ref = task.checkpoint.screenshot_ref if task.checkpoint else None
    for cited in ((task.result or {}).get("screenshot_ref"), checkpoint_ref):
        if cited and cited not in refs:
            refs.append(str(cited))
    return refs


async def _blockers(session: AsyncSession, task: AgentTask) -> list[TaskBlockerOut]:
    rows = await session.scalars(select(PendingAction).where(or_(
        PendingAction.agent_task_id == task.id,
        PendingAction.detail["tasks"].contains([{"task_id": str(task.id)}]))).order_by(PendingAction.created_at))
    return [TaskBlockerOut(pending_action_id=a.id, kind=(a.detail or {}).get("kind"), title=a.title,
                           status=a.status.value, raised_at=a.created_at, resolution=a.resolution) for a in rows]


async def _permits(session: AsyncSession, task: AgentTask) -> list[PermitDecisionOut]:
    rows = await session.scalars(select(AuditEvent).where(
        AuditEvent.subject_type == "agent_task", AuditEvent.subject_id == str(task.id),
        AuditEvent.action.in_(tuple(PERMIT_ACTIONS))).order_by(AuditEvent.created_at, AuditEvent.id))
    out = []
    for e in rows:
        decision = PERMIT_ACTIONS[e.action]
        reason = e.detail.get("reason") or ("cleared: the runner may submit" if decision == "granted" else None)
        out.append(PermitDecisionOut(at=e.created_at, decision=decision, reason=reason,  # type: ignore[arg-type]
                                     changes=list(e.detail.get("changes") or []), permit_id=e.detail.get("permit_id")))
    return out


def _result(task: AgentTask) -> TaskResultOut | None:
    r = task.result
    if not r:
        return None
    return TaskResultOut(outcome=r.get("outcome"), detail=r.get("detail") or r.get("reason") or r.get("cancelled"),
                         reference=r.get("reference"), confirmation_text=r.get("confirmation_text"), at=r.get("at"))


async def runner_tasks(session: AsyncSession, token_id: uuid.UUID, *, offset: int,
                       limit: int) -> tuple[list[RunnerTaskOut], int]:
    """The tasks this runner claimed, most recent claim first. Returns (page, total)."""
    claimed = (select(AuditEvent.subject_id.label("task_id"), func.max(AuditEvent.created_at).label("at"))
               .where(AuditEvent.action == "gateway.task_claimed",
                      AuditEvent.detail["runner_id"].astext == str(token_id))
               .group_by(AuditEvent.subject_id).subquery())
    total = int(await session.scalar(select(func.count()).select_from(claimed)) or 0)
    rows = (await session.execute(select(claimed.c.task_id, claimed.c.at)
                                  .order_by(claimed.c.at.desc(), claimed.c.task_id).offset(offset).limit(limit))).all()
    out = []
    for raw, at in rows:
        task = await session.get(AgentTask, uuid.UUID(raw))
        if task is None:
            continue
        out.append(RunnerTaskOut(
            task_id=task.id, type=task.type.value, status=task.status.value, title=await task_title(session, task),
            application_id=task.application_id, claimed_at=at, steps_used=task.steps_used, attempts=task.attempts,
            dry_run=bool(task.payload.get("dry_run")), checkpoint=task.checkpoint,
            blockers=await _blockers(session, task), permit_decisions=await _permits(session, task),
            result=_result(task), evidence_refs=_evidence(task)))
    return out, total
