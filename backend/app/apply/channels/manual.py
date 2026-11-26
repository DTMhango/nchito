"""Manual handoff channel (DESIGN.md 8.2, 18.1): the owner submits.

``dispatch`` only hands the bundle to the owner (``handed_off``, no evidence); the owner's
``mark-submitted`` (with the reference, if any) records the outcome. ``reconcile`` cannot find out on
its own what the owner did, so it stays ``unknown`` and the owner is asked.
"""

from __future__ import annotations

from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply.channels.base import ChannelName, DispatchOutcome, DispatchRequest, Enforcement


class ManualChannel:
    name: ClassVar[ChannelName] = "manual"
    enforcement: ClassVar[Enforcement] = "owner"

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        return DispatchOutcome(status="handed_off")

    async def cancel(self, attempt_id: str) -> bool:
        return True  # nothing leaves until the owner submits

    async def reconcile(self, attempt_id: str) -> DispatchOutcome:
        return DispatchOutcome(status="unknown", error="only the owner knows whether it was submitted")


async def factory(session: AsyncSession) -> ManualChannel:
    return ManualChannel()
