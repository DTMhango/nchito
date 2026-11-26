"""Health: liveness, readiness (public, for the platform) and the owner's detailed report."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.deps import RequireOwner, SessionDep
from app.ops import health as ops_health

router = APIRouter(prefix="/api/health", tags=["system"])


class Live(BaseModel):
    alive: bool = True


@router.get("/live", response_model=Live, operation_id="health_live")
async def live() -> Live:
    """Liveness: the process answers. Touches nothing, so a database outage does not restart the web tier."""
    return Live()


@router.get("/ready", response_model=ops_health.Ready, operation_id="health_ready",
            responses={503: {"model": ops_health.Ready, "description": "Database down or not migrated"}})
async def ready(session: SessionDep, response: Response) -> ops_health.Ready:
    """Readiness: the database answers and is migrated. A stale worker does not make the web tier unready."""
    result = await ops_health.ready(session)
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/detail", response_model=ops_health.DetailedHealth, operation_id="health_detail",
            dependencies=[RequireOwner])
async def detail(session: SessionDep) -> ops_health.DetailedHealth:
    """Worker heartbeat age, last successful sweep and backup, disk, queue depth, per-connection status."""
    return await ops_health.detailed(session)
