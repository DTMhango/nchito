"""Settings > AI endpoints: model routing (with route tests), price table, spend summary and meter.

Provider records are under ``/api/connections`` and prompts under ``/api/kit/prompts``.
Spend changes are announced on ``/api/events`` as ``spend.updated``; ``budget.warning`` and
``budget.exhausted`` are sent once per month.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.api.common import ApiModel
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.api.routers.insights import SpendMeter
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.llm import checks, pricing
from app.llm.deps import ledger, llm_service
from app.llm.ledger import Ledger, SpendSummary
from app.llm.routing import STAGE_SETTING, resolve_route
from app.llm.service import LLMService
from app.models.platform import ConfigKind, ConfigRevision, LlmPrice

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[RequireOwner])

ROUTING_SUBJECT = uuid.UUID("0c6f1a52-8d1e-4d3f-9d55-3a2b7c1e9f01")


ServiceDep = Annotated[LLMService, Depends(llm_service)]
LedgerDep = Annotated[Ledger, Depends(ledger)]


class LastTest(BaseModel):
    ok: bool
    at: datetime
    detail: str | None = None


class RouteOut(BaseModel):
    stage: str
    setting_key: str
    provider: str
    model: str
    billed: bool
    last_test: LastTest | None = None


class RouteTestIn(BaseModel):
    stage: str
    model: str | None = Field(default=None, description="Defaults to the stage's current model")


class RouteActivateIn(BaseModel):
    stage: str
    model: str = Field(min_length=1, max_length=128)
    reason: str | None = None


class PriceOut(pricing.PriceIn, ApiModel):
    id: uuid.UUID
    updated_at: datetime


class PriceTableIn(BaseModel):
    prices: list[pricing.PriceIn]


def _check_stage(stage: str) -> None:
    if stage not in STAGE_SETTING:
        raise HTTPException(422, detail=f"unknown stage {stage!r}")


@router.get("/routing", response_model=list[RouteOut], name="ai_routing_list")
async def list_routing(session: SessionDep) -> list[RouteOut]:
    values = await settings_service.values(session)
    tests = await checks.last_tests(session)
    out: list[RouteOut] = []
    for stage, key in STAGE_SETTING.items():
        provider = values["ai.provider"]
        model = values[key]
        test = tests.get((provider, model))
        out.append(RouteOut(stage=stage, setting_key=key, provider=provider, model=model,
                            billed=provider != "claude_cli",
                            last_test=LastTest(ok=bool(test.detail.get("ok")), at=test.created_at,
                                               detail=test.detail.get("detail")) if test else None))
    return out


@router.post("/routing/test", response_model=checks.RouteTestOut, name="ai_routing_test")
async def test_route(body: RouteTestIn, session: SessionDep, principal: PrincipalDep,
                     service: ServiceDep) -> checks.RouteTestOut:
    """One tiny budgeted request on the route (costs well under one cent on the defaults)."""
    _check_stage(body.stage)
    result = await checks.run_test(service, stage=body.stage, model=body.model)
    await checks.record(session, result, actor=principal.actor)
    return result


@router.post("/routing/activate", response_model=RouteOut, name="ai_routing_activate")
async def activate_route(body: RouteActivateIn, session: SessionDep, principal: PrincipalDep) -> RouteOut:
    """Switch a stage to a model. The route must have passed a test recently (DESIGN.md 18.5)."""
    _check_stage(body.stage)
    values = await settings_service.values(session)
    provider = values["ai.provider"]
    test = await checks.recent_success(session, provider=provider, model=body.model, now=utcnow(),
                                       valid_minutes=values["ai.route_test_valid_minutes"])
    if test is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"Test {provider}/{body.model} successfully before activating it.")
    key = STAGE_SETTING[body.stage]
    old = values[key]
    try:
        await settings_service.set_value(session, key, body.model, actor=principal.actor,
                                         reason=body.reason or "route activated after a passing test")
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    version = (await session.scalar(select(func.coalesce(func.max(ConfigRevision.version), 0)).where(
        ConfigRevision.kind == ConfigKind.model_routing, ConfigRevision.subject_id == ROUTING_SUBJECT)) or 0) + 1
    session.add(ConfigRevision(kind=ConfigKind.model_routing, subject_id=ROUTING_SUBJECT, version=version,
                               author=principal.actor, note=f"{body.stage}: {old} -> {body.model}",
                               snapshot={"stage": body.stage, "provider": provider, "model": body.model,
                                         "test_event_id": str(test.id)},
                               diff={"setting": key, "old": old, "new": body.model}))
    route = resolve_route({**values, key: body.model}, body.stage)
    return RouteOut(stage=body.stage, setting_key=key, provider=route.provider, model=route.model,
                    billed=route.billed, last_test=LastTest(ok=True, at=test.created_at, detail=None))


@router.get("/prices", response_model=list[PriceOut], name="ai_prices_list")
async def list_prices(session: SessionDep) -> list[LlmPrice]:
    return await pricing.list_prices(session)


@router.put("/prices", response_model=list[PriceOut], name="ai_prices_replace")
async def replace_prices(body: PriceTableIn, session: SessionDep, principal: PrincipalDep) -> list[LlmPrice]:
    """Replace the whole price table (the screen edits it as one table)."""
    keys = [(p.provider, p.model) for p in body.prices]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, detail="each provider and model appears once")
    before = [_price_dict(p) for p in await pricing.list_prices(session)]
    await session.execute(delete(LlmPrice))
    for row in body.prices:
        session.add(LlmPrice(**row.model_dump()))
    await session.flush()
    await audit.record(session, actor=principal.actor, action="ai.prices_changed", subject_type="price_table",
                       detail={"before": before, "after": [_price_dict(p) for p in body.prices]})
    return await pricing.list_prices(session)


@router.post("/prices/reset", response_model=list[PriceOut], name="ai_prices_reset")
async def reset_prices(session: SessionDep, principal: PrincipalDep) -> list[LlmPrice]:
    """Restore the dated default table."""
    await session.execute(delete(LlmPrice))
    await session.flush()
    rows = await pricing.list_prices(session)
    await audit.record(session, actor=principal.actor, action="ai.prices_reset", subject_type="price_table",
                       detail={"as_of": str(rows[0].as_of) if rows else None})
    return rows


def _price_dict(p: LlmPrice | pricing.PriceIn) -> dict[str, str | int | None]:
    out: dict[str, str | int | None] = {}
    for field in pricing.PriceIn.model_fields:
        value = getattr(p, field)
        out[field] = str(value) if isinstance(value, Decimal | date) else value
    return out


@router.get("/spend", response_model=SpendSummary, name="ai_spend_summary")
async def spend_summary(session: SessionDep, ledger: LedgerDep,
                        month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None
                        ) -> SpendSummary:
    """Month to date (owner's time zone), by stage, model and run; billed and estimated-unbilled apart."""
    return await ledger.summary(session, month)


@router.get("/spend/meter", response_model=SpendMeter, name="ai_spend_meter")
async def spend_meter(session: SessionDep, ledger: LedgerDep) -> SpendMeter:
    """The top-bar meter. Refetch on the ``spend.updated`` event."""
    s = await ledger.summary(session)
    return SpendMeter(month_to_date_minor=s.month_to_date_minor, reserved_minor=s.reserved_minor,
                      cap_minor=s.cap_minor, currency=s.currency, estimated_unbilled_minor=s.estimated_unbilled_minor)
