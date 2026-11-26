"""``FakeLLMClient``: the ``LLMClient`` every test uses (no test calls a provider).

Script replies per stage (or for any stage) and inspect ``calls`` afterwards::

    fake = FakeLLMClient()
    fake.script("score", {"score": 72, "reasons": []})          # dict, model instance,
    fake.script("score", lambda call: {...})                     # callable(FakeCall) -> reply,
    fake.script("extract", BudgetExhausted("monthly", ...))      # or an exception to raise
    result, usage = await fake.complete("score", messages, ScoreOut, max_cost_micros=10)
    assert fake.calls[0].stage == "score"

Replies are consumed in order; ``default`` (if set) answers when a stage's queue is empty;
otherwise the call fails loudly. Messages still go through ``render``, so untrusted data is
wrapped and a credential in a prompt raises ``SecretInPrompt`` exactly as in production.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.llm.client import BudgetExhausted, Message, ResultT, Stage, Usage
from app.llm.render import RenderedPrompt, render

Reply = BaseModel | dict[str, Any] | Exception | Callable[["FakeCall"], Any]
ANY_STAGE = "*"


@dataclass
class FakeCall:
    stage: str
    messages: Sequence[Message]
    schema: type[BaseModel]
    max_cost_micros: int
    model: str | None
    prompt: RenderedPrompt


@dataclass
class FakeLLMClient:
    cost_micros: int = 0
    estimate_micros: int = 0
    currency: str = "USD"
    billed: bool = True
    provider: str = "fake"
    default_model: str = "fake-model"
    default: Reply | None = None
    calls: list[FakeCall] = field(default_factory=list)
    _queues: dict[str, deque[Reply]] = field(default_factory=lambda: defaultdict(deque))

    def script(self, stage: Stage | str, *replies: Reply) -> FakeLLMClient:
        self._queues[stage].extend(replies)
        return self

    def calls_for(self, stage: str) -> list[FakeCall]:
        return [c for c in self.calls if c.stage == stage]

    async def estimate_cost_micros(self, stage: Stage, messages: Sequence[Message], *, model: str | None = None,
                                   schema: type[BaseModel] | None = None) -> int:
        render(messages)
        return self.estimate_micros

    async def complete(self, stage: Stage, messages: Sequence[Message], schema: type[ResultT], *,
                       max_cost_micros: int, model: str | None = None) -> tuple[ResultT, Usage]:
        call = FakeCall(stage=stage, messages=messages, schema=schema, max_cost_micros=max_cost_micros, model=model,
                        prompt=render(messages))
        self.calls.append(call)
        if self.estimate_micros > max_cost_micros:
            raise BudgetExhausted("call", needed_micros=self.estimate_micros, available_micros=max_cost_micros,
                                  currency=self.currency)
        reply = self._next(stage)
        if callable(reply) and not isinstance(reply, BaseModel | Exception):
            reply = reply(call)
        if isinstance(reply, Exception):
            raise reply
        data = reply.model_dump() if isinstance(reply, BaseModel) else reply
        return schema.model_validate(data), Usage(provider=self.provider, model=model or self.default_model,
                                                  input_tokens=len(call.prompt.all_text) // 4, output_tokens=0,
                                                  cost_micros=self.cost_micros, currency=self.currency,
                                                  billed=self.billed)

    def _next(self, stage: str) -> Reply:
        for key in (stage, ANY_STAGE):
            if self._queues[key]:
                return self._queues[key].popleft()
        if self.default is not None:
            return self.default
        raise AssertionError(f"FakeLLMClient: no scripted reply for stage {stage!r}")
