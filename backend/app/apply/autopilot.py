"""Global Autopilot switch (DESIGN.md 8.1): Running / Paused, backed by the
``automation.paused`` setting (versioned and audited by the settings service).

Pausing stops every new outward action at once: every outstanding submit permit is revoked (and
the permit gate refuses new ones while paused), queued sends that no provider has yet are
cancelled, open apply tasks are reported as paused (runners cannot obtain a permit), and attempts
already handed to a provider or of unknown outcome are listed as out (they cannot be recalled).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    Application,
    DispatchAttempt,
    DispatchStatus,
)
from app.models.platform import Setting, SettingRevision
from app.models.search import Job

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
    paused_by: str | None = Field(default=None, description="Who paused (owner, system or a runner name)")
    reason: str | None = Field(default=None, description="Why it was paused, as given")
    summary: PauseSummary = Field(description="What the last pause did. Empty until something has been queued")


class AutopilotWrite(BaseModel):
    paused: bool
    reason: str | None = Field(default=None, max_length=500)


async def collect_pause_effects(session: AsyncSession, *, actor: str = "system") -> PauseSummary:
    """Revoke permits, cancel queued sends and report paused tasks and what could not be recalled."""
    from app.apply import outcomes, permits  # permits -> gates -> pipeline; keep this module light to import

    now = utcnow()
    await permits.lock_permits(session)
    await permits.revoke(session, reason="autopilot paused", actor=actor, now=now)
    await permits.release_stale_claims(session, now=now)
    summary = PauseSummary()
    rows = (await session.execute(
        select(DispatchAttempt, Job).join(Application, Application.id == DispatchAttempt.application_id)
        .join(Job, Job.id == Application.job_id)
        .where(DispatchAttempt.status.in_((DispatchStatus.reserved, DispatchStatus.handed_off,
                                           DispatchStatus.unknown)))
        .order_by(DispatchAttempt.created_at))).all()
    for attempt, job in rows:
        label = f"{job.title} at {job.employer}"
        if attempt.status == DispatchStatus.reserved and attempt.started_at is None:
            app = await outcomes.lock_application(session, attempt.application_id)
            await outcomes.cancel(session, attempt, app, "cancelled: autopilot paused", actor=actor, now=now)
            summary.cancelled.append(PauseItem(id=str(attempt.id), label=label,
                                               detail=f"{attempt.channel.value} send cancelled before hand-off"))
        else:
            state = "in flight" if attempt.status == DispatchStatus.reserved else attempt.status.value
            summary.already_out.append(PauseItem(id=str(attempt.id), label=label,
                                                 detail=f"{attempt.channel.value}: {state}"))
    tasks = (await session.scalars(select(AgentTask).where(
        AgentTask.type == AgentTaskType.apply,
        AgentTask.status.in_((AgentTaskStatus.queued, AgentTaskStatus.claimed))))).all()
    for task in tasks:
        summary.paused.append(PauseItem(id=str(task.id), label=f"apply task {task.status.value}",
                                        detail="no submit permit is granted while paused"))
    await session.flush()
    return summary


async def read_state(session: AsyncSession, summary: PauseSummary | None = None) -> AutopilotState:
    paused = bool(await settings_service.get_value(session, PAUSED_KEY))
    paused_at = paused_by = reason = None
    if paused:
        # The pause is a versioned setting: its latest revision says who, when and why.
        rev = await session.scalar(select(SettingRevision).where(SettingRevision.key == PAUSED_KEY)
                                   .order_by(SettingRevision.version.desc()).limit(1))
        if rev is not None:
            paused_at, paused_by, reason = rev.created_at, rev.changed_by, rev.reason
        else:
            row = await session.scalar(select(Setting).where(Setting.key == PAUSED_KEY))
            paused_at = row.updated_at if row else None
    return AutopilotState(paused=paused, paused_at=paused_at, paused_by=paused_by, reason=reason,
                          summary=summary or PauseSummary())


class ResumeRefused(Exception):
    """Resuming while paused for a restore goes through ``resume-after-restore`` (18.3)."""


async def set_paused(session: AsyncSession, paused: bool, *, actor: str, reason: str | None = None) -> AutopilotState:
    from app.apply import restore

    if not paused and await restore.is_active(session):
        raise ResumeRefused("paused for a restore from backup: reconcile, then use resume-after-restore")
    summary = PauseSummary()
    default = "autopilot paused" if paused else "autopilot resumed"
    await settings_service.set_value(session, PAUSED_KEY, paused, actor=actor, reason=(reason or "").strip() or default)
    if paused:
        summary = await collect_pause_effects(session, actor=actor)
    return await read_state(session, summary)
