"""Tailoring requests: create (idempotent), process (one spec version per request), pause and resume.

A request is keyed by the spec version it starts from and the digest of the usable Kit facts, so asking
twice for the same application and version gives the same request, while a Kit change allows a new one.
Processing holds the request row lock; a request already ``done`` is never processed again and a spec
version is unique per request, so a retried or resumed task cannot write a second version.

A budget refusal parks the request ``paused`` with the budget state at the time; :func:`resume_paused`
re-queues it once a cap is set and the cap (or the month) has changed.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.llm.client import BudgetExhausted, LLMClient, LLMError
from app.llm.ledger import month_bounds
from app.llm.money import effective_cap_micros
from app.llm.prompts import active_prompt
from app.models.applications import (
    Application,
    ApplicationSpecVersion,
    Stage,
    TailoringRequest,
    TailoringStatus,
)
from app.models.search import Run, RunKind, RunStatus
from app.pipeline.checks import service as checks
from app.pipeline.checks.items import content_hash
from app.pipeline.tailoring.answers import draft_answers
from app.pipeline.tailoring.prompt import TailorReply, build_messages, select_facts
from app.schemas.json_types import ApplicationSpec

log = logging.getLogger(__name__)

STAGE = "tailor"
OPEN = (TailoringStatus.queued, TailoringStatus.running, TailoringStatus.paused)


class TailoringError(ValueError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def request_key(from_version: int, kit_digest: str) -> str:
    return hashlib.sha256(f"{from_version}|{kit_digest}".encode()).hexdigest()


async def _open_run(session: AsyncSession, app: Application, req: TailoringRequest) -> None:
    """The request's own run, so tailoring started by a sweep or by the owner shows in run history with cost.
    Spend still counts against the sweep that asked (``req.run_id``); this run records the request's outcome."""
    run = Run(kind=RunKind.tailoring, trigger="sweep" if req.run_id else "manual", campaign_id=app.campaign_id,
              status=RunStatus.queued, counts={}, config_versions={"application_id": str(app.id),
                                                                   "request_id": str(req.id)})
    session.add(run)
    await session.flush()
    req.tailoring_run_id = run.id


async def _close_run(session: AsyncSession, req: TailoringRequest, status: RunStatus, *, cost_micros: int = 0,
                     error: str | None = None, counts: dict[str, int] | None = None) -> None:
    run = await session.get(Run, req.tailoring_run_id) if req.tailoring_run_id else None
    if run is None:
        return
    run.status = status
    if status == RunStatus.running:
        run.started_at = run.started_at or utcnow()
        await publish(session, "run.started", {"run_id": str(run.id), "kind": "tailoring"})
        return
    run.error = error
    if status == RunStatus.paused:
        return  # not finished: it resumes when the budget allows
    run.finished_at = utcnow()
    run.cost_micros += cost_micros
    run.counts = counts or {}
    await publish(session, "run.finished", {"run_id": str(run.id), "status": status.value})


async def request(session: AsyncSession, app: Application, *, actor: str,
                  run_id: uuid.UUID | None = None) -> tuple[TailoringRequest, bool]:
    """The request for this application's current spec version and Kit; ``True`` when it needs queueing
    (new, or a failed one retried). Moves a shortlisted application to ``tailoring``."""
    if app.stage not in (Stage.shortlisted, Stage.tailoring, Stage.ready):
        raise TailoringError(f"an application in {app.stage.value} cannot be tailored")
    _, kit = await checks.context(session, app)
    latest = await checks.latest_version(session, app.id)
    from_version = latest.version if latest else 0
    key = request_key(from_version, kit.digest())
    existing = await session.scalar(select(TailoringRequest).where(
        TailoringRequest.application_id == app.id, TailoringRequest.request_key == key).with_for_update())
    if existing is not None:
        if existing.status != TailoringStatus.failed:
            return existing, False
        existing.status, existing.error = TailoringStatus.queued, None
        await _open_run(session, app, existing)
        await session.flush()
        return existing, True
    row = TailoringRequest(application_id=app.id, request_key=key, from_version=from_version, run_id=run_id,
                           requested_by=actor)
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError:  # a concurrent request won the race: use it
        winner = await session.scalar(select(TailoringRequest).where(
            TailoringRequest.application_id == app.id, TailoringRequest.request_key == key))
        assert winner is not None
        return winner, False
    await _open_run(session, app, row)
    if app.stage == Stage.shortlisted:
        await stages.transition(session, app, Stage.tailoring, actor=actor, why="tailoring requested", via="system")
    await audit.record(session, actor=actor, action="application.tailor_requested", subject_type="application",
                       subject_id=app.id, detail={"request_id": str(row.id), "from_version": from_version})
    return row, True


async def _pause_mark(session: AsyncSession, exc: BudgetExhausted, now: datetime) -> dict[str, object]:
    values = await settings_service.values(session)
    return {"scope": exc.scope, "cap_micros": effective_cap_micros(values, "monthly"),
            "per_run_cap_micros": effective_cap_micros(values, "per_run"),
            "month": month_bounds(now, values["general.timezone"])[2]}


