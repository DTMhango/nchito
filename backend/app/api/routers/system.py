"""Health, audit log, and the SSE event stream."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import PrincipalDep, SessionDep
from app.core.events import hub
from app.models.platform import AuditEvent
from app.ops.health import Health, check

router = APIRouter(prefix="/api", tags=["system"])

SSE_KEEPALIVE_SECONDS = 15.0


@router.get("/health", response_model=Health, operation_id="health",
            responses={503: {"model": Health, "description": "Database unreachable"}})
async def health(session: SessionDep, response: Response) -> Health:
    """Public. 200 when the database answers (status `ok`, or `degraded` if the worker is
    stale); 503 when the database is down."""
    result = await check(session)
    if result.status == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor: str
    action: str
    subject_type: str | None = None
    subject_id: str | None = None
    detail: dict[str, Any]
    ip: str | None = None


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    next_before: datetime | None = None


@router.get("/audit", response_model=AuditPage, operation_id="audit_list", tags=["audit"])
async def list_audit(
    _: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=500),
    before: datetime | None = Query(default=None, description="Return events strictly older than this"),
    action: str | None = Query(default=None, description="Exact action, or a prefix ending in '.'"),
    subject_type: str | None = None,
    subject_id: str | None = None,
    actor: str | None = None,
) -> AuditPage:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
    if before is not None:
        stmt = stmt.where(AuditEvent.created_at < before)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action) if action.endswith(".") else
                          AuditEvent.action == action)
    if subject_type:
        stmt = stmt.where(AuditEvent.subject_type == subject_type)
    if subject_id:
        stmt = stmt.where(AuditEvent.subject_id == subject_id)
    if actor:
        stmt = stmt.where(AuditEvent.actor == actor)
    rows = list((await session.scalars(stmt)).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(
        items=[AuditEventOut.model_validate(r, from_attributes=True) for r in rows],
        next_before=rows[-1].created_at if more and rows else None,
    )


@router.get("/events", operation_id="events_stream", tags=["events"],
            response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}},
                             "description": "Server-sent events: `event: <type>` / `data: {data, at}`"}})
async def events(request: Request, _: PrincipalDep) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        async with hub.subscribe() as queue:
            yield "retry: 5000\n: connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield event.to_sse()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
