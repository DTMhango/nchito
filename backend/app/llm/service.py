"""``LLMService``: the production ``LLMClient``.

Per call: render the messages (untrusted data wrapped, secrets refused), resolve the route from
settings, price it from the price table, then for each attempt reserve the upper-bound cost in
the ledger, call the provider once, and reconcile to the reported usage. Retries back off
exponentially; every attempt is budgeted, so the cap covers retries (DESIGN.md 18.5).
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.llm import pricing, provider_records
from app.llm.client import (
    BudgetExhausted,
    LLMConfigError,
    LLMError,
    Message,
    ResultT,
    Stage,
    Usage,
)
from app.llm.ledger import Ledger, Reservation
from app.llm.providers import Credentials, ProviderAdapter, ProviderCallError, ProviderRequest, default_adapters
from app.llm.render import json_schema_for, render, schema_instruction
from app.llm.routing import Route, resolve_route
from app.models.platform import LlmPrice

TIMEOUT_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class CallPlan:
    route: Route
    credentials: Credentials
    price: LlmPrice
    currency: str
    request: ProviderRequest
    estimate_micros: int
    retries: int


class LLMService:
    def __init__(self, *, adapters: dict[str, ProviderAdapter] | None = None, ledger: Ledger | None = None,
                 sessionmaker: async_sessionmaker[AsyncSession] | None = None, run_id: uuid.UUID | None = None,
                 agent_task_id: uuid.UUID | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, backoff_seconds: float = 1.0) -> None:
        self._adapters = adapters if adapters is not None else default_adapters()
        self._sessionmaker = sessionmaker
        self.ledger = ledger or Ledger(sessionmaker)
        self.run_id = run_id
        self.agent_task_id = agent_task_id
        self._sleep = sleep
        self._backoff = backoff_seconds

    def for_run(self, run_id: uuid.UUID | None, agent_task_id: uuid.UUID | None = None) -> LLMService:
        """A copy whose ledger rows carry ``run_id`` (for the per-run cap) and ``agent_task_id``."""
        other = LLMService.__new__(LLMService)
        other.__dict__.update(self.__dict__)
        other.run_id, other.agent_task_id = run_id, agent_task_id
        return other

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker or get_sessionmaker()

    async def plan(self, stage: Stage | str, messages: Sequence[Message], schema: type[BaseModel] | None,
                   model: str | None = None, *, max_output_tokens: int | None = None,
                   provider: str | None = None, credentials: Credentials | None = None) -> CallPlan:
        """Everything a call needs, priced. ``provider``/``credentials`` pin a specific provider record
        (used by the "test this route/connection" checks)."""
        prompt = render(messages)
        system = prompt.system
        json_schema: dict = {}
        if schema is not None:
            json_schema = json_schema_for(schema)
            system = (system + "\n\n" if system else "") + schema_instruction(schema)
        async with self.sessionmaker() as session, session.begin():
            values = await settings_service.values(session)
            route = resolve_route(values, stage, model)
            if provider is not None:
                route = dataclasses.replace(route, provider=provider, billed=provider != "claude_cli")
            if credentials is None:
                credentials, _ = await provider_records.credentials_for(session, route.provider)
            price = await pricing.get_price(session, route.provider, route.model)
        if price is None:
            raise LLMConfigError(f"no price for {route.provider}/{route.model}: add it to the price table")
        currency = values["budget.currency"]
        if price.currency != currency:
            raise LLMConfigError(f"price for {route.model} is in {price.currency}, the budget is in {currency}")
        out_tokens = max_output_tokens or values["ai.max_output_tokens"]
        request = ProviderRequest(model=route.model, system=system, turns=prompt.turns, json_schema=json_schema,
                                  max_output_tokens=out_tokens,
                                  timeout_seconds=float(values["ai.request_timeout_seconds"]))
        input_tokens = pricing.estimate_input_tokens(prompt.all_text + system, messages=len(prompt.turns) + 1)
        estimate = pricing.max_cost_micros(price, input_tokens, out_tokens)
        return CallPlan(route=route, credentials=credentials, price=price, currency=currency, request=request,
                        estimate_micros=estimate, retries=values["ai.max_retries"])

    async def estimate_cost_micros(self, stage: Stage, messages: Sequence[Message], *, model: str | None = None) -> int:
        return (await self.plan(stage, messages, None, model)).estimate_micros

    async def complete(self, stage: Stage, messages: Sequence[Message], schema: type[ResultT], *,
                       max_cost_micros: int, model: str | None = None) -> tuple[ResultT, Usage]:
        return await self.run_plan(await self.plan(stage, messages, schema, model), schema,
                                   max_cost_micros=max_cost_micros)

    async def run_plan(self, plan: CallPlan, schema: type[ResultT], *, max_cost_micros: int) -> tuple[ResultT, Usage]:
        if plan.estimate_micros > max_cost_micros:
            raise BudgetExhausted("call", needed_micros=plan.estimate_micros, available_micros=max_cost_micros,
                                  currency=plan.currency)
        adapter = self._adapters.get(plan.route.provider)
        if adapter is None:
            raise LLMConfigError(f"no adapter for provider {plan.route.provider}")
        total_cost = 0
        last_error: Exception | None = None
        for attempt in range(plan.retries + 1):
            if attempt:
                await self._sleep(self._backoff * 2 ** (attempt - 1) * (1 + random.random() / 4))  # noqa: S311
            reservation = await self.ledger.reserve(
                stage=plan.route.stage, provider=plan.route.provider, model=plan.route.model,
                amount_micros=plan.estimate_micros, billed=adapter.billed, run_id=self.run_id,
                agent_task_id=self.agent_task_id)
            try:
                reply = await asyncio.wait_for(adapter.call(plan.request, plan.credentials),
                                               plan.request.timeout_seconds + TIMEOUT_GRACE_SECONDS)
            except (ProviderCallError, TimeoutError) as exc:
                error = exc if isinstance(exc, ProviderCallError) else ProviderCallError(
                    "provider call timed out", retryable=True, may_have_billed=True)
                total_cost += await self._close_failed(reservation, error, plan)
                last_error = error
                if not error.retryable:
                    raise LLMError(f"{plan.route.stage}: {error}") from error
                continue
            except BaseException:
                await self.ledger.reconcile(reservation, cost_micros=reservation.amount_micros, input_tokens=0,
                                            output_tokens=0, note="unexpected failure: charged at estimate")
                raise
            cost = pricing.cost_micros(plan.price, input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                                      cache_write_tokens=reply.cache_write_tokens,
                                      cache_read_tokens=reply.cache_read_tokens)
            await self.ledger.reconcile(reservation, cost_micros=cost, input_tokens=self._in_tokens(reply),
                                        output_tokens=reply.output_tokens)
            total_cost += cost
            try:
                result = schema.model_validate(reply.data)
            except ValidationError as exc:
                last_error = exc
                continue
            return result, Usage(provider=plan.route.provider, model=plan.route.model,
                                 input_tokens=self._in_tokens(reply), output_tokens=reply.output_tokens,
                                 cost_micros=total_cost, currency=plan.currency, billed=adapter.billed)
        raise LLMError(f"{plan.route.stage}: no valid reply after {plan.retries + 1} attempts") from last_error

    @staticmethod
    def _in_tokens(reply: object) -> int:
        return (getattr(reply, "input_tokens", 0) + getattr(reply, "cache_write_tokens", 0)
                + getattr(reply, "cache_read_tokens", 0))

    async def _close_failed(self, reservation: Reservation, error: ProviderCallError, plan: CallPlan) -> int:
        if error.usage is not None:
            cost = pricing.cost_micros(plan.price, input_tokens=error.usage.input_tokens,
                                      output_tokens=error.usage.output_tokens,
                                      cache_write_tokens=error.usage.cache_write_tokens,
                                      cache_read_tokens=error.usage.cache_read_tokens)
            await self.ledger.reconcile(reservation, cost_micros=cost, input_tokens=self._in_tokens(error.usage),
                                        output_tokens=error.usage.output_tokens, note=str(error))
            return cost
        if error.may_have_billed:
            await self.ledger.reconcile(reservation, cost_micros=reservation.amount_micros, input_tokens=0,
                                        output_tokens=0, note=f"{error}: charged at estimate")
            return reservation.amount_micros
        await self.ledger.release(reservation, note=str(error))
        return 0
