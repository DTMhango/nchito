"""A fake server-enforced channel for dispatch tests: no network, every call recorded."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from app.apply.channels.base import ChannelName, DispatchOutcome, DispatchRequest, Enforcement
from app.schemas.json_types import Evidence


def sent(message_id: str = "msg-1") -> DispatchOutcome:
    return DispatchOutcome(status="sent", provider_message_id=message_id,
                           evidence=Evidence(kind="sent_mail_id", value=message_id))


@dataclass
class FakeChannel:
    """``outcomes`` are returned in order by ``dispatch`` (an exception instance is raised); the last one
    repeats. ``reconciles`` likewise for ``reconcile``. ``delay`` makes dispatch slow (concurrency tests)."""

    name: ClassVar[ChannelName] = "email"
    enforcement: ClassVar[Enforcement] = "server"

    outcomes: list[DispatchOutcome | BaseException] = field(default_factory=lambda: [sent()])
    reconciles: list[DispatchOutcome] = field(default_factory=lambda: [DispatchOutcome(status="unknown")])
    delay: float = 0.0
    dispatched: list[DispatchRequest] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    hasher: Callable[..., str] | None = None

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        self.dispatched.append(request)
        if self.hasher is not None:
            assert self.hasher(request.packet) == request.packet_hash
        if self.delay:
            await asyncio.sleep(self.delay)
        out = self.outcomes[min(len(self.dispatched), len(self.outcomes)) - 1]
        if isinstance(out, BaseException):
            raise out
        return out

    async def cancel(self, attempt_id: str) -> bool:
        self.cancelled.append(attempt_id)
        return True

    async def reconcile(self, attempt_id: str) -> DispatchOutcome:
        self.reconciled.append(attempt_id)
        return self.reconciles[min(len(self.reconciled), len(self.reconciles)) - 1]
