"""Shared async HTTP client for connectors: per-source rate limiting, timeouts, bounded retries.

Connectors never build their own client; they receive an ``HttpFetcher`` (see ``base.py``).
In production that is a ``PoliteFetcher`` around an ``HttpxFetcher``; in tests it is a recorded
fixture fetcher, so no test touches the network.

The User-Agent is generic on purpose: it names the software, never the owner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.sources.base import HttpFetcher, RateLimitSpec, SourceError

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; NchitoJobReader/1.0)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BODY_BYTES = 12_000_000


@dataclass(frozen=True)
class HttpPolicy:
    """Technical transport limits (not business settings)."""

    timeout_seconds: float = 20.0
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    backoff_cap_seconds: float = 20.0


Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Token bucket: ``burst`` tokens, refilled at ``requests_per_minute``. One per source."""

    def __init__(self, spec: RateLimitSpec, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Sleep = asyncio.sleep) -> None:
        self._rate = spec.requests_per_minute / 60.0
        self._capacity = float(max(spec.burst, 1))
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._stamp = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                self._tokens = min(self._capacity, self._tokens + (now - self._stamp) * self._rate)
                self._stamp = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await self._sleep((1.0 - self._tokens) / self._rate)


class HttpxFetcher:
    """Plain httpx transport with timeouts and bounded retries on transient failures."""

    def __init__(self, policy: HttpPolicy | None = None, *, client: httpx.AsyncClient | None = None,
                 sleep: Sleep = asyncio.sleep) -> None:
        self.policy = policy or HttpPolicy()
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.policy.timeout_seconds, follow_redirects=True,
                                             headers={"User-Agent": USER_AGENT})
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> tuple[int, str]:
        policy = self.policy
        last = ""
        for attempt in range(1, policy.max_attempts + 1):
            try:
                response = await self._get_client().request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = type(exc).__name__
            else:
                if response.status_code not in RETRY_STATUSES:
                    if len(response.content) > MAX_BODY_BYTES:
                        raise SourceError("response too large")
                    return response.status_code, response.text
                last = f"HTTP {response.status_code}"
                retry_after = response.headers.get("retry-after", "")
                too_long = retry_after.isdigit() and int(retry_after) > policy.backoff_cap_seconds
                if response.status_code == 429 and too_long:
                    return response.status_code, response.text  # a source that asks us to wait long is not hammered
            if attempt < policy.max_attempts:
                await self._sleep(min(policy.backoff_cap_seconds, policy.backoff_seconds * 2 ** (attempt - 1)))
        raise SourceError(f"request failed after {policy.max_attempts} attempts ({last})")

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        return await self._request("GET", url, headers=dict(headers) if headers else None)

    async def post_json(self, url: str, payload: Mapping[str, Any]) -> tuple[int, str]:
        return await self._request("POST", url, content=json.dumps(payload),
                                   headers={"Content-Type": "application/json", "Accept": "application/json"})


class PoliteFetcher:
    """Applies one source's rate limit to every request of an inner fetcher."""

    def __init__(self, inner: HttpFetcher, limiter: RateLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        await self._limiter.acquire()
        return await self._inner.get(url, headers=headers)

    async def post_json(self, url: str, payload: Mapping[str, Any]) -> tuple[int, str]:
        await self._limiter.acquire()
        return await self._inner.post_json(url, payload)


def polite(inner: HttpFetcher, spec: RateLimitSpec) -> PoliteFetcher:
    return PoliteFetcher(inner, RateLimiter(spec))


def parse_json(status: int, body: str, what: str) -> Any:
    """Decode a JSON response or raise ``SourceError`` (blocked, schema change, HTTP error)."""
    if status != 200:
        raise SourceError(f"{what}: HTTP {status}")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise SourceError(f"{what}: response was not JSON") from exc
