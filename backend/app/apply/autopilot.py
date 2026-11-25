"""Global Autopilot switch (DESIGN.md 8.1): Running / Paused, backed by the
``automation.paused`` setting (versioned and audited by the settings service).

Pausing stops every new outward action at once. The pause report lists what was cancelled
(queued sends), paused (agent tasks) and already out (handed to a provider or submitted,
cannot be recalled). In wave 0 nothing can be queued yet, so the lists are empty; the apply
stream (wave 2) fills them by implementing ``collect_pause_effects`` against
``DispatchAttempt`` and ``AgentTask`` and must keep the response shape.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import service as settings_service
from app.models.platform import Setting

PAUSED_KEY = "automation.paused"


class PauseItem(BaseModel):
    id: str
    label: str
    detail: str


class PauseSummary(BaseModel):
    cancelled: list[PauseItem] = Field(default_factory=list, description="Queued sends cancelled")
    paused: list[PauseItem] = Field(default_factory=list, description="Agent tasks paused")
    already_out: list[PauseItem] = Field(default_factory=list,
                                         description="Handed to a provider or submitted; cannot be recalled")


class AutopilotState(BaseModel):
    paused: bool
    paused_at: datetime | None
    summary: PauseSummary = Field(description="What the last pause did. Empty until something has been queued")


class AutopilotWrite(BaseModel):
    paused: bool


async def collect_pause_effects(session: AsyncSession) -> PauseSummary:
    """Cancel queued sends and pause agent tasks; report what could not be recalled.
    Wave 0 has no dispatch or agent tasks, so there is nothing to act on."""
    return PauseSummary()


async def read_state(session: AsyncSession, summary: PauseSummary | None = None) -> AutopilotState:
    paused = bool(await settings_service.get_value(session, PAUSED_KEY))
    paused_at = None
    if paused:
        row = await session.scalar(select(Setting).where(Setting.key == PAUSED_KEY))
        paused_at = row.updated_at if row else None
    return AutopilotState(paused=paused, paused_at=paused_at, summary=summary or PauseSummary())


async def set_paused(session: AsyncSession, paused: bool, *, actor: str) -> AutopilotState:
    summary = PauseSummary()
    if paused:
        summary = await collect_pause_effects(session)
    await settings_service.set_value(session, PAUSED_KEY, paused, actor=actor,
                                     reason="autopilot paused" if paused else "autopilot resumed")
    return await read_state(session, summary)
