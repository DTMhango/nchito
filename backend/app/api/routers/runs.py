"""Runs and schedules. Wave 1 (sources stream: runs, scheduler)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Page, Timestamps
from app.api.crud_db import add_db_crud, page_of
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.models.search import Campaign, Run, RunKind, RunStatus, Schedule
from app.schemas.json_types import SourceRunResult

router = APIRouter(prefix="/api", tags=["runs"], dependencies=[RequireOwner], responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "runs"

RunKindT = Literal["sweep", "rescore", "expiry_check", "digest", "backup", "retention"]
ACTIVE = (RunStatus.queued, RunStatus.running)


class ProposedAction(BaseModel):
    job_id: uuid.UUID | None = Field(description="None when the posting is new and has no job yet")
    title: str
    employer: str
    action: str = Field(description="apply, ask_owner, prepare, add_to_matches, review, skip or parked")
    reason: str
    score: int | None = None


class RunOut(Timestamps):
    kind: RunKindT
    trigger: str
    campaign_id: uuid.UUID | None
    schedule_id: uuid.UUID | None
    scheduled_for: datetime | None
    dry_run: bool
    counts: dict[str, int] = Field(
        description="Per-stage counts: found, new, passed_filters, above_threshold, tailored, applied (later stages "
                    "stay 0 until their stream lands), plus intake detail (seen, suppressed, reposted, extracted, ...)")
    proposed_actions: list[ProposedAction] = Field(default_factory=list,
                                                   description="Dry runs only: what a real run would do")
    source_results: list[SourceRunResult]
    cost_minor: int
    cost_micros: int = 0
    config_versions: dict[str, Any]
    status: Literal["queued", "running", "succeeded", "failed", "partial", "cancelled", "skipped", "paused"]
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None

    @model_validator(mode="before")
    @classmethod
    def _lift_proposed(cls, data: Any) -> Any:
        if isinstance(data, Run):
            payload = {name: getattr(data, name) for name in cls.model_fields if hasattr(data, name)}
            payload["proposed_actions"] = (data.config_versions or {}).get("proposed_actions", [])
            return payload
        return data


class RunCreate(BaseModel):
    kind: RunKindT
    campaign_id: uuid.UUID | None = None
    dry_run: bool = False


class ScheduleIn(ApiModel):
    name: str
    kind: RunKindT
    campaign_id: uuid.UUID | None = None
    cron: str = Field(description="Five-field cron in the schedule's time zone")
    timezone: str | None = Field(default=None, description="None: general.timezone")
    enabled: bool = True
    dry_run: bool = False


class ScheduleOut(ScheduleIn, Timestamps):
    next_run_at: datetime | None
    last_enqueued_at: datetime | None
    last_run_id: uuid.UUID | None


Enqueue = Callable[[Run], Awaitable[None]]


async def get_enqueue() -> Enqueue:
    """Defers the run to the worker. The web process opens the queue connection per call; tests
    replace this dependency."""

    async def enqueue(run: Run) -> None:
        from app.worker.queue import enqueue_run, queue_app

        async with queue_app.open_async():
            await enqueue_run(run)

    return enqueue


EnqueueDep = Annotated[Enqueue, Depends(get_enqueue)]


@router.get("/runs", response_model=Page[RunOut], name="runs_list")
async def list_runs(session: SessionDep, kind: RunKindT | None = None, campaign_id: uuid.UUID | None = None,
                    cursor: str | None = None, limit: int = 50) -> Page[RunOut]:
    where = []
    if kind:
        where.append(Run.kind == RunKind(kind))
    if campaign_id:
        where.append(Run.campaign_id == campaign_id)
    rows, total, nxt = await page_of(session, Run, [Run.created_at.desc(), Run.id], cursor, limit, *where)
    return Page[RunOut](items=[RunOut.model_validate(r) for r in rows], total=total, next_cursor=nxt)


@router.get("/runs/{run_id}", response_model=RunOut, name="runs_get")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> RunOut:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return RunOut.model_validate(run)


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED, name="runs_create",
             responses={409: {"description": "A run for this campaign is already queued or running"},
                        422: {"description": "A sweep needs an existing campaign"}})
async def create_run(body: RunCreate, session: SessionDep, principal: PrincipalDep, enqueue: EnqueueDep) -> RunOut:
    """Start a manual run (or a dry run: counts what a sweep would do, writes nothing)."""
    kind = RunKind(body.kind)
    if kind == RunKind.sweep:
        if body.campaign_id is None or await session.get(Campaign, body.campaign_id) is None:
            raise HTTPException(422, detail="A sweep needs an existing campaign.")
        busy = await session.scalar(select(Run.id).where(Run.kind == kind, Run.campaign_id == body.campaign_id,
                                                         Run.status.in_(ACTIVE)).limit(1))
        if busy is not None:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="A sweep for this campaign is already queued or running.")
    run = Run(kind=kind, trigger="manual", campaign_id=body.campaign_id, dry_run=body.dry_run,
              status=RunStatus.queued)
    session.add(run)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="run.started", subject_type="run", subject_id=run.id,
                       detail={"kind": body.kind, "dry_run": body.dry_run})
    out = RunOut.model_validate(run)
    await session.commit()  # the worker must find the row when it picks the job up
    await enqueue(run)
    return out


@router.post("/runs/{run_id}/cancel", response_model=RunOut, name="runs_cancel",
             responses={409: {"description": "The run already finished"}})
async def cancel_run(run_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> RunOut:
    """Cancel a queued run at once; a running sweep stops at its next checkpoint and keeps what it saved."""
    run = await session.get(Run, run_id, with_for_update=True)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    if run.status not in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"The run already {run.status.value}.")
    was_queued = run.status == RunStatus.queued
    run.status = RunStatus.cancelled
    if was_queued:
        run.finished_at = utcnow()
        await publish(session, "run.finished", {"run_id": str(run.id), "status": "cancelled"})
    await audit.record(session, actor=principal.actor, action="run.cancelled", subject_type="run",
                       subject_id=run.id, detail={"was": "queued" if was_queued else "running"})
    await session.refresh(run)
    return RunOut.model_validate(run)


# ----- schedules -----------------------------------------------------------------------------


async def _prepare_schedule(session: Any, data: dict[str, Any], existing: Schedule | None) -> dict[str, Any]:
    cron = " ".join(data["cron"].split())
    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        raise ValueError("cron must be a valid five-field expression, for example 0 6 * * *")
    tz = data.get("timezone")
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {tz!r}") from exc
    kind = RunKind(data["kind"])
    if kind == RunKind.sweep and (data.get("campaign_id") is None
                                  or await session.get(Campaign, data["campaign_id"]) is None):
        raise ValueError("a sweep schedule needs an existing campaign")
    data.update(cron=cron, kind=kind, next_run_at=None)  # the tick re-arms from the new cron and zone
    return data


add_db_crud(router, "/schedules", "schedules", orm=Schedule, model_in=ScheduleIn, model_out=ScheduleOut,
            audit_prefix="schedule", order_by=[Schedule.created_at, Schedule.id], prepare=_prepare_schedule)
