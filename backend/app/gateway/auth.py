"""Runner tokens (DESIGN.md 8.3; CONTRACTS.md 8). Invariants, never settings:

- A token is ``nch_`` plus 256 random bits, shown once. Only its sha256 is stored (a high-entropy
  secret needs no slow hash, and the lookup is by hash), with a short prefix for display.
- Each token is one runner identity with a declared kind (``pc`` or ``server``); ``last_used_at`` is its
  last-seen heartbeat.
- Scopes: ``gateway:tasks`` (apply and check tasks), ``gateway:packets`` (packets, answers, files),
  ``gateway:permits`` (submit permits), ``gateway:sweep`` (sweep tasks and reported jobs).
- A revoked token is refused outright. A suspended token (a submission without a permit was detected)
  may still report what it did, but gets no tasks, packets, answers or permits.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.applications import AgentTask, AgentTaskStatus
from app.models.platform import ApiToken

TOKEN_PREFIX = "nch_"
PREFIX_LEN = 12
SCOPES = ("gateway:tasks", "gateway:packets", "gateway:permits", "gateway:sweep")
RUNNER_KINDS = ("pc", "server")


@dataclass(frozen=True)
class NewToken:
    row: ApiToken
    secret: str


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(TOKEN_PREFIX):
        return None
    return value


def actor(token: ApiToken) -> str:
    """The audit actor for a runner (CONTRACTS 11: the runner token name)."""
    return f"runner:{token.name}"


async def create(session: AsyncSession, *, name: str, runner_kind: str, scopes: list[str], by: str) -> NewToken:
    if runner_kind not in RUNNER_KINDS:
        raise ValueError(f"unknown runner kind {runner_kind!r}")
    unknown = sorted(set(scopes) - set(SCOPES))
    if unknown or not scopes:
        raise ValueError(f"scopes must be some of {list(SCOPES)}")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(name=name.strip(), token_hash=hash_token(secret), prefix=secret[:PREFIX_LEN],
                   scopes=sorted(set(scopes)), runner_kind=runner_kind)
    session.add(row)
    await session.flush()
    await audit.record(session, actor=by, action="gateway.token_created", subject_type="api_token", subject_id=row.id,
                       detail={"name": row.name, "runner_kind": runner_kind, "scopes": row.scopes,
                               "prefix": row.prefix})
    return NewToken(row, secret)


async def authenticate(session: AsyncSession, raw: str | None) -> ApiToken | None:
    """The live (not revoked) token for a bearer value, or None."""
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    token = await session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None:
        return None
    return token


async def release_tasks(session: AsyncSession, token: ApiToken, *, why: str, now: datetime,
                        keep: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Put the tasks a token holds back in the queue (from their checkpoints) for any runner."""
    rows = (await session.execute(
        update(AgentTask).where(AgentTask.claimed_by_token_id == token.id,
                                AgentTask.status == AgentTaskStatus.claimed,
                                *([AgentTask.id != keep] if keep else []))
        .values(status=AgentTaskStatus.queued, claimed_by_token_id=None, claimed_at=None, heartbeat_at=None)
        .returning(AgentTask.id))).scalars().all()
    for task_id in rows:
        await audit.record(session, actor="system", action="gateway.task_released", subject_type="agent_task",
                           subject_id=task_id, detail={"runner": token.name, "reason": why, "at": now.isoformat()})
    return list(rows)


async def revoke(session: AsyncSession, token: ApiToken, *, by: str, now: datetime) -> None:
    if token.revoked_at is None:
        token.revoked_at = now
        await release_tasks(session, token, why="token revoked", now=now)
        await audit.record(session, actor=by, action="gateway.token_revoked", subject_type="api_token",
                           subject_id=token.id, detail={"name": token.name})
    await session.flush()


async def suspend(session: AsyncSession, token: ApiToken, *, reason: str, now: datetime,
                  keep: uuid.UUID | None = None) -> None:
    if token.suspended_at is None:
        token.suspended_at, token.suspended_reason = now, reason[:2000]
        await release_tasks(session, token, why="runner suspended", now=now, keep=keep)
        await audit.record(session, actor="system", action="gateway.token_suspended", subject_type="api_token",
                           subject_id=token.id, detail={"name": token.name, "reason": reason})
    await session.flush()


async def reinstate(session: AsyncSession, token: ApiToken, *, by: str, note: str | None = None) -> None:
    """Lift a suspension. The caller has the owner's explicit acknowledgement (the API requires it)."""
    if token.revoked_at is not None:
        raise ValueError("a revoked token cannot be reinstated; create a new one")
    if token.suspended_at is not None:
        reason = token.suspended_reason
        token.suspended_at = token.suspended_reason = None
        await audit.record(session, actor=by, action="gateway.token_reinstated", subject_type="api_token",
                           subject_id=token.id, detail={"name": token.name, "was_suspended_for": reason,
                                                        "acknowledged": True, "note": note})
    await session.flush()
