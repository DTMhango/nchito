"""Injectable HTTP transport for outbound connections (Drive, Telegram, webhooks).

Connectors never create their own HTTP client: they receive an ``HttpTransport``. Production uses
``HttpxTransport``; tests pass a fake, so nothing in the test suite touches the network.
``get_transport`` / ``set_transport`` give web and worker one shared default that tests replace.
"""

from __future__ import annotations

import json as jsonlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return jsonlib.loads(self.body.decode("utf-8")) if self.body else None


@runtime_checkable
class HttpTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
        data: Mapping[str, str] | None = None,
    ) -> HttpResponse: ...


class HttpxTransport:
    """The real transport. A client per call keeps it safe across event loops (web and worker)."""

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._timeout = timeout_seconds

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
        data: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            resp = await client.request(method, url, headers=dict(headers or {}), params=dict(params or {}),
                                        json=json, content=content, data=dict(data) if data else None)
        return HttpResponse(status=resp.status_code, body=resp.content, headers=dict(resp.headers))


_default: HttpTransport | None = None


def get_transport() -> HttpTransport:
    global _default
    if _default is None:
        _default = HttpxTransport()
    return _default


def set_transport(transport: HttpTransport | None) -> None:
    """Replace the shared default (tests); ``None`` restores the real one."""
    global _default
    _default = transport
