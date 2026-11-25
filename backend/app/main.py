"""FastAPI application: /api REST + SSE, the built SPA at / when present."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routers import ALL_ROUTERS
from app.core.config import get_config
from app.core.db import dispose_engine
from app.core.events import hub
from app.core.security import csrf_ok

log = logging.getLogger(__name__)


def _operation_id(route: APIRoute) -> str:
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()
        await dispose_engine()


def _mount_spa(app: FastAPI, spa_dir: Path) -> None:
    index = spa_dir / "index.html"
    if not index.is_file():
        log.info("no built SPA at %s; serving the API only", spa_dir)
        return
    assets = spa_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="spa-assets")
    root = spa_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "mcp")):
            return JSONResponse({"detail": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(spa_dir: Path | None = None) -> FastAPI:
    cfg = get_config()
    app = FastAPI(
        title="Nchito API",  # stable contract title; the product name is the general.app_name setting
        version=__version__,
        summary="Private single-owner job-hunting platform",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path.startswith("/api/") and not csrf_ok(request):
            return JSONResponse({"detail": "cross-site request refused"}, status_code=status.HTTP_403_FORBIDDEN)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    for router in ALL_ROUTERS:
        app.include_router(router)

    _mount_spa(app, spa_dir if spa_dir is not None else cfg.spa_dir)
    return app


app = create_app()
