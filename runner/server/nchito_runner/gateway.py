"""Client for the Nchito agent gateway (MCP streamable HTTP at /mcp, CONTRACTS.md section 8).

Tool names and argument shapes are the contract's; results come back as plain dicts. The
connection is re-opened after a transport failure. Liveness: the contract has no heartbeat
tool, so ``ping`` (an MCP-level request, authenticated by the same bearer token) is the
heartbeat, and the idle ``next_task`` poll doubles as last-seen. ``release_task`` is optional
(used only when the server lists it); otherwise a shutdown saves a checkpoint and stops the
heartbeat so the server's stale-claim logic returns the lease.
"""

from __future__ import annotations

import contextlib
import json
from contextlib import AsyncExitStack
from typing import Any, Protocol

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class GatewayError(Exception):
    pass


class Gateway(Protocol):
    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...
    async def ping(self) -> None: ...
    async def has_tool(self, name: str) -> bool: ...
    async def close(self) -> None: ...


class McpGateway:
    def __init__(self, url: str, token: str):
        self._url = url
        self._token = token
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: set[str] | None = None

    async def _connect(self) -> ClientSession:
        if self._session is not None:
            return self._session
        stack = AsyncExitStack()
        try:
            client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {self._token}"}, timeout=60.0)
            await stack.enter_async_context(client)
            streams = await stack.enter_async_context(streamable_http_client(self._url, http_client=client))
            session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self._session = stack, session
        return session

    async def _reset(self) -> None:
        stack, self._stack, self._session, self._tools = self._stack, None, None, None
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
            raise GatewayError(f"{tool}: {last}") from last
        payload = self._payload(result)
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            raise GatewayError(f"{tool}: {payload}")
        return payload

    @staticmethod
    def _payload(result: Any) -> dict[str, Any]:
        structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured.get("result", structured) if set(structured) == {"result"} and isinstance(
                structured["result"], dict) else structured
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                try:
                    data = json.loads(text)
                except ValueError:
                    return {"text": text}
                return data if isinstance(data, dict) else {"result": data}
        return {}

    async def ping(self) -> None:
        session = await self._connect()
        await session.send_ping()

    async def has_tool(self, name: str) -> bool:
        if self._tools is None:
            session = await self._connect()
            self._tools = {t.name for t in (await session.list_tools()).tools}
        return name in self._tools

    async def close(self) -> None:
        await self._reset()
