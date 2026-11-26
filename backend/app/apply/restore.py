"""Paused for restore (DESIGN.md 18.3, RUNBOOK "Backups and restore"). Invariants, not settings:

A database restored from a backup does not know what the old instance sent after the backup. So:

- :func:`enter` (called by the restore procedure: ``python -m app.cli restored`` or the backups module)
  pauses everything, revokes outstanding permits, marks every attempt that was in flight at backup time
  (reserved, handed off or unknown) as uncertain so it is reconciled against the channel (the mailbox's
  sent items find a message by its attempt id), and withdraws every approval of a role that was ready to
  go but not yet sent (the old instance may have sent it after the backup with an attempt this database
  never saw): the owner is asked to approve it again.
- :func:`resume` is refused while any attempt of that set is still uncertain. Only then does sending
  resume. The ordinary Autopilot switch cannot resume while paused for a restore.
- The state is the append-only audit (``restore.paused`` / ``restore.resumed``): it cannot be edited.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import approval, outcomes, packets, permits
from app.apply.channels.base import DispatchOutcome
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import Application, DispatchAttempt, DispatchStatus, Stage
from app.models.platform import AuditEvent

RESTORE_ACTOR = "system:restore"
PAUSED, RESUMED = "restore.paused", "restore.resumed"


class RestoreError(Exception):
    def __init__(self, message: str, status: int = 409, outstanding: list[uuid.UUID] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.outstanding = outstanding or []


@dataclass
class RestoreState:
    active: bool
    entered_at: datetime | None = None
    backup_taken_at: str | None = None
    attempt_ids: list[uuid.UUID] = field(default_factory=list)
    outstanding: list[DispatchAttempt] = field(default_factory=list)
    held_application_ids: list[uuid.UUID] = field(default_factory=list)


async def state(session: AsyncSession) -> RestoreState:
    latest = await session.scalar(select(AuditEvent).where(AuditEvent.action.in_((PAUSED, RESUMED)))
                                  .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(1))
    if latest is None or latest.action == RESUMED:
        return RestoreState(active=False)
    ids = [uuid.UUID(i) for i in latest.detail.get("attempt_ids", [])]
    rows = (await session.scalars(select(DispatchAttempt).where(DispatchAttempt.id.in_(ids))
                                  .execution_options(populate_existing=True))).all() if ids else []
    return RestoreState(active=True, entered_at=latest.created_at, backup_taken_at=latest.detail.get("backup_taken_at"),
                        attempt_ids=ids, outstanding=[a for a in rows if outcomes.is_uncertain(a)],
                        held_application_ids=[uuid.UUID(i) for i in latest.detail.get("held_application_ids", [])])


async def is_active(session: AsyncSession) -> bool:
    return (await state(session)).active


async def enter(session: AsyncSession, *, backup_taken_at: datetime | None = None, actor: str = RESTORE_ACTOR,
                now: datetime | None = None) -> RestoreState:
    """Start paused for a restore. The caller commits."""
    now = now or utcnow()
    await permits.lock_permits(session)
    await settings_service.set_value(session, "automation.paused", True, actor=actor,
                                     reason="started from a restored backup: reconcile before resuming")
    await permits.revoke(session, reason="restored from a backup", actor=actor, now=now)
    attempts = (await session.scalars(select(DispatchAttempt).where(
        DispatchAttempt.status.in_(outcomes.OPEN_STATUSES)).order_by(DispatchAttempt.created_at))).all()
    for attempt in attempts:
        if attempt.status == DispatchStatus.reserved:
            attempt.started_at = attempt.started_at or now
            await outcomes.record(session, attempt, DispatchOutcome(
                status="unknown", error="restored from a backup: it may have been sent after the backup"),
                via="restore", actor=actor, now=now)
        attempt.last_reconciled_at = None  # check it at once
    held = []
    ready = (await session.scalars(select(Application).where(
        Application.stage == Stage.ready, Application.approved_packet_id.is_not(None)))).all()
    for app in ready:
        packet = await packets.current(session, app.id)
        app.approved_packet_id = None
        held.append(app.id)
        if packet is not None:
            await approval.request_owner_approval(
                session, app, packet, "restored from a backup: check this was not sent after the backup, then "
                                      "approve it again")
    await session.flush()
    await audit.record(session, actor=actor, action=PAUSED, subject_type="instance", detail={
        "backup_taken_at": backup_taken_at.isoformat() if backup_taken_at else None,
        "attempt_ids": [str(a.id) for a in attempts], "held_application_ids": [str(i) for i in held]})
    return await state(session)


async def resume(session: AsyncSession, *, actor: str, now: datetime | None = None) -> RestoreState:
    """Resume after a restore, once every attempt in flight at backup time is settled."""
    current = await state(session)
    if not current.active:
        raise RestoreError("the instance is not paused for a restore")
    if current.outstanding:
        raise RestoreError(f"{len(current.outstanding)} send(s) from before the backup are not reconciled yet",
                           outstanding=[a.id for a in current.outstanding])
    await settings_service.set_value(session, "automation.paused", False, actor=actor,
                                     reason="resumed after the restore was reconciled")
    await audit.record(session, actor=actor, action=RESUMED, subject_type="instance",
                       detail={"attempt_ids": [str(i) for i in current.attempt_ids]})
    return RestoreState(active=False)
