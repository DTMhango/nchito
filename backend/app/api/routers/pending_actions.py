"""Pending actions: the "Needs you" list and the Action centre.

Wave 1 (tracking): list, detail, decisions grouped by shared blocker, dismiss, snooze, and answering
an unknown question into the answer bank. Resolving the other types (sign-in continue, approvals,
confirmations) is the apply stream's (wave 2): approvals, conflict choices and "continue" resolve here;
confirming a submission belongs to reconciliation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import owner_actions, resolvers, stages
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.models.applications import Application, PendingAction, PendingActionType, PendingStatus
from app.models.base import Origin, ReviewState
from app.models.kit import Answer, AnswerClass, AnswerScope
from app.models.search import Job
from app.schemas.json_types import AgentTaskState, AnswerPatterns

router = APIRouter(prefix="/api/pending-actions", tags=["pending_actions"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)

PendingType = Literal["approve", "sign_in", "create_account", "captcha", "unknown_question", "assessment",
                      "declaration", "confirm_submission", "review_import", "conflict_choice", "answer_review_due",
                      "follow_up"]
ScopeT = Literal["this_application", "this_employer", "this_country", "all_matching"]
StatusT = Literal["open", "resolved", "dismissed", "expired"]


class PendingActionOut(Timestamps):
    type: PendingType
    application_id: uuid.UUID | None
    agent_task_id: uuid.UUID | None
    group_key: str | None
    title: str
    detail: dict[str, Any]
    checkpoint: AgentTaskState | None
    deadline: datetime | None
    status: StatusT
    snoozed_until: datetime | None = None
    snoozed: bool = Field(default=False, description="Hidden until snoozed_until, unless its deadline is imminent")
    employer: str | None = None
    job_title: str | None = None
    resolution: dict[str, Any] | None = None


class DecisionGroup(BaseModel):
    """Shared blockers grouped on Today (18.4): 'signing in here unlocks two applications'."""

    group_key: str
    title: str
    consequence: str
    nearest_deadline: datetime | None
    actions: list[PendingActionOut]


class ResolveIn(BaseModel):
    resolution: Literal["continue", "answered", "approved", "confirmed", "dismissed", "chosen"]
    answer_value: str | None = None
    answer_scope: ScopeT | None = Field(
        default=None, description="Default from answers.routine_default_scope / material_default_scope")
    chosen_application_id: uuid.UUID | None = None
    chosen_job_id: uuid.UUID | None = Field(
        default=None, description="conflict_choice: the role chosen (one of the two in the action's detail)")
    note: str | None = None
    reference: str | None = Field(default=None, max_length=200,
                                  description="confirmed: the employer's reference number, kept as evidence")


class DismissIn(BaseModel):
    note: str | None = None


class SnoozeIn(BaseModel):
    until: datetime = Field(description="The action comes back at this time")


class AnswerIn(BaseModel):
    answer_value: str = Field(min_length=1)
    answer_scope: ScopeT | None = Field(
        default=None, description="Default from answers.routine_default_scope / material_default_scope")
    note: str | None = None


# ----- building the output --------------------------------------------------------------------------


async def _imminent_days(session: AsyncSession) -> int:
    return int(await settings_service.get_value(session, "tracking.imminent_deadline_days"))


def _is_snoozed(action: PendingAction, now: datetime, days: int) -> bool:
    return action.status == PendingStatus.open and stages.is_snoozed(
        action.snoozed_until, now, deadlines=[action.deadline], imminent_days=days)


async def _context(session: AsyncSession, actions: list[PendingAction]) -> dict[uuid.UUID, tuple[str, str]]:
    ids = {a.application_id for a in actions if a.application_id}
    if not ids:
        return {}
    rows = await session.execute(select(Application.id, Job.employer, Job.title)
                                 .join(Job, Job.id == Application.job_id).where(Application.id.in_(ids)))
    return {r[0]: (r[1], r[2]) for r in rows}


async def _outs(session: AsyncSession, actions: list[PendingAction]) -> list[PendingActionOut]:
    now = utcnow()
    days = await _imminent_days(session)
    ctx = await _context(session, actions)
    out = []
    for a in actions:
        employer, title = ctx.get(a.application_id, (None, None)) if a.application_id else (None, None)
        out.append(PendingActionOut(
            id=a.id, created_at=a.created_at, updated_at=a.updated_at, type=a.type.value,
            application_id=a.application_id, agent_task_id=a.agent_task_id, group_key=a.group_key, title=a.title,
            detail=a.detail, checkpoint=a.checkpoint, deadline=a.deadline, status=a.status.value,
            snoozed_until=a.snoozed_until, snoozed=_is_snoozed(a, now, days), employer=employer, job_title=title,
            resolution=a.resolution))
    return out


def _deadline_key(a: PendingAction) -> tuple[int, datetime]:
    return (0, a.deadline) if a.deadline else (1, datetime.max.replace(tzinfo=UTC))


def consequence_text(actions: list[PendingAction]) -> str:
    """One line on what a decision unlocks, built from the grouped actions."""
    n = len({a.application_id for a in actions if a.application_id}) or len(actions)
    kind = actions[0].type
    roles = f"{n} role{'s' if n != 1 else ''}"
    apps = f"{n} application{'s' if n != 1 else ''}"
    match kind:
        case PendingActionType.unknown_question:
            return f"One answer affects {roles}"
        case PendingActionType.sign_in | PendingActionType.create_account:
            return f"Signing in here unlocks {apps}"
        case PendingActionType.captcha:
            return f"Solving this unblocks {apps}"
        case PendingActionType.approve:
            return f"Approving lets {apps} go out"
        case PendingActionType.follow_up:
            return f"{n} follow-up{'s' if n != 1 else ''} due"
        case _:
            return f"{n} item{'s' if n != 1 else ''} waiting on you"


async def open_decisions(session: AsyncSession) -> list[DecisionGroup]:
    """Open, un-snoozed actions grouped by shared blocker, soonest deadline then biggest consequence first."""
    now = utcnow()
    days = await _imminent_days(session)
    rows = list(await session.scalars(select(PendingAction).where(PendingAction.status == PendingStatus.open)
                                      .order_by(PendingAction.created_at, PendingAction.id)))
    groups: dict[str, list[PendingAction]] = {}
    for a in rows:
        if _is_snoozed(a, now, days):
            continue
        groups.setdefault(a.group_key or f"action:{a.id}", []).append(a)
    ordered = sorted(groups.items(), key=lambda kv: (_deadline_key(min(kv[1], key=_deadline_key)), -len(kv[1]),
                                                     min(a.created_at for a in kv[1])))
    out: list[DecisionGroup] = []
    for key, actions in ordered:
        outs = await _outs(session, actions)
        nearest = min((a.deadline for a in actions if a.deadline), default=None)
        title = actions[0].title if len(actions) == 1 else _group_title(actions)
        out.append(DecisionGroup(group_key=key, title=title, consequence=consequence_text(actions),
                                 nearest_deadline=nearest, actions=outs))
    return out


def _group_title(actions: list[PendingAction]) -> str:
    return str(actions[0].detail.get("group_title") or actions[0].title)


# ----- endpoints ------------------------------------------------------------------------------------


@router.get("", response_model=Page[PendingActionOut], name="pending_actions_list")
async def list_pending(session: SessionDep, status: StatusT = "open", type: PendingType | None = None,
                       include_snoozed: bool = False, cursor: str | None = None,
                       limit: int = Query(default=100, ge=1, le=500)) -> Page[PendingActionOut]:
    """Soonest deadline first, then oldest. Snoozed actions stay hidden until they come back."""
    stmt = select(PendingAction).where(PendingAction.status == PendingStatus(status))
    if type:
        stmt = stmt.where(PendingAction.type == PendingActionType(type))
    rows = list(await session.scalars(stmt.order_by(PendingAction.deadline.asc().nulls_last(),
                                                    PendingAction.created_at, PendingAction.id)))
    if status == "open" and not include_snoozed:
        now, days = utcnow(), await _imminent_days(session)
        rows = [a for a in rows if not _is_snoozed(a, now, days)]
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    page = rows[offset:offset + limit]
    return Page[PendingActionOut](items=await _outs(session, page), total=len(rows),
                                  next_cursor=str(offset + limit) if offset + limit < len(rows) else None)


@router.get("/decisions", response_model=list[DecisionGroup], name="pending_actions_decisions")
async def decisions(session: SessionDep) -> list[DecisionGroup]:
    return await open_decisions(session)


async def _load(session: AsyncSession, action_id: uuid.UUID) -> PendingAction:
    action = await session.get(PendingAction, action_id)
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="pending action not found")
    return action


def _require_open(action: PendingAction) -> None:
    if action.status != PendingStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"already {action.status.value}")


@router.get("/{action_id}", response_model=PendingActionOut, name="pending_actions_get")
async def get_pending(action_id: uuid.UUID, session: SessionDep) -> PendingActionOut:
    return (await _outs(session, [await _load(session, action_id)]))[0]


async def _close(session: AsyncSession, action: PendingAction, new_status: PendingStatus, resolution: dict[str, Any],
                 actor: str) -> None:
    action.status = new_status
    action.resolved_at = utcnow()
    action.resolution = resolution
    await session.flush()
    await session.refresh(action)
    if action.application_id:
        await stages.add_event(session, action.application_id, "pending_action_closed", actor,
                               {"pending_action_id": str(action.id), "type": action.type.value,
                                "status": new_status.value, **{k: v for k, v in resolution.items() if k != "value"}})
    await publish(session, "pending_action.resolved", {"pending_action_id": str(action.id)})


async def _dismiss(session: AsyncSession, action: PendingAction, note: str | None, actor: str) -> None:
    _require_open(action)
    await _close(session, action, PendingStatus.dismissed, {"resolution": "dismissed", "note": note}, actor)
    await audit.record(session, actor=actor, action="pending_action.dismissed", subject_type="pending_action",
                       subject_id=action.id, detail={"type": action.type.value, "note": note})


@router.post("/{action_id}/dismiss", response_model=PendingActionOut, name="pending_actions_dismiss")
async def dismiss(action_id: uuid.UUID, body: DismissIn, principal: PrincipalDep,
                  session: SessionDep) -> PendingActionOut:
    action = await _load(session, action_id)
    await _dismiss(session, action, body.note, principal.actor)
    return (await _outs(session, [action]))[0]


@router.post("/{action_id}/snooze", response_model=PendingActionOut, name="pending_actions_snooze")
async def snooze(action_id: uuid.UUID, body: SnoozeIn, principal: PrincipalDep,
                 session: SessionDep) -> PendingActionOut:
    """Hide until ``until``; it returns on schedule, and sooner if its deadline becomes imminent."""
    action = await _load(session, action_id)
    _require_open(action)
    if body.until <= utcnow():
        raise HTTPException(422, detail="snooze until a time in the future")
    action.snoozed_until = body.until
    await session.flush()
    await session.refresh(action)
    await audit.record(session, actor=principal.actor, action="pending_action.snoozed", subject_type="pending_action",
                       subject_id=action.id, detail={"until": body.until.isoformat()})
    await publish(session, "pending_action.resolved", {"pending_action_id": str(action.id), "snoozed": True})
    return (await _outs(session, [action]))[0]


def _is_material(action: PendingAction) -> bool:
    return bool(action.detail.get("material"))


async def _save_answer(session: AsyncSession, action: PendingAction, value: str, scope: str | None,
                       actor: str) -> tuple[Answer, str]:
    question = str(action.detail.get("question") or action.title).strip()
    if scope is None:
        key = "answers.material_default_scope" if _is_material(action) else "answers.routine_default_scope"
        scope = str(await settings_service.get_value(session, key))
    app = await session.get(Application, action.application_id) if action.application_id else None
    job = await session.get(Job, app.job_id) if app else None
    scope_ref: str | None = None
    if scope == "this_application":
        if app is None:
            raise HTTPException(422, detail="this action has no application")
        scope_ref = str(app.id)
    elif scope == "this_employer":
        if job is None:
            raise HTTPException(422, detail="this action has no employer")
        scope_ref = job.canonical_employer
    elif scope == "this_country":
        country = job.location.country if job else None
        if not country:
            raise HTTPException(422, detail="this role has no known country")
        scope_ref = country
    answer = Answer(
        patterns=AnswerPatterns(canonical=question), value=value,
        value_type=str(action.detail.get("value_type", "text")),
        answer_class=AnswerClass.ask_first if _is_material(action) else AnswerClass.auto,
        material=_is_material(action), settled=True, scope=AnswerScope(scope), scope_ref=scope_ref,
        review_state=ReviewState.confirmed, origin=Origin.owner, confirmed_at=utcnow())
    session.add(answer)
    await session.flush()
    await audit.record(session, actor=actor, action="answer.saved_from_pending", subject_type="answer",
                       subject_id=answer.id, detail={"scope": scope, "scope_ref": scope_ref,
                                                     "pending_action_id": str(action.id), "material": answer.material})
    return answer, scope


async def _answer(session: AsyncSession, action: PendingAction, value: str, scope: str | None, note: str | None,
                  actor: str) -> list[PendingAction]:
    """Save the answer, close this action and every sibling in the group the answer's scope covers."""
    _require_open(action)
    if action.type != PendingActionType.unknown_question:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="only an unknown question can be answered here")
    answer, scope = await _save_answer(session, action, value, scope, actor)
    closed = [action]
    if action.group_key:
        siblings = list(await session.scalars(select(PendingAction).where(
            PendingAction.group_key == action.group_key, PendingAction.status == PendingStatus.open,
            PendingAction.id != action.id)))
        origin = await _scope_subject(session, action)
        for sib in siblings:
            if await _covered(session, scope, answer.scope_ref, origin, sib):
                closed.append(sib)
    for a in closed:
        await _close(session, a, PendingStatus.resolved,
                     {"resolution": "answered", "answer_id": str(answer.id), "scope": scope, "note": note,
                      "via": None if a is action else str(action.id)}, actor)
    return closed


