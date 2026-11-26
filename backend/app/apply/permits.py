"""Submit permits (DESIGN.md 7.1, 8.1, 8.3, 18.1-18.3). Invariants, not settings:

- **Only through the decision table.** :func:`request` runs ``apply.gates.evaluate`` (purpose
  ``permit``) and issues a permit only when ``Decision.permit`` is ``granted``.
- **Bound** to one packet hash, its channel and the runner token (or no runner, for the server-side
  email channel). **Short-lived** (``automation.permit_valid_minutes``) and **single use**.
- **Serialised.** Issuing takes one transaction-scoped advisory lock for all permits (caps and
  outstanding permits are counted under it), the application row lock and the per-employer lock of
  7.1, so two runners cannot both obtain a permit for one application or one employer group.
- On a grant the application moves to ``applying`` in the same transaction (it is then live for the
  employer limit). An expired, unused permit gives the claim back (:func:`release_stale_claims`).
- **Consuming is atomic**: one conditional ``UPDATE ... WHERE used_at IS NULL AND expires_at > now``.
  Expired, used, revoked or mismatched permits refuse. The dispatch layer must consume the permit
  and write the ``DispatchAttempt`` in the same transaction.
- Every grant, refusal, consumption and revocation is in the append-only audit with the gates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import gates, stages
from app.apply.gates import Check, Evaluation
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    ApplicationPacket,
    DispatchAttempt,
    Stage,
    SubmitPermit,
)
from app.pipeline import conflicts
from app.schemas.json_types import GateResult

PERMIT_LOCK = "nchito:submit-permits"


class PermitRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class PermitResult:
    status: str  # granted | wait_for_owner | denied
    reason: str
    permit: SubmitPermit | None = None
    gates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def granted(self) -> bool:
        return self.status == "granted"

    @property
    def code(self) -> str | None:
        """The machine code of a refusal (``app.apply.errors``); None when granted."""
        from app.apply import errors

        return None if self.granted else errors.for_permit_reason(self.reason, (str(g.get("gate")) for g in self.gates))


async def lock_permits(session: AsyncSession) -> None:
    """The transaction-scoped lock every permit decision (and the pause) takes."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": PERMIT_LOCK})


def _results(evaluation: Evaluation) -> list[GateResult]:
    return [GateResult.model_validate(g) for g in evaluation.gate_results()]


async def request(session: AsyncSession, application_id: uuid.UUID, *, packet_hash: str, channel: str,
                  runner_token_id: uuid.UUID | None = None, agent_task_id: uuid.UUID | None = None,
                  actor: str = "system", now: datetime | None = None) -> PermitResult:
    """Ask for a submit permit immediately before sending. Returns ``granted`` (with the permit),
    ``wait_for_owner`` (an automatic approval no longer holds: ask the owner) or ``denied``."""
    now = now or utcnow()
    await lock_permits(session)
    app = await session.scalar(select(Application).where(Application.id == application_id)
                               .with_for_update().execution_options(populate_existing=True))
    if app is None:
        raise PermitRefused("application not found")
    packet = await session.scalar(select(ApplicationPacket).where(
        ApplicationPacket.application_id == app.id, ApplicationPacket.content_hash == packet_hash)
        .order_by(ApplicationPacket.version.desc()).limit(1).execution_options(populate_existing=True))
    approval = None
    if packet is not None and packet.approved_at is not None:
        approval = "auto" if (packet.approved_by or "").startswith("system") else "owner"
    conflict = await conflicts.check_conflict_at_submit(session, app, now=now, claim=False)
    extra: dict[str, Check] = {"employer_conflict": (conflict.outcome, conflict.reason)}
    extra["stage"] = (("pass", f"application is {app.stage.value}") if app.stage in (Stage.ready, Stage.applying)
                      else ("fail", f"application is {app.stage.value}, not ready"))
    evaluation = await gates.evaluate(session, app, packet, channel=channel, approval=approval,  # type: ignore[arg-type]
                                      packet_hash=packet_hash, runner_token_id=runner_token_id, now=now,
                                      extra_checks=extra)
    detail = {"packet_hash": packet_hash, "channel": channel, "approval": approval,
              "runner_token_id": str(runner_token_id) if runner_token_id else None,
              "agent_task_id": str(agent_task_id) if agent_task_id else None,
              "reason": evaluation.reason, "mode": evaluation.decision.mode, "gates": evaluation.gate_results()}
    if evaluation.status != "granted" or packet is None:
        await audit.record(session, actor=actor, action=f"permit.{evaluation.status}", subject_type="application",
                           subject_id=app.id, detail=detail)
        return PermitResult(evaluation.status, evaluation.reason, None, evaluation.gate_results())
    minutes = int(await settings_service.get_value(session, "automation.permit_valid_minutes"))
    permit = SubmitPermit(application_id=app.id, packet_id=packet.id, packet_hash=packet.content_hash,
                          agent_task_id=agent_task_id, runner_token_id=runner_token_id, issued_at=now,
                          expires_at=now + timedelta(minutes=minutes), checks=_results(evaluation))
    session.add(permit)
    if app.stage != Stage.applying:
        await stages.transition(session, app, Stage.applying, actor=actor, via="system", now=now,
                                why="submit permit granted", detail={"packet_hash": packet.content_hash})
    await session.flush()
    await audit.record(session, actor=actor, action="permit.granted", subject_type="submit_permit",
                       subject_id=permit.id, detail={**detail, "application_id": str(app.id),
                                                     "expires_at": permit.expires_at.isoformat()})
    return PermitResult("granted", evaluation.reason, permit, evaluation.gate_results())


