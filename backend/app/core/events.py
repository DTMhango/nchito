"""Server-sent events.

Producers (web or worker) call ``publish(session, type, data)``: it issues ``pg_notify`` inside
the caller's transaction, so listeners hear about a change only once it is committed.
The web process runs one ``EventHub`` that LISTENs on the channel and fans events out to every
connected SSE client. Payloads are small (a type and ids); clients refetch what they need.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_config

log = logging.getLogger(__name__)

CHANNEL = "nchito_events"
MAX_PAYLOAD = 7000  # pg_notify limit is 8000 bytes


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]
    at: str

    def to_sse(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps({'data': self.data, 'at': self.at})}\n\n"


def _encode(event_type: str, data: dict[str, Any]) -> str:
    payload = json.dumps({"type": event_type, "data": data, "at": utcnow().isoformat()}, default=str)
    if len(payload.encode()) > MAX_PAYLOAD:
        raise ValueError("event payload too large: send ids, not records")
    return payload


async def publish(session: AsyncSession, event_type: str, data: dict[str, Any] | None = None) -> None:
    await session.execute(text("SELECT pg_notify(:channel, :payload)"),
                          {"channel": CHANNEL, "payload": _encode(event_type, data or {})})


class EventHub:
    """Fan-out of database notifications to in-process subscribers."""

    def __init__(self, queue_size: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._queue_size = queue_size
        self._conn: asyncpg.Connection | None = None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def dispatch(self, event: Event) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()  # slow client: drop its oldest event
            queue.put_nowait(event)

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            raw = json.loads(payload)
            self.dispatch(Event(type=raw["type"], data=raw.get("data", {}), at=raw.get("at", "")))
        except (ValueError, KeyError):
            log.warning("ignored malformed event payload")

    async def start(self) -> None:
        dsn = get_config().libpq_url
        try:
            self._conn = await asyncpg.connect(dsn)
            await self._conn.add_listener(CHANNEL, self._on_notify)
        except (OSError, asyncpg.PostgresError) as exc:
            log.error("event hub could not listen: %s", exc)
            self._conn = None

    async def stop(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                await self._conn.close()
        self._conn = None

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


hub = EventHub()