async def process(session: AsyncSession, client: LLMClient, request_id: uuid.UUID, *,
                  now: datetime | None = None) -> TailoringStatus:
    """Run one request to a spec version. Safe to call again: a done request is left alone."""
    now = now or utcnow()
    req = await session.get(TailoringRequest, request_id, with_for_update=True)
    if req is None:
        raise TailoringError("tailoring request not found", 404)
    if req.status in (TailoringStatus.done, TailoringStatus.paused, TailoringStatus.failed):
        return req.status
    app = await session.get(Application, req.application_id, with_for_update=True)
    assert app is not None
    req.status = TailoringStatus.running
    req.attempts += 1
    await _close_run(session, req, RunStatus.running)
    job, kit = await checks.context(session, app)
    values = await settings_service.values(session)
    cfg = await checks.check_settings(session, values)
    prompt = await active_prompt(session, STAGE)
    prompt_version = f"db-{prompt.version}" if prompt else "none"
    facts = select_facts(kit, job, limit=int(values["tailoring.max_facts"]))
    messages = build_messages(prompt.text if prompt else "", kit, facts, job,
                              letter_paragraphs=cfg.letter_paragraphs, cv_pages=int(values["documents.cv_pages"]),
                              bullets_per_role=cfg.bullets_per_role)
    model = values["ai.model_tailor"]
    try:
        limit = await client.estimate_cost_micros(STAGE, messages, model=model, schema=TailorReply)
        reply, usage = await client.complete(STAGE, messages, TailorReply, max_cost_micros=limit, model=model)
    except BudgetExhausted as exc:
        req.status = TailoringStatus.paused
        req.paused_mark = await _pause_mark(session, exc, now)
        req.error = str(exc)[:2000]
        await _close_run(session, req, RunStatus.paused, error=req.error)
        await audit.record(session, actor="system", action="application.tailor_paused", subject_type="application",
                           subject_id=app.id, detail={"request_id": str(req.id), "scope": exc.scope})
        return req.status
    except LLMError as exc:
        req.status, req.error = TailoringStatus.failed, str(exc)[:2000]
        await _close_run(session, req, RunStatus.failed, error=req.error)
        await audit.record(session, actor="system", action="application.tailor_failed", subject_type="application",
                           subject_id=app.id, detail={"request_id": str(req.id), "error": req.error[:300]})
        return req.status

    spec = ApplicationSpec.model_validate(reply.model_dump(exclude={"screening_questions"}))
    version = ApplicationSpecVersion(
        application_id=app.id, version=await checks.next_version_number(session, app.id), origin="tailor",
        request_id=req.id, parent_version=req.from_version or None, spec=spec, content_hash=content_hash(spec),
        answers=await draft_answers(session, app, job, reply.screening_questions, today=now.date()),
        model=usage.model, prompt_version=prompt_version, cost_micros=usage.cost_micros, created_by="system")
    session.add(version)
    app.spec = spec
    await session.flush()
    results, check_cost = await checks.check_version(session, version, client=client)
    version.cost_micros = usage.cost_micros + check_cost
    req.status, req.result_version, req.error, req.paused_mark = TailoringStatus.done, version.version, None, None
    await _close_run(session, req, RunStatus.succeeded, cost_micros=version.cost_micros, counts={"tailored": 1})
    await stages.add_event(session, app.id, "spec_version", "system", {
        "version": version.version, "origin": "tailor", "content_hash": version.content_hash,
        "status": checks.worst(results)})
    await audit.record(session, actor="system", action="application.tailored", subject_type="application",
                       subject_id=app.id, detail={"request_id": str(req.id), "version": version.version,
                                                  "model": usage.model, "prompt_version": prompt_version,
                                                  "facts_sent": [f.code for f in facts],
                                                  "cost_micros": version.cost_micros})
    await publish(session, "application.updated", {"application_id": str(app.id)})
    return req.status


async def resume_paused(session: AsyncSession, enqueue: Callable[[TailoringRequest], Awaitable[None]], *,
                        now: datetime | None = None) -> list[TailoringRequest]:
    """Re-queue requests paused for budget once the budget allows (a cap is set, and it or the month
    changed since the pause). Commits before enqueueing."""
    paused = list((await session.scalars(select(TailoringRequest).where(
        TailoringRequest.status == TailoringStatus.paused).order_by(TailoringRequest.created_at))).all())
    if not paused:
        return []
    values = await settings_service.values(session)
    cap = effective_cap_micros(values, "monthly")
    if cap is None:
        return []
    month = month_bounds(now or utcnow(), values["general.timezone"])[2]
    resumed: list[TailoringRequest] = []
    for req in paused:
        mark = req.paused_mark or {}
        if (mark.get("cap_micros") == cap and mark.get("per_run_cap_micros") == effective_cap_micros(values, "per_run")
                and mark.get("month") == month):
            continue
        req.status = TailoringStatus.queued
        if req.tailoring_run_id:
            run = await session.get(Run, req.tailoring_run_id)
            if run is not None:
                run.status, run.error = RunStatus.queued, None
        await audit.record(session, actor="system", action="application.tailor_resumed", subject_type="application",
                           subject_id=req.application_id, detail={"request_id": str(req.id),
                                                                  "after": mark.get("scope")})
        resumed.append(req)
    await session.commit()
    for req in resumed:
        await enqueue(req)
    return resumed
