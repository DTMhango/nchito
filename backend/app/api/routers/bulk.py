"""Bulk actions on Matches and Applications selections (DESIGN 10.3, wave 4).

Flow: ``POST /bulk/preview`` resolves the selection (ids, or "everything matching this view", resolved
here on the server) and reports what each item would do, grouped by reason; nothing changes.
``POST /bulk/{id}/run`` confirms the previewed count and queues a background run that reports progress
(SSE ``bulk.progress`` and ``GET /bulk/{id}``) and per-item results; running it again finishes what failed
and repeats nothing. ``POST /bulk/{id}/undo`` reverses tags, snooze, skip and archive inside the window.
Every item goes through the single-item service function (``app.pipeline.bulk``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.api.common import ApiModel, Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.api.routers.applications import _filters as application_filters
from app.core.clock import utcnow
from app.core.conditions import ConditionSet, Group, ValueFilter, evaluate
from app.core.settings import service as settings_service
from app.models.applications import Application
from app.models.bulk import BulkItem, BulkOperation
from app.models.search import Job, SavedView
from app.pipeline import bulk, filters
from app.schemas.json_types import BulkActionName, BulkItemOutcome, BulkStatus, BulkSubject, BulkVerdict

router = APIRouter(prefix="/api/bulk", tags=["bulk"], dependencies=[RequireOwner])


class ViewSelectionIn(BaseModel):
    """Everything matching a view, resolved on the server (the same filter as the list)."""

    view_id: uuid.UUID | None = None
    conditions: str | None = Field(default=None, description="JSON ConditionSet, as in the Matches list")
    q: str | None = None
    triage: str | None = Field(default=None, description="Matches only: new, shortlisted, ...")
    stage: str | None = Field(default=None, description="Applications only")
    campaign_id: uuid.UUID | None = None
    channel: str | None = Field(default=None, description="Applications only")
    pinned: bool | None = None


class SelectionIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, description="The ticked rows")
    view: ViewSelectionIn | None = Field(default=None, description="Or everything matching this view")


class ParamsIn(BaseModel):
    tag: str | None = None
    until: datetime | None = Field(default=None, description="Snooze until")
    reason: str | None = Field(default=None, description="Required to skip")
    stage: str | None = Field(default=None, description="Target stage of move_stage")
    campaign_id: uuid.UUID | None = None
    note: str | None = None


class PreviewIn(BaseModel):
    subject: BulkSubject
    action: BulkActionName
    params: ParamsIn = Field(default_factory=ParamsIn)
    selection: SelectionIn


class SampleOut(BaseModel):
    id: uuid.UUID
    label: str
    reason: str


class ReasonGroupOut(BaseModel):
    code: str
    title: str
    count: int
    samples: list[SampleOut]


class PreviewOut(BaseModel):
    operation_id: uuid.UUID
    subject: BulkSubject
    action: BulkActionName
    selected: int = Field(description="Confirm this count to run")
    will_change: int
    unchanged: ReasonGroupOut | None = Field(default=None, description="Already as asked")
    refused: list[ReasonGroupOut] = Field(description="Cannot be changed, grouped by reason")
    refused_total: int
    reversible: bool


class RunIn(BaseModel):
    confirm_count: int | None = Field(default=None, description="Must equal the previewed count")


class OperationOut(Timestamps):
    subject: BulkSubject
    action: BulkActionName
    status: BulkStatus
    selected: int
    params: dict[str, Any]
    counts: dict[str, int] = Field(description="Items per outcome")
    done: int = Field(description="Items finished (any outcome but pending)")
    created_by: str
    started_at: datetime | None
    finished_at: datetime | None
    undo_until: datetime | None
    can_undo: bool
    error: str | None = None


class ItemOut(ApiModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    label: str
    planned: BulkVerdict
    planned_code: str | None
    planned_reason: str | None
    outcome: BulkItemOutcome
    code: str | None
    reason: str | None


class BulkOptionsOut(BaseModel):
    max_selection: int
    undo_window_minutes: int
    approve_reviewed_enabled: bool
    reversible: list[BulkActionName]
    actions: dict[BulkSubject, list[BulkActionName]]


BulkEnqueue = Callable[[uuid.UUID], Awaitable[None]]


async def get_bulk_enqueue() -> BulkEnqueue:
    """Defers the run to the worker (tests replace this dependency)."""

    async def enqueue(operation_id: uuid.UUID) -> None:
        from app.pipeline.bulk_tasks import enqueue as defer
        from app.worker.queue import queue_app

        async with queue_app.open_async():
            await defer(operation_id)

    return enqueue


def _http(exc: bulk.BulkError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "reason": str(exc)})


def _conditions(raw: str | None) -> ConditionSet | None:
    if not raw:
        return None
    try:
        return ConditionSet.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors(include_url=False)) from exc


async def resolve_ids(session: SessionDep, subject: str, selection: SelectionIn, limit: int) -> list[uuid.UUID]:
    """The ids a selection stands for. ``limit + 1`` at most are returned, so the caller can refuse a
    selection over the cap without resolving all of it."""
    if selection.ids is not None:
        if selection.view is not None:
            raise bulk.BulkError("choose rows or a view, not both", 422, "bad_selection")
        return list(dict.fromkeys(selection.ids))
    view = selection.view
    if view is None:
        raise bulk.BulkError("nothing is selected", 422, "empty_selection")
    body = None
    if view.view_id:
        saved = await session.get(SavedView, view.view_id)
        if saved is None:
            raise bulk.BulkError("view not found", 404, "not_found")
        body = saved.body
    explicit = _conditions(view.conditions)
    if subject == "jobs":
        triage = ConditionSet(root=Group(conditions=[ValueFilter(
            facet="triage", include=[view.triage])])) if view.triage else None
        conditions = filters.combine(body.conditions if body else None, explicit, triage, text=view.q)
        records = await filters.load_records(session, now=utcnow())
        hits = [r["id"] for _, r in records if evaluate(conditions, r)]
        return [uuid.UUID(str(i)) for i in hits[: limit + 1]]
    stmt = select(Application.id, Application.job_id).join(Job, Job.id == Application.job_id).where(
        *application_filters(view.stage, view.campaign_id, view.channel, view.q, view.pinned)).order_by(
        Application.created_at)
    rows = (await session.execute(stmt)).all()
    if body is not None or explicit is not None:
        conditions = filters.combine(body.conditions if body else None, explicit)
        records = await filters.load_records(session, now=utcnow(), job_ids=[j for _, j in rows])
        keep = {str(r["id"]) for _, r in records if evaluate(conditions, r)}
        rows = [(a, j) for a, j in rows if str(j) in keep]
    return [a for a, _ in rows][: limit + 1]


async def _operation(session: SessionDep, operation_id: uuid.UUID) -> BulkOperation:
    op = await session.get(BulkOperation, operation_id)
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="operation not found")
    return op


async def _out(session: SessionDep, op: BulkOperation) -> OperationOut:
    await session.refresh(op)
    counts = await bulk._counts(session, op.id)
    done = sum(n for outcome, n in counts.items() if outcome != "pending")
    can_undo = (op.status in ("done", "partial") and op.undone_at is None and op.undo_until is not None
                and op.undo_until >= utcnow() and op.action in bulk.REVERSIBLE)
    return OperationOut.model_validate({
        "id": op.id, "created_at": op.created_at, "updated_at": op.updated_at, "subject": op.subject,
        "action": op.action, "status": op.status, "selected": op.selected, "params": op.params, "counts": counts,
        "done": done, "created_by": op.created_by, "started_at": op.started_at, "finished_at": op.finished_at,
        "undo_until": op.undo_until, "can_undo": can_undo, "error": op.error})


def _group(g: bulk.ReasonGroup) -> ReasonGroupOut:
    return ReasonGroupOut(code=g.code, title=g.title, count=g.count,
                          samples=[SampleOut(id=i, label=label, reason=reason) for i, label, reason in g.samples])


@router.get("/options", response_model=BulkOptionsOut, name="bulk_options")
async def options(session: SessionDep) -> BulkOptionsOut:
    """What the bulk bars may offer, from settings."""
    values = await settings_service.values(session)
    every = list(bulk.ACTIONS)
    return BulkOptionsOut(
        max_selection=int(values["bulk.max_selection"]), undo_window_minutes=int(values["bulk.undo_window_minutes"]),
        approve_reviewed_enabled=bool(values["bulk.allow_approve_reviewed"]),
        reversible=[a for a in every if a in bulk.REVERSIBLE],  # type: ignore[misc]
        actions={"jobs": [a for a in every if a not in bulk.APPLICATION_ONLY],  # type: ignore[misc]
                 "applications": [a for a in every
                                  if a != "approve_reviewed" or values["bulk.allow_approve_reviewed"]]})


@router.post("/preview", response_model=PreviewOut, name="bulk_preview",
             responses={422: {"description": "Bad selection or parameters, or over the size cap ({code, reason})"}})
async def preview(body: PreviewIn, principal: PrincipalDep, session: SessionDep) -> PreviewOut:
    """What would happen to each selected item. Nothing changes; the count to confirm is ``selected``."""
    try:
        cap = int((await settings_service.values(session))["bulk.max_selection"])
        ids = await resolve_ids(session, body.subject, body.selection, cap)
        params = bulk.parse_params(body.params.model_dump(exclude_none=True))
        selection = ({"ids": [str(i) for i in ids]} if body.selection.ids is not None
                     else {"view": body.selection.view.model_dump(mode="json") if body.selection.view else None})
        op = await bulk.create_preview(session, subject=body.subject, action=body.action, ids=ids, params=params,
                                       selection=selection, actor=principal.actor)
    except bulk.BulkError as exc:
        raise _http(exc) from exc
    summary = await bulk.summarise(session, op)
    return PreviewOut(
        operation_id=op.id, subject=body.subject, action=body.action, selected=summary.selected,
        will_change=summary.will_change, unchanged=_group(summary.unchanged) if summary.unchanged else None,
        refused=[_group(g) for g in summary.refused], refused_total=sum(g.count for g in summary.refused),
        reversible=body.action in bulk.REVERSIBLE)


@router.post("/{operation_id}/run", response_model=OperationOut, status_code=status.HTTP_202_ACCEPTED,
             name="bulk_run", responses={409: {"description": "Count does not match, or already run ({code, reason})"}})
async def run(operation_id: uuid.UUID, body: RunIn, principal: PrincipalDep, session: SessionDep,
              enqueue: Annotated[BulkEnqueue, Depends(get_bulk_enqueue)]) -> OperationOut:
    """Confirm the previewed count and run it in the background. Running a failed or partial operation
    again retries only what failed."""
    try:
        op = await bulk.confirm(session, operation_id, confirm_count=body.confirm_count, actor=principal.actor)
    except bulk.BulkError as exc:
        raise _http(exc) from exc
    out = await _out(session, op)
    await session.commit()  # the worker must find the queued operation
    await enqueue(operation_id)
    return out


@router.get("", response_model=Page[OperationOut], name="bulk_list")
async def list_operations(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
                          ) -> Page[OperationOut]:
    rows = (await session.scalars(select(BulkOperation).where(BulkOperation.status != "previewed")
                                  .order_by(BulkOperation.created_at.desc()).limit(limit))).all()
    return Page[OperationOut](items=[await _out(session, r) for r in rows], total=len(rows))


@router.get("/{operation_id}", response_model=OperationOut, name="bulk_get")
async def get_operation(operation_id: uuid.UUID, session: SessionDep) -> OperationOut:
    return await _out(session, await _operation(session, operation_id))


@router.get("/{operation_id}/items", response_model=Page[ItemOut], name="bulk_items")
async def operation_items(operation_id: uuid.UUID, session: SessionDep, outcome: BulkItemOutcome | None = None,
                          cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 100
                          ) -> Page[ItemOut]:
    """Per-item results (what each did, or why it could not)."""
    await _operation(session, operation_id)
    try:
        offset = int(cursor) if cursor else 0
    except ValueError as exc:
        raise HTTPException(422, detail="bad cursor") from exc
    stmt = select(BulkItem).where(BulkItem.operation_id == operation_id)
    if outcome:
        stmt = stmt.where(BulkItem.outcome == outcome)
    rows = list((await session.scalars(stmt.order_by(BulkItem.label, BulkItem.id).offset(offset).limit(limit + 1))
                 ).all())
    return Page[ItemOut](items=[ItemOut.model_validate(r) for r in rows[:limit]],
                         next_cursor=str(offset + limit) if len(rows) > limit else None)


@router.post("/{operation_id}/undo", response_model=OperationOut, name="bulk_undo",
             responses={409: {"description": "Cannot be undone, or the window has passed ({code, reason})"}})
async def undo(operation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> OperationOut:
    try:
        op = await bulk.undo(session, operation_id, actor=principal.actor)
    except bulk.BulkError as exc:
        raise _http(exc) from exc
    return await _out(session, op)


@router.get("/{operation_id}/csv", name="bulk_csv", response_class=Response,
            responses={200: {"content": {"text/csv": {}}}})
async def csv_export(operation_id: uuid.UUID, session: SessionDep) -> Response:
    """The export action's file: the operation's selection as CSV (read only)."""
    op = await _operation(session, operation_id)
    if op.action != "export_csv":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "not_export", "reason": "not an export"})
    return Response(await bulk.export_csv(session, op), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="export-{op.id}.csv"'})