async def _scope_subject(session: AsyncSession, action: PendingAction) -> Job | None:
    app = await session.get(Application, action.application_id) if action.application_id else None
    return await session.get(Job, app.job_id) if app else None


async def _covered(session: AsyncSession, scope: str, scope_ref: str | None, origin: Job | None,
                   sibling: PendingAction) -> bool:
    if scope == "all_matching":
        return True
    if scope == "this_application":
        return False
    other = await _scope_subject(session, sibling)
    if other is None:
        return False
    if scope == "this_employer":
        return other.canonical_employer.lower() == (scope_ref or "").lower()
    return (other.location.country or "").lower() == (scope_ref or "").lower()


@router.post("/{action_id}/answer", response_model=list[PendingActionOut], name="pending_actions_answer")
async def answer(action_id: uuid.UUID, body: AnswerIn, principal: PrincipalDep,
                 session: SessionDep) -> list[PendingActionOut]:
    """Answer an unknown form question: saves it to the answer bank with the chosen scope and settles every
    other open question in the group that the scope covers. Returns the actions that closed."""
    action = await _load(session, action_id)
    closed = await _answer(session, action, body.answer_value, body.answer_scope, body.note, principal.actor)
    return await _outs(session, closed)


@router.post("/{action_id}/resolve", response_model=PendingActionOut, name="pending_actions_resolve")
async def resolve(action_id: uuid.UUID, body: ResolveIn, principal: PrincipalDep,
                  session: SessionDep) -> PendingActionOut:
    """Settle a decision: ``dismissed``; ``answered`` (unknown question); ``approved`` (approve the packet the
    action names, if it is still current); ``chosen`` (conflict choice, with ``chosen_job_id``); ``continue``
    ('I've signed in, continue': the task returns to the same runner, 8.4). ``confirmed``
    (``confirm_submission``): the uncertain send went out; settles it as sent with the owner's evidence
    (``reference`` if given). ``approved`` on an action whose ``detail.kind`` is a registered proposal (for
    example ``mail_stage_proposal``) applies that proposal; 501 when its module is not in this build. To
    say an uncertain send did not go out, use the dispatch's ``reconcile`` (``not_sent``)."""
    action = await _load(session, action_id)
    kind = action.type
    try:
        if body.resolution == "dismissed":
            await _dismiss(session, action, body.note, principal.actor)
        elif body.resolution == "answered" and kind == PendingActionType.unknown_question:
            if not body.answer_value:
                raise HTTPException(422, detail="answer_value is required")
            await _answer(session, action, body.answer_value, body.answer_scope, body.note, principal.actor)
        elif body.resolution == "approved" and resolvers.handles(action):
            _require_open(action)
            await owner_actions.apply_proposal(session, action, actor=principal.actor)
        elif body.resolution == "approved" and kind == PendingActionType.approve:
            _require_open(action)
            await owner_actions.approve_from_action(session, action, actor=principal.actor)
        elif body.resolution == "chosen" and kind == PendingActionType.conflict_choice:
            _require_open(action)
            await owner_actions.choose(session, action, body.chosen_job_id, actor=principal.actor, note=body.note)
        elif body.resolution == "continue" and kind in owner_actions.CONTINUABLE:
            _require_open(action)
            await owner_actions.continue_task(session, action, actor=principal.actor, note=body.note)
        elif body.resolution == "confirmed" and kind == PendingActionType.confirm_submission:
            _require_open(action)
            await owner_actions.confirm_submission(session, action, actor=principal.actor,
                                                   reference=body.reference, note=body.note)
        else:
            raise HTTPException(422, detail=f"'{body.resolution}' does not resolve a {kind.value} action")
    except owner_actions.ResolveError as exc:
        raise HTTPException(exc.status, detail=exc.message) from exc
    except stages.IllegalTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
    await publish(session, "pending_action.resolved", {"pending_action_id": str(action.id)})
    await session.refresh(action)
    return (await _outs(session, [action]))[0]


__all__ = ["DecisionGroup", "PendingActionOut", "open_decisions"]
