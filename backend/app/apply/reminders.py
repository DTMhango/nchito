"""Follow-up and stale-pending reminders (DESIGN.md 8, 16: follow-up reminder after applying).

Run periodically by the worker (``app/worker/tracking_tasks.py``). Both functions are idempotent:
an application gets one follow-up action, and a pending action is flagged stale once.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings
from app.models.applications import Application, PendingAction, PendingActionType, PendingStatus, Stage
from app.models.platform import Notification
from app.models.search import Job

AWAITING_REPLY = (Stage.submitted_unconfirmed, Stage.submitted)


async def create_follow_up_reminders(session: AsyncSession, now: datetime | None = None) -> int:
    """Open a ``follow_up`` pending action for each application that has gone unanswered for
    ``automation.follow_up_days`` since it was sent (including ones the owner logged by hand)."""
    now = now or utcnow()
    days = int(await settings.get_value(session, "automation.follow_up_days"))
    cutoff = now - timedelta(days=days)
    rows = await session.execute(
        select(Application, Job).join(Job, Job.id == Application.job_id)
        .where(Application.stage.in_(AWAITING_REPLY), Application.applied_at.is_not(None),
               Application.applied_at <= cutoff))
    created = 0
    for app, job in rows.all():
        already = await session.scalar(select(PendingAction.id).where(
            PendingAction.application_id == app.id, PendingAction.type == PendingActionType.follow_up).limit(1))
        if already is not None:
            continue
        waited = (now - app.applied_at).days
        action = PendingAction(
            type=PendingActionType.follow_up, application_id=app.id,
            title=f"Follow up with {job.employer} about {job.title}",
            detail={"applied_at": app.applied_at.isoformat(), "days_waiting": waited, "follow_up_days": days,
                    "owner_attested": app.owner_attested},
            status=PendingStatus.open)
        session.add(action)
        await session.flush()
        await stages.add_event(session, app.id, "follow_up_due", "system",
                               {"pending_action_id": str(action.id), "days_waiting": waited})
        await publish(session, "pending_action.created", {"pending_action_id": str(action.id)})
        created += 1
    return created


async def remind_stale_pending(session: AsyncSession, now: datetime | None = None) -> int:
    """One notification per open pending action that has waited ``tracking.stale_pending_days``
    (snoozed actions are left alone until their snooze ends)."""
    now = now or utcnow()
    days = int(await settings.get_value(session, "tracking.stale_pending_days"))
    cutoff = now - timedelta(days=days)
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.status == PendingStatus.open, PendingAction.created_at <= cutoff))
    sent = 0
    for action in rows:
        if action.snoozed_until is not None and action.snoozed_until > now:
            continue
        if action.detail.get("stale_reminded_at"):
            continue
        waited = (now - action.created_at).days
        session.add(Notification(
            kind="pending_action_stale", title=f"Still waiting on you: {action.title}"[:200],
            body=f"Open for {waited} days.", link=f"/today?action={action.id}",
            payload={"pending_action_id": str(action.id), "days_waiting": waited},
            dedupe_key=f"pending-stale:{action.id}"))
        action.detail = {**action.detail, "stale_reminded_at": now.isoformat()}
        sent += 1
    await session.flush()
    return sent
