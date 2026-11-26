"""Shared pieces of the gateway: errors, the clock, task ownership and what every tool loads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import packets
from app.core.clock import Clock, SystemClock
from app.core.settings import service as settings_service
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    Application,
    ApplicationPacket,
)
from app.models.platform import ApiToken
from app.models.search import Job

MAX_TEXT = 2000  # bound on any free text a runner sends; it is stored as data, never followed

_clock: Clock = SystemClock()


def set_clock(clock: Clock | None) -> None:
    """Replace the gateway clock (tests)."""
    global _clock
    _clock = clock or SystemClock()


def now() -> datetime:
    return _clock.now()


class GatewayError(Exception):
    """A refused tool call. ``code`` is stable; the runner sees ``{"code", "reason"}``."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason

    def __str__(self) -> str:
        return json.dumps({"code": self.code, "reason": self.reason})


def clip(text: str | None, limit: int = MAX_TEXT) -> str | None:
    """Untrusted text, bounded and with control characters removed, for storage as data."""
    if text is None:
        return None
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    return cleaned[:limit]


def require_scope(token: ApiToken, scope: str) -> None:
    if scope not in (token.scopes or []):
        raise GatewayError("scope_missing", f"this token lacks the {scope} scope")


def require_active(token: ApiToken) -> None:
    if token.revoked_at is not None:
        raise GatewayError("token_revoked", "this token has been revoked")
    if token.suspended_at is not None:
        raise GatewayError("runner_suspended", f"this runner is suspended: {token.suspended_reason or 'see the app'}")


async def setting(session: AsyncSession, key: str) -> Any:
    return await settings_service.get_value(session, key)


async def lease_minutes(session: AsyncSession) -> int:
    return int(await setting(session, "runners.task_lease_minutes"))


def lease_expired(task: AgentTask, at: datetime, minutes: int) -> bool:
    beat = task.heartbeat_at or task.claimed_at
    return beat is None or beat <= at - timedelta(minutes=minutes)


def parse_id(raw: str, what: str = "task") -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise GatewayError("not_found", f"no such {what}") from exc


async def own_task(session: AsyncSession, token: ApiToken, task_id: str, *, at: datetime,
                   types: tuple[AgentTaskType, ...] | None = None) -> AgentTask:
    """The task, locked, when it is claimed by this runner and its lease holds. Touches the heartbeat."""
    task = await session.scalar(select(AgentTask).where(AgentTask.id == parse_id(task_id))
                                .with_for_update().execution_options(populate_existing=True))
    if task is None or task.claimed_by_token_id != token.id:
        raise GatewayError("not_your_task", "this task is not claimed by this runner")
    if task.status != AgentTaskStatus.claimed:
        raise GatewayError("task_not_active", f"this task is {task.status.value}")
    if lease_expired(task, at, await lease_minutes(session)):
        from app.gateway import tasks  # tasks imports this module

        await tasks.expire_one(session, task, at=at)
        raise GatewayError("lease_expired", "this task's lease expired; call next_task again")
    if types is not None and task.type not in types:
        raise GatewayError("wrong_task_type", f"not available for a {task.type.value} task")
    task.heartbeat_at = at
    return task


async def task_application(session: AsyncSession, task: AgentTask) -> tuple[Application, Job]:
    if task.application_id is None:
        raise GatewayError("no_application", "this task has no application")
    app = await session.get(Application, task.application_id)
    job = await session.get(Job, app.job_id) if app else None
    if app is None or job is None:
        raise GatewayError("no_application", "the application for this task is gone")
    return app, job


async def approved_packet(session: AsyncSession, app: Application) -> ApplicationPacket | None:
    """The current packet when it is the approved one for the browser channel; else None."""
    packet = await packets.current(session, app.id)
    if packet is None or packet.approved_at is None or app.approved_packet_id != packet.id \
            or packet.contents.channel != "browser":
        return None
    return packet


def same_site(domain: str | None, allowed: str | None) -> bool:
    """``domain`` is ``allowed`` or one of its subdomains."""
    if not domain or not allowed:
        return False
    return domain == allowed or domain.endswith(f".{allowed}")
