"""The MCP server at ``/mcp`` (streamable HTTP, official ``mcp`` SDK), DESIGN.md 8.3; CONTRACTS.md 8.

- Stateless streamable HTTP with JSON responses: each POST is one self-contained exchange, so the web
  process keeps no MCP session state and needs no lifespan hook.
- ``Authorization: Bearer nch_...`` on every request. A missing, unknown or revoked token is 401 before
  the MCP layer sees anything. Every authenticated request (tool call, list, ping) updates the runner's
  last-seen (``ApiToken.last_used_at``). Calls per token are limited per minute (``runners.calls_per_minute``,
  per web process).
- Tools and their JSON Schemas are exactly ``app.gateway.tools.TOOLS``; the server validates input and
  output against them. A refused call returns an MCP tool error whose text is ``{"code", "reason"}``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict, deque
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app import __version__
from app.core.db import get_sessionmaker
from app.gateway import auth, common, service
from app.gateway.common import GatewayError
from app.gateway.tools import TOOLS

SCOPE_KEY = "nchito_runner_id"

server: Server[Any, Request] = Server("nchito-gateway", version=__version__,
                                      instructions="Nchito agent gateway. Call next_task to start; the rules in "
                                                   "each task's instructions are enforced by the server.")


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [types.Tool(name=name, description=desc, inputSchema=i.model_json_schema(),
                       outputSchema=o.model_json_schema())
            for name, (i, o, desc) in TOOLS.items()]


@server.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    request = server.request_context.request
    runner_id = request.scope.get("state", {}).get(SCOPE_KEY) if request is not None else None
    if runner_id is None:
        raise GatewayError("unauthenticated", "no runner token on this request")
    return await service.call(uuid.UUID(runner_id), name, arguments)


class _RateLimiter:
    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        calls = self._calls[key]
        while calls and calls[0] <= now - window:
            calls.popleft()
        if len(calls) >= limit:
            return False
        calls.append(now)
        return True

    def reset(self) -> None:
        self._calls.clear()


limiter = _RateLimiter()


def _unauthorised(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=401, headers={"WWW-Authenticate": 'Bearer realm="nchito"'})


async def _authenticate(scope: Scope) -> tuple[str | None, JSONResponse | None]:
    request = Request(scope)
    raw = auth.parse_bearer(request.headers.get("authorization"))
    if raw is None:
        return None, _unauthorised("a runner bearer token is required")
    async with get_sessionmaker()() as session:
        token = await auth.authenticate(session, raw)
        if token is None:
            return None, _unauthorised("unknown or revoked token")
        limit = int(await common.setting(session, "runners.calls_per_minute"))
        token_id = str(token.id)
        token.last_used_at = common.now()  # any authenticated request (a ping too) is the runner's last-seen
        await session.commit()
    if not limiter.allow(token_id, limit):
        return None, JSONResponse({"detail": "too many calls; slow down"}, status_code=429,
                                  headers={"Retry-After": "60"})
    return token_id, None


class GatewayApp:
    """ASGI app for ``/mcp``: bearer auth and rate limit, then one stateless MCP exchange."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        token_id, refusal = await _authenticate(scope)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        scope = {**scope, "state": {**scope.get("state", {}), SCOPE_KEY: token_id}}
        transport = StreamableHTTPServerTransport(mcp_session_id=None, is_json_response_enabled=True,
                                                  event_store=None)

        async def run_server(*, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            async with transport.connect() as (read_stream, write_stream):
                task_status.started()
                await server.run(read_stream, write_stream, server.create_initialization_options(), stateless=True)

        async with anyio.create_task_group() as tg:
            await tg.start(run_server)
            try:
                await transport.handle_request(scope, receive, send)
            finally:
                with anyio.CancelScope(shield=True):
                    await transport.terminate()


gateway_app = GatewayApp()


def error_payload(exc: BaseException) -> dict[str, Any]:
    """The ``{"code", "reason"}`` a runner sees for a refused call."""
    if isinstance(exc, GatewayError):
        return {"code": exc.code, "reason": exc.reason}
    try:
        return json.loads(str(exc))
    except ValueError:
        return {"code": "error", "reason": str(exc)}
