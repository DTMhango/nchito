""""Test this route": one tiny, budgeted request through the normal path (ledger included).

A model route must pass a test before it is activated (DESIGN.md 18.5). Results are kept in the
audit trail (``ai.route_tested``) and read back by ``recent_success``.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.llm.client import BudgetExhausted, LLMError, Message, TextPart
from app.llm.providers import Credentials
from app.llm.service import LLMService
from app.models.platform import AuditEvent

TEST_OUTPUT_TOKENS = 256
TEST_MESSAGES = (
    Message(role="system", parts=[TextPart("This is a connectivity check. Reply with ok set to true.")]),
    Message(role="user", parts=[TextPart("ping")]),
)


class Pong(BaseModel):
    ok: bool


class RouteTestOut(BaseModel):
    ok: bool
    stage: str
    provider: str | None = None
    model: str | None = None
    detail: str | None = None
    cost_micros: int = 0
    currency: str | None = None
    billed: bool = True
    latency_ms: int | None = None


async def run_test(service: LLMService, *, stage: str, model: str | None = None, provider: str | None = None,
                   credentials: Credentials | None = None) -> RouteTestOut:
    started = time.monotonic()
    try:
        plan = await service.plan(stage, TEST_MESSAGES, Pong, model, max_output_tokens=TEST_OUTPUT_TOKENS,
                                  provider=provider, credentials=credentials)
    except LLMError as exc:
        return RouteTestOut(ok=False, stage=stage, provider=provider, model=model, detail=str(exc))
    plan = dataclasses.replace(plan, retries=0)
    out = RouteTestOut(ok=False, stage=stage, provider=plan.route.provider, model=plan.route.model,
                       currency=plan.currency, billed=plan.route.billed)
    try:
        result, usage = await service.run_plan(plan, Pong, max_cost_micros=plan.estimate_micros)
    except BudgetExhausted as exc:
        out.detail = ("Set a monthly cap first: paid calls stay off without one." if exc.scope == "no_cap"
                      else f"Budget refused the test ({exc.scope}).")
        return out
    except LLMError as exc:
        out.detail = str(exc)
        return out
    out.ok = bool(result.ok)
    out.cost_micros = usage.cost_micros
    out.latency_ms = int((time.monotonic() - started) * 1000)
    out.detail = "Replied as expected." if out.ok else "Replied, but not as expected."
    return out


async def record(session: AsyncSession, result: RouteTestOut, *, actor: str) -> None:
    await audit.record(session, actor=actor, action="ai.route_tested", subject_type="ai_route",
                       subject_id=result.stage, detail=result.model_dump(exclude={"detail"}) | {
                           "detail": (result.detail or "")[:300]})


async def recent_success(session: AsyncSession, *, provider: str, model: str, now: datetime,
                         valid_minutes: int) -> AuditEvent | None:
    since = now - timedelta(minutes=valid_minutes)
    return await session.scalar(select(AuditEvent).where(
        AuditEvent.action == "ai.route_tested", AuditEvent.created_at >= since,
        AuditEvent.detail["ok"].astext == "true", AuditEvent.detail["provider"].astext == provider,
        AuditEvent.detail["model"].astext == model).order_by(AuditEvent.created_at.desc()).limit(1))


async def last_tests(session: AsyncSession) -> dict[tuple[str, str], AuditEvent]:
    """Latest test per (provider, model)."""
    rows = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "ai.route_tested")
                                  .order_by(AuditEvent.created_at.desc()).limit(500))).all()
    out: dict[tuple[str, str], AuditEvent] = {}
    for row in rows:
        out.setdefault((str(row.detail.get("provider")), str(row.detail.get("model"))), row)
    return out
