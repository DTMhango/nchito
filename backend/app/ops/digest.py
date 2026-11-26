"""The digest: a plain-text summary of a period, sent through the configured notifiers.

``render_digest`` is pure reading (no writes) and is what the email channel also calls to build
its message. ``send_digest_if_due`` decides when (after the daily sweep, or at a morning time,
or never; a setting), and hands the text to ``ops.notifications.notify`` with one idempotency key
per local day, so a restart or a second worker cannot send it twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm.money import micros_to_minor
from app.models.applications import Application, MailThread, PendingAction, PendingStatus
from app.models.platform import LedgerEntry, LedgerKind, Notification
from app.models.search import Assessment, AssessmentState, Job, Run, RunKind, RunStatus
from app.ops import notifications

DEFAULT_WINDOW = timedelta(hours=24)


@dataclass
class Digest:
    title: str
    body: str
    counts: dict[str, int] = field(default_factory=dict)
    is_empty: bool = True


def _money(micros: int, currency: str) -> str:
    return f"{micros / 1_000_000:,.2f} {currency}"


async def render_digest(session: AsyncSession, *, since: datetime, until: datetime | None = None,
                        values: dict[str, Any] | None = None, titles: bool | None = None) -> Digest:
    """Build the digest for [since, until). ``titles=False`` lists counts only (generic detail level)."""
    until = until or utcnow()
    values = values or await settings_service.values(session)
    tz = ZoneInfo(values["general.timezone"])
    limit = int(values["notifications.digest_max_items"])
    show_titles = (values["notifications.detail_level"] == "titles") if titles is None else titles
    threshold = int(values["scoring.threshold_shortlist"])
    currency = str(values["budget.currency"])

    matches = (await session.execute(
        select(Assessment.score, Job.title, Job.employer).join(Job, Job.id == Assessment.job_id).where(
            Assessment.state == AssessmentState.scored, Assessment.score >= threshold,
            Assessment.created_at >= since, Assessment.created_at < until)
        .order_by(Assessment.score.desc(), Job.title).limit(1000))).all()
    new_jobs = int(await session.scalar(select(func.count()).select_from(Job).where(
        Job.created_at >= since, Job.created_at < until)) or 0)
    needs = (await session.scalars(select(PendingAction).where(PendingAction.status == PendingStatus.open)
                                   .order_by(PendingAction.deadline.asc().nulls_last(), PendingAction.created_at)
                                   )).all()
    sent = (await session.execute(
        select(Job.title, Job.employer).join(Application, Application.job_id == Job.id).where(
            Application.applied_at >= since, Application.applied_at < until, Application.origin == "system")
        .order_by(Application.applied_at))).all()
    replies = int(await session.scalar(select(func.count()).select_from(MailThread).where(
        MailThread.created_at >= since, MailThread.created_at < until, MailThread.classification != "other")) or 0)
    period_spend = int(await session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0)).where(
        LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.billed.is_(True),
        LedgerEntry.created_at >= since, LedgerEntry.created_at < until)) or 0)

    counts = {"new_jobs": new_jobs, "matches": len(matches), "needs_you": len(needs), "sent": len(sent),
              "replies": replies, "spend_micros": period_spend, "spend_minor": micros_to_minor(period_spend)}
    lines = [f"New roles found: {new_jobs}", f"New matches (score {threshold}+): {len(matches)}"]
    if show_titles:
        lines += [f"  {score}  {title}, {employer}" for score, title, employer in matches[:limit]]
        if len(matches) > limit:
            lines.append(f"  and {len(matches) - limit} more")
    lines.append(f"Needs you: {len(needs)}")
    if show_titles:
        lines += [f"  {pa.title}" for pa in needs[:limit]]
        if len(needs) > limit:
            lines.append(f"  and {len(needs) - limit} more")
    lines.append(f"Applications sent: {len(sent)}")
    if show_titles:
        lines += [f"  {title}, {employer}" for title, employer in sent[:limit]]
    lines.append(f"Replies: {replies}")
    lines.append(f"AI spend this period: {_money(period_spend, currency)}")
    is_empty = not (new_jobs or matches or needs or sent or replies or period_spend)
    date_text = until.astimezone(tz).date().isoformat()
    title = str(values["notifications.digest_title"]).format(app_name=values["general.app_name"], date=date_text,
                                                             count=len(matches) + len(needs))
    return Digest(title=title, body="\n".join(lines), counts=counts, is_empty=is_empty)


async def _last_digest_at(session: AsyncSession) -> datetime | None:
    return await session.scalar(select(func.max(Notification.created_at)).where(Notification.kind == "digest"))


async def digest_due(session: AsyncSession, now: datetime, values: dict[str, Any]) -> str | None:
    """The local-date key if a digest is due now and not yet created today, else ``None``."""
    mode = values["notifications.digest"]
    if mode == "off" or not values["notifications.channels"]:
        return None
    tz = ZoneInfo(values["general.timezone"])
    local = now.astimezone(tz)
    day = local.date().isoformat()
    if await session.scalar(select(Notification.id).where(Notification.dedupe_key == f"digest:{day}")):
        return None
    if mode == "morning":
        hour, minute = (int(p) for p in values["notifications.digest_time"].split(":"))
        return day if (local.hour, local.minute) >= (hour, minute) else None
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))
    swept = await session.scalar(select(Run.id).where(
        Run.kind == RunKind.sweep, Run.status.in_((RunStatus.succeeded, RunStatus.partial)),
        Run.finished_at >= day_start).limit(1))
    return day if swept else None


async def send_digest_if_due(session: AsyncSession, now: datetime | None = None) -> bool:
    """Create today's digest notification when due. Delivery (quiet hours, retries) is ``deliver_due``'s job."""
    now = now or utcnow()
    values = await settings_service.values(session)
    day = await digest_due(session, now, values)
    if day is None:
        return False
    since = await _last_digest_at(session) or now - DEFAULT_WINDOW
    digest = await render_digest(session, since=since, until=now, values=values)
    if digest.is_empty and values["notifications.digest_skip_empty"]:
        return False
    created = await notifications.notify(session, kind="digest", key=f"digest:{day}", title=digest.title,
                                         body=digest.body, link="/today", payload={"counts": digest.counts})
    return created is not None
