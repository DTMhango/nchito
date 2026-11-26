"""Client for the Nchito agent gateway (MCP streamable HTTP at ``<NCHITO_URL>/mcp``, CONTRACTS.md section 8 and
"Wave 3 gateway additions").

The gateway runs the official ``mcp`` SDK 1.x as a stateless streamable-HTTP server with JSON responses and a
bearer token on every request. Tool names and argument shapes are the contract's; results come back as plain dicts.
A refused call is an MCP tool error whose text is ``{"code", "reason"}``; it is raised as ``GatewayError`` with
that ``code``. The connection is re-opened once after a transport failure.

Files never travel through the browser: packet files are fetched from the gateway's signed
``/api/gateway/files/{signed}`` links and evidence is ``PUT`` to its signed ``/api/gateway/uploads/{signed}`` links,
always on the gateway this runner is connected to (``Guard.gateway_file_url``), never anywhere else.
"""

from __future__ import annotations

import contextlib
import json
from contextlib import AsyncExitStack
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .guard import Guard

# The gateway's final tool list (backend/app/gateway/tools.py ``TOOLS``). ``check`` scripts compare against it.
EXPECTED_TOOLS: tuple[str, ...] = (
    "next_task", "get_packet", "find_answer", "save_checkpoint", "raise_blocker", "request_submit_permit",
    "report_result", "report_jobs", "report_check", "release_task", "evidence_upload_url", "get_runner_config",
)
FILES_PATH = "/api/gateway/files/"
UPLOADS_PATH = "/api/gateway/uploads/"


class GatewayError(Exception):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class Gateway(Protocol):
    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...
    async def ping(self) -> None: ...
    async def list_tools(self) -> list[str]: ...
    async def download(self, signed_url: str) -> bytes: ...
    async def upload(self, signed_url: str, content: bytes, content_type: str) -> None: ...
    async def close(self) -> None: ...


def gateway_root(mcp_url: str) -> str:
    """``https://nchito.example.com/mcp`` -> ``https://nchito.example.com``."""
    root = mcp_url.rstrip("/")
    return root[: -len("/mcp")] if root.endswith("/mcp") else root


def error_from(tool: str, payload: dict[str, Any]) -> GatewayError:
    code = payload.get("code") if isinstance(payload.get("code"), str) else None
    reason = payload.get("reason") or payload.get("text") or payload
    return GatewayError(f"{tool}: {code + ': ' if code else ''}{reason}", code=code)


class McpGateway:
    def __init__(self, mcp_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 60.0):
        self._url = mcp_url
        self._root = gateway_root(mcp_url)
        self._token = token
        self._transport = transport
        self._timeout = timeout
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._files: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers={"Authorization": f"Bearer {self._token}"}, timeout=self._timeout,
                                 transport=self._transport, follow_redirects=False)

    async def _connect(self) -> ClientSession:
        if self._session is not None:
            return self._session
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(self._client())
            read, write, _ = await stack.enter_async_context(streamable_http_client(self._url, http_client=client))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self._session = stack, session
        return session

    async def _reset(self) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack:
            with contextlib.suppress(Exception):
                await stack.aclose()

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        for _ in range(2):  # one transparent reconnect
            try:
                session = await self._connect()
                result = await session.call_tool(tool, args)
                break
            except Exception as exc:
                last = exc
                await self._reset()
        else:
            raise GatewayError(f"{tool}: {last}", code="transport") from last
        payload = self._payload(result)
        if getattr(result, "isError", False):
            raise error_from(tool, payload)
        return payload

    @staticmethod
    def _payload(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            if set(structured) == {"result"} and isinstance(structured["result"], dict):
                return structured["result"]
            return structured
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if not text:
                continue
            start = text.find("{")  # an SDK may prefix an error text ("Error executing tool x: {...}")
            try:
                data = json.loads(text[start:] if start >= 0 else text)
            except ValueError:
                return {"text": text}
            return data if isinstance(data, dict) else {"result": data}
        return {}

    async def ping(self) -> None:
        session = await self._connect()
        await session.send_ping()

    async def list_tools(self) -> list[str]:
        session = await self._connect()
        return [t.name for t in (await session.list_tools()).tools]

    def _files_client(self) -> httpx.AsyncClient:
        if self._files is None:
            self._files = self._client()
        return self._files

    async def download(self, signed_url: str) -> bytes:
        url = Guard.gateway_file_url(signed_url, self._root, FILES_PATH)
        resp = await self._files_client().get(url)
        if resp.status_code != 200:
            raise GatewayError(f"file download: HTTP {resp.status_code}", code=f"http_{resp.status_code}")
        return resp.content

    async def upload(self, signed_url: str, content: bytes, content_type: str) -> None:
        url = Guard.gateway_file_url(signed_url, self._root, UPLOADS_PATH)
        resp = await self._files_client().put(url, content=content, headers={"Content-Type": content_type})
        if resp.status_code not in (200, 201):
            raise GatewayError(f"evidence upload: HTTP {resp.status_code}", code=f"http_{resp.status_code}")

    async def close(self) -> None:
        await self._reset()
        files, self._files = self._files, None
        if files is not None:
            with contextlib.suppress(Exception):
                await files.aclose()