async def consume(session: AsyncSession, permit_id: uuid.UUID, *, packet_hash: str, channel: str,
                  runner_token_id: uuid.UUID | None = None, actor: str = "system",
                  now: datetime | None = None) -> SubmitPermit:
    """Use a permit, exactly once. Raises :class:`PermitRefused` when it is expired, used, revoked or
    bound to a different packet, channel or runner. Atomic: two concurrent calls cannot both succeed."""
    now = now or utcnow()
    permit = await session.get(SubmitPermit, permit_id)
    if permit is None:
        raise PermitRefused("permit not found")
    packet = await session.get(ApplicationPacket, permit.packet_id)
    reasons = []
    if permit.packet_hash != packet_hash:
        reasons.append("bound to a different packet")
    if permit.runner_token_id != runner_token_id:
        reasons.append("bound to a different runner")
    if packet is None or packet.contents.channel != channel:
        reasons.append("bound to a different channel")
    if packet is not None and packet.invalidated_at is not None:
        reasons.append("the packet has been replaced")
    if not reasons:
        used = await session.scalar(
            update(SubmitPermit).where(SubmitPermit.id == permit_id, SubmitPermit.used_at.is_(None),
                                       SubmitPermit.expires_at > now, SubmitPermit.packet_hash == packet_hash)
            .values(used_at=now).returning(SubmitPermit.id))
        if used is None:
            await session.refresh(permit)
            reasons.append("already used" if permit.used_at is not None else "expired or revoked")
    if reasons:
        await audit.record(session, actor=actor, action="permit.refused", subject_type="submit_permit",
                           subject_id=permit_id, detail={"reasons": reasons, "packet_hash": packet_hash,
                                                         "channel": channel})
        raise PermitRefused("; ".join(reasons))
    await session.refresh(permit)
    await audit.record(session, actor=actor, action="permit.consumed", subject_type="submit_permit",
                       subject_id=permit.id, detail={"application_id": str(permit.application_id),
                                                     "packet_hash": packet_hash, "channel": channel})
    return permit


async def revoke(session: AsyncSession, *, application_id: uuid.UUID | None = None, reason: str, actor: str,
                 now: datetime | None = None) -> list[uuid.UUID]:
    """Expire every outstanding permit (of one application, or all of them). Returns their ids."""
    now = now or utcnow()
    stmt = update(SubmitPermit).where(SubmitPermit.used_at.is_(None), SubmitPermit.expires_at > now)
    if application_id is not None:
        stmt = stmt.where(SubmitPermit.application_id == application_id)
    rows = (await session.execute(stmt.values(expires_at=now).returning(SubmitPermit.id,
                                                                        SubmitPermit.application_id))).all()
    for pid, _ in rows:
        await audit.record(session, actor=actor, action="permit.revoked", subject_type="submit_permit",
                           subject_id=pid, detail={"reason": reason})
    for app_id in {a for _, a in rows}:
        app = await session.get(Application, app_id)
        if app is not None:
            await _give_back(session, app, f"permit revoked: {reason}", now)
    return [pid for pid, _ in rows]


async def _give_back(session: AsyncSession, app: Application, why: str, now: datetime) -> bool:
    """``applying`` -> ``ready`` when nothing was dispatched for it."""
    if app.stage != Stage.applying:
        return False
    attempt = await session.scalar(select(DispatchAttempt.id).where(DispatchAttempt.application_id == app.id)
                                   .limit(1))
    if attempt is not None:
        return False
    await stages.transition(session, app, Stage.ready, actor="system", via="system", now=now, why=why)
    return True


async def release_stale_claims(session: AsyncSession, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Applications claimed by a permit that expired unused and never dispatched go back to ``ready``.
    Call from the scheduler tick."""
    now = now or utcnow()
    apps = (await session.scalars(select(Application).where(Application.stage == Stage.applying))).all()
    released = []
    for app in apps:
        live = await session.scalar(select(SubmitPermit.id).where(
            SubmitPermit.application_id == app.id, SubmitPermit.used_at.is_(None),
            SubmitPermit.expires_at > now).limit(1))
        used = await session.scalar(select(SubmitPermit.id).where(
            SubmitPermit.application_id == app.id, SubmitPermit.used_at.is_not(None)).limit(1))
        if live is None and used is None and await _give_back(session, app, "submit permit expired unused", now):
            released.append(app.id)
    return released
