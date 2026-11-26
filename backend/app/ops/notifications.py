"""Notifications: from events to messages on the owner's channels. DESIGN.md 12, 14.

Flow: ``collect`` turns what already happened (open pending actions, sent applications, replies,
failed runs, budget notices) into ``Notification`` rows, one per event (the ``dedupe_key`` is the
idempotency key, enforced by a unique index and ``ON CONFLICT DO NOTHING``). ``deliver_due`` then
sends each undelivered row to every configured channel.

Rules enforced here:
- Which kinds notify, quiet hours, wording and the detail level are settings.
- A message holds a title, a short body and links. It never holds ``payload``, secrets, answers,
  pay figures or posting text. Title and body are scrubbed for secret-looking strings.
- Delivery failures are recorded on the row and retried within bounds; they never raise to the
  caller, so a broken Telegram bot cannot fail a sweep.
- A channel that already accepted a message is never sent it again (``channels_sent``), and rows
  are claimed with ``FOR UPDATE SKIP LOCKED`` so two workers cannot send the same one.
- Quiet hours hold a message; it is sent when they end.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import records as _records  # noqa: F401  (registers the telegram and webhook notifiers)
from app.connect.notifier import Button, DeliveryError, OutboundMessage, notifier_for
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.models.applications import Application, MailThread, PendingAction, PendingStatus, Stage
from app.models.platform import AuditEvent, Notification
from app.models.search import Job, Run, RunStatus

log = logging.getLogger(__name__)

DELIVERY_KEY = "_delivery"
FINAL_STATES = ("done", "gave_up", "skipped")
GENERIC_TITLES = {
    "pending_action": "Something needs you",
    "pending_action_stale": "Something is still waiting for you",
    "application_sent": "An application was sent",
    "reply_received": "A reply arrived",
    "run_failed": "A run failed",
    "budget": "Budget notice",
    "health": "Health notice",
    "backup": "Backup notice",
    "digest": "Your digest is ready",
}
NEEDS_YOU_KINDS = ("pending_action", "pending_action_stale")
MAX_BODY = 400
MAX_DIGEST_BODY = 3500
MAX_TITLE = 200
_SECRET_LIKE = re.compile(
    r"(sk-[A-Za-z0-9_-]{10,}|Bearer\s+\S+|\b\d{6,}:[A-Za-z0-9_-]{20,}\b|\b[A-Za-z0-9+/_-]{40,}\b)")


def scrub(text: str | None) -> str | None:
    """Mask anything that looks like a key or token."""
    return _SECRET_LIKE.sub("[hidden]", text) if text else text


# ----- time ----------------------------------------------------------------------------------


def _hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def in_quiet_hours(now: datetime, tz: ZoneInfo, start: str, end: str) -> bool:
    """True when ``now`` is inside [start, end) in ``tz``; the window may wrap midnight; equal means none."""
    local = now.astimezone(tz).time().replace(second=0, microsecond=0)
    s, e = _hhmm(start), _hhmm(end)
    if s == e:
        return False
    return s <= local < e if s < e else (local >= s or local < e)


# ----- creating notifications ----------------------------------------------------------------


async def notify(session: AsyncSession, *, kind: str, key: str, title: str, body: str | None = None,
                 link: str | None = None, payload: dict[str, Any] | None = None) -> uuid.UUID | None:
    """Record one notification. A repeat of the same ``key`` is ignored (returns ``None``)."""
    stmt = insert(Notification).values(
        id=uuid.uuid4(), kind=kind, title=title[:MAX_TITLE], body=body[:MAX_DIGEST_BODY] if body else None, link=link,
        payload=payload or {}, channels_sent=[], dedupe_key=key[:200]
    ).on_conflict_do_nothing(index_elements=[Notification.dedupe_key]).returning(Notification.id)
    return await session.scalar(stmt)


@dataclass
class CollectResult:
    created: int = 0


async def collect(session: AsyncSession, now: datetime | None = None) -> CollectResult:
    """Create notification rows for recent events. Nothing is created while no channel is configured."""
    now = now or utcnow()
    values = await settings_service.values(session)
    result = CollectResult()
    if not values["notifications.channels"]:
        return result
    cutoff = now - timedelta(hours=values["notifications.lookback_hours"])
    enabled = set(values["notifications.events"])

    async def add(**kw: Any) -> None:
        if kw["kind"] in enabled and await notify(session, **kw):
            result.created += 1

    if "pending_action" in enabled:
        rows = await session.scalars(select(PendingAction).where(
            PendingAction.status == PendingStatus.open, PendingAction.created_at >= cutoff))
        for pa in rows:
            if pa.snoozed_until is not None and pa.snoozed_until > now:
                continue
            await add(kind="pending_action", key=f"pending:{pa.id}", title=pa.title,
                      body=pa.type.value.replace("_", " ").capitalize()
                      + (f", due {pa.deadline.date().isoformat()}" if pa.deadline else ""),
                      link=f"/today?action={pa.id}",
                      payload={"pending_action_id": str(pa.id), "action_type": pa.type.value})

    if "application_sent" in enabled:
        sent = await session.execute(
            select(Application, Job).join(Job, Job.id == Application.job_id).where(
                Application.applied_at.is_not(None), Application.applied_at >= cutoff, Application.origin == "system",
                Application.stage.in_((Stage.submitted, Stage.submitted_unconfirmed))))
        for app, job in sent.all():
            await add(kind="application_sent", key=f"sent:{app.id}", title=f"Sent: {job.title} at {job.employer}",
                      link=f"/jobs/{job.id}", payload={"application_id": str(app.id)})

    if "reply_received" in enabled:
        threads = await session.scalars(select(MailThread).where(
            MailThread.created_at >= cutoff, MailThread.classification != "other",
            MailThread.application_id.is_not(None)))
        for th in threads:
            await add(kind="reply_received", key=f"reply:{th.id}:{th.classification.value}",
                      title=f"Reply ({th.classification.value}) to an application",
                      link=f"/applications?application={th.application_id}",
                      payload={"mail_thread_id": str(th.id)})

    if "run_failed" in enabled:
        runs = await session.scalars(select(Run).where(
            Run.status == RunStatus.failed, Run.finished_at.is_not(None), Run.finished_at >= cutoff))
        for run in runs:
            await add(kind="run_failed", key=f"run-failed:{run.id}", title=f"A {run.kind.value} run failed",
                      body=None, link="/settings/schedule", payload={"run_id": str(run.id)})

    if "budget" in enabled:
        events = await session.scalars(select(AuditEvent).where(
            AuditEvent.created_at >= cutoff, or_(AuditEvent.action == "budget.warning",
                                                 AuditEvent.action.startswith("budget.exhausted"))))
        for ev in events:
            exhausted = ev.action.startswith("budget.exhausted")
            await add(kind="budget", key=f"audit:{ev.id}",
                      title="AI budget used up" if exhausted else "AI budget warning",
                      body="Paid work is paused until the cap changes or the month ends." if exhausted
                      else "Spend is close to the monthly cap.", link="/settings/ai",
                      payload={"audit_event_id": str(ev.id)})
    return result


# ----- composing a message -------------------------------------------------------------------


def _absolute(link: str | None) -> str | None:
    if not link:
        return None
    base = get_config().base_url.rstrip("/")
    if link.startswith("/"):
        return base + link
    return link if link.startswith(get_config().base_origin) else None


def compose(n: Notification, values: dict[str, Any], app_name: str, now: datetime) -> OutboundMessage:
    """The only fields that ever leave the server: title, short body, links."""
    fields = {"app_name": app_name, "date": now.date().isoformat(), "count": "1"}
    generic = values["notifications.detail_level"] == "generic" and n.kind != "digest"
    raw_title = GENERIC_TITLES.get(n.kind, "Notice") if generic else (scrub(n.title) or "Notice")
    if n.kind == "digest":
        title = raw_title
    else:
        template = values["notifications.needs_you_title" if n.kind in NEEDS_YOU_KINDS else "notifications.alert_title"]
        title = str(template).format(title=raw_title, **fields)
    limit = MAX_DIGEST_BODY if n.kind == "digest" else MAX_BODY
    body = None if generic else (scrub(n.body)[:limit] if n.body else None)
    link = _absolute(n.link)
    buttons: list[Button] = []
    if link:
        buttons.append(Button("Open", link))
        if n.kind == "pending_action" and n.payload.get("action_type") == "approve":
            buttons.insert(0, Button("Approve", link + ("&" if "?" in link else "?") + "intent=approve"))
        if n.kind == "pending_action" and n.payload.get("action_type") in ("sign_in", "create_account", "captcha"):
            sep = "&" if "?" in link else "?"
            buttons.insert(0, Button("I've signed in, continue", f"{link}{sep}intent=continue"))
    return OutboundMessage(event_id=n.dedupe_key or str(n.id), kind=n.kind, title=title[:MAX_TITLE], body=body,
                           created_at=n.created_at, link=link, buttons=tuple(buttons))


# ----- delivery ------------------------------------------------------------------------------


def _state(n: Notification) -> dict[str, Any]:
    raw = n.payload.get(DELIVERY_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _set_state(n: Notification, **state: Any) -> None:
    n.payload = {**n.payload, DELIVERY_KEY: {**_state(n), **state}}


def _undelivered(cutoff: datetime, exclude: set[uuid.UUID]) -> Any:
    state = Notification.payload[DELIVERY_KEY]["state"].astext
    stmt = select(Notification).where(
        Notification.created_at >= cutoff, or_(state.is_(None), state.notin_(FINAL_STATES))
    ).order_by(Notification.created_at).limit(1).with_for_update(skip_locked=True)
    return stmt.where(Notification.id.notin_(exclude)) if exclude else stmt


@dataclass
class DeliveryResult:
    sent: int = 0
    held: int = 0
    failed: int = 0
    skipped: int = 0


async def _deliver_one(session: AsyncSession, n: Notification, values: dict[str, Any], app_name: str,
                       now: datetime, quiet: bool, result: DeliveryResult) -> None:
    channels: list[str] = list(values["notifications.channels"])
    if n.kind != "digest" and n.kind not in values["notifications.events"]:
        _set_state(n, state="skipped", reason="event not enabled")
        result.skipped += 1
        return
    if not channels:
        _set_state(n, state="skipped", reason="no channel configured")
        result.skipped += 1
        return
    st = _state(n)
    wait_until = st.get("next_attempt_at")
    if wait_until and datetime.fromisoformat(wait_until) > now:
        result.held += 1
        return
    if quiet:
        _set_state(n, state="pending", held="quiet hours")
        result.held += 1
        return
    message = compose(n, values, app_name, now)
    attempts = int(st.get("attempts", 0))
    errors: dict[str, str] = {}
    sent = list(n.channels_sent)
    for channel in channels:
        if channel in sent:
            continue
        notifier = await notifier_for(session, channel)
        if notifier is None:
            errors[channel] = "not connected"
            continue
        try:
            await notifier.send(message)
        except DeliveryError as exc:
            errors[channel] = exc.detail[:200]
            if not exc.retryable:
                attempts = max(attempts, values["notifications.retry_attempts"] - 1)
        except Exception as exc:  # a broken connector must never fail the caller
            log.exception("notifier %s crashed", channel)
            errors[channel] = f"{type(exc).__name__}"
        else:
            sent.append(channel)
            result.sent += 1
    n.channels_sent = sent
    if not errors:
        _set_state(n, state="done", delivered_at=now.isoformat(), held=None, errors=None)
        return
    attempts += 1
    result.failed += 1
    if attempts >= values["notifications.retry_attempts"]:
        _set_state(n, state="gave_up", attempts=attempts, errors=errors)
        await audit.record(session, actor="system", action="notification.delivery_failed",
                           subject_type="notification", subject_id=n.id, detail={"kind": n.kind, "errors": errors})
        return
    wait = timedelta(minutes=values["notifications.retry_minutes"] * 2 ** (attempts - 1))
    _set_state(n, state="pending", attempts=attempts, errors=errors, next_attempt_at=(now + wait).isoformat())


async def deliver_due(session: AsyncSession, now: datetime | None = None, *, limit: int = 50) -> DeliveryResult:
    """Send undelivered notifications. Commits after each row (releases its lock, records the outcome)."""
    now = now or utcnow()
    values = await settings_service.values(session)
    result = DeliveryResult()
    if not values["notifications.channels"]:
        return result
    tz = ZoneInfo(values["general.timezone"])
    quiet = values["notifications.quiet_hours_enabled"] and in_quiet_hours(
        now, tz, values["notifications.quiet_hours_start"], values["notifications.quiet_hours_end"])
    cutoff = now - timedelta(hours=values["notifications.lookback_hours"])
    app_name = str(values["general.app_name"])
    seen: set[uuid.UUID] = set()
    for _ in range(limit):
        n = await session.scalar(_undelivered(cutoff, seen))
        if n is None:
            break
        seen.add(n.id)
        try:
            await _deliver_one(session, n, values, app_name, now, quiet, result)
        except Exception:
            log.exception("delivery of notification %s failed unexpectedly", n.id)
            await session.rollback()
            continue
        await session.commit()
    return result
