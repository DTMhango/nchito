"""Apply channel interface (DESIGN.md 8.2, 18.1-18.3).

Channels: ``email`` (server-enforced), ``browser`` (through the agent gateway; instructed and
audited), ``manual`` (the owner). Invariants every channel MUST keep:

- **Nothing leaves without a dispatch attempt.** The apply layer writes a ``DispatchAttempt``
  and reserves caps in one transaction *before* calling ``dispatch``. Channels never create
  attempts themselves.
- **Bound to the packet.** ``dispatch`` sends exactly the ``PacketContents`` whose hash is on the
  attempt. If the packet hash on the application changed, the apply layer cancels; the channel
  must not re-read live data.
- **Gates are rechecked at dispatch**, after the send delay (pause, caps, expiry, duplicates,
  conflict group) by the apply layer via ``pipeline.decisions``; a channel does not decide.
- **No automatic resend.** An attempt with no recorded outcome is ``unknown`` /
  ``submitted_unconfirmed`` and is reconciled, never retried.
- **Evidence or it did not happen.** ``DispatchOutcome.evidence`` is required for ``sent``;
  without it the application is ``submitted_unconfirmed``.
- **Cancellable until handed off.** ``cancel`` succeeds only before the provider has the message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, runtime_checkable

from app.schemas.json_types import Evidence, PacketContents

ChannelName = Literal["email", "browser", "manual"]
Enforcement = Literal["server", "instructed", "owner"]


@dataclass(frozen=True)
class DispatchRequest:
    attempt_id: str
    application_id: str
    packet_hash: str
    packet: PacketContents


@dataclass(frozen=True)
class DispatchOutcome:
    status: Literal["handed_off", "sent", "failed", "unknown"]
    provider_message_id: str | None = None
    evidence: Evidence | None = None
    error: str | None = None


@runtime_checkable
class Channel(Protocol):
    name: ClassVar[ChannelName]
    enforcement: ClassVar[Enforcement]

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        """Send (email), hand to a runner (browser), or prepare the bundle (manual)."""
        ...

    async def cancel(self, attempt_id: str) -> bool:
        """Cancel before hand-off. Returns False if it is too late."""
        ...

    async def reconcile(self, attempt_id: str) -> DispatchOutcome:
        """Find out what happened to an attempt without an outcome (sent items, confirmations)."""
        ...
