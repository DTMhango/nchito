"""Append-only audit trail.

``record`` adds an ``AuditEvent`` to the caller's session so the audit row commits or rolls back
with the change it describes. The table rejects UPDATE and DELETE at the database.
Secrets never enter the trail: keys that look secret are redacted.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import AuditEvent

_SECRET_KEY_RE = re.compile(r"(password|secret|token|api[_-]?key|totp|authorization|cookie)", re.I)
REDACTED = "***"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if _SECRET_KEY_RE.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


async def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    subject_type: str | None = None,
    subject_id: object | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=str(subject_id) if subject_id is not None else None,
        detail=redact(detail or {}),
        ip=ip,
    )
    session.add(event)
    await session.flush()
    return event
