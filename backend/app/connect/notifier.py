"""Notifier interface: Telegram, signed webhook, and (from the mail stream) email. DESIGN.md 12, 14.

Invariants:
- A ``Notifier`` only delivers an ``OutboundMessage`` it is given. It never reads the database,
  and the message carries no secrets and no records, only a title, a short body and links.
- ``event_id`` is the idempotency key of the message; receivers can drop a repeat.
- A failure raises ``DeliveryError``; the caller records it and retries within bounds. Delivery
  failures never fail the pipeline that produced the event.
- Channels register a factory here: ``register_notifier_factory("email", factory)``. The factory
  returns ``None`` when the channel is not connected.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Button:
    label: str
    url: str


@dataclass(frozen=True)
class OutboundMessage:
    event_id: str
    kind: str
    title: str
    body: str | None
    created_at: datetime
    link: str | None = None
    buttons: tuple[Button, ...] = field(default_factory=tuple)


class DeliveryError(RuntimeError):
    """The channel did not accept the message. ``detail`` is safe to store and show (no secrets)."""

    def __init__(self, detail: str, *, retryable: bool = True) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retryable = retryable


@runtime_checkable
class Notifier(Protocol):
    channel: str

    async def send(self, message: OutboundMessage) -> None: ...


NotifierFactory = Callable[[AsyncSession], Awaitable[Notifier | None]]

_FACTORIES: dict[str, NotifierFactory] = {}


def register_notifier_factory(channel: str, factory: NotifierFactory) -> None:
    _FACTORIES[channel] = factory


def unregister_notifier_factory(channel: str) -> None:
    _FACTORIES.pop(channel, None)


async def notifier_for(session: AsyncSession, channel: str) -> Notifier | None:
    factory = _FACTORIES.get(channel)
    return await factory(session) if factory else None


def registered_channels() -> list[str]:
    return sorted(_FACTORIES)
