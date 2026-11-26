"""Guardrail waivers (DESIGN.md 5.3): the owner may waive a ``block, waivable once`` guardrail for ONE
application, with a reason. An ``always block`` rule can never be waived, and a rule that only advises
has nothing to waive. Every waiver is audited."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.models.applications import Application
from app.models.kit import Guardrail, GuardrailWaiver, Severity, Strictness


class WaiverError(ValueError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


async def create(session: AsyncSession, guardrail: Guardrail, application_id: uuid.UUID, reason: str, *,
                 actor: str) -> GuardrailWaiver:
    reason = reason.strip()
    if not reason:
        raise WaiverError("a reason is required to waive a guardrail", 422)
    if guardrail.strictness != Strictness.block_waivable_once or guardrail.severity != Severity.block:
        raise WaiverError("this guardrail cannot be waived: only 'block, waivable once' rules can")
    if await session.get(Application, application_id) is None:
        raise WaiverError("application not found", 404)
    existing = await session.scalar(select(GuardrailWaiver.id).where(
        GuardrailWaiver.guardrail_id == guardrail.id, GuardrailWaiver.application_id == application_id))
    if existing is not None:
        raise WaiverError("this guardrail is already waived for that application")
    row = GuardrailWaiver(guardrail_id=guardrail.id, application_id=application_id, reason=reason, waived_by=actor)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await audit.record(session, actor=actor, action="kit.guardrail.waived", subject_type="guardrail",
                       subject_id=guardrail.id, detail={"application_id": str(application_id), "reason": reason,
                                                        "guardrail": guardrail.name, "waiver_id": str(row.id)})
    return row


async def waived_ids(session: AsyncSession, application_id: uuid.UUID) -> set[str]:
    """Guardrail ids waived for this application (what ``guardrails.blocked(..., waived=)`` takes)."""
    rows = await session.scalars(select(GuardrailWaiver.guardrail_id).where(
        GuardrailWaiver.application_id == application_id))
    return {str(i) for i in rows.all()}
