"""LLM client interface (DESIGN.md 11).

``complete(stage, messages, schema) -> (structured result, usage)``. Adapters: Anthropic API
(default), OpenAI-compatible endpoint, Claude Code CLI (PC only, opt-in, "not billed").
Invariants every adapter and caller MUST keep:

- **Budget first.** Callers go through the ledger: estimate the maximum cost, reserve, call,
  reconcile. ``max_cost_minor`` is the reservation; an adapter refuses a call whose own
  estimate exceeds it. At the cap, paid calls raise ``BudgetExceeded``.
- **Structured only.** ``schema`` is a Pydantic model; the result is validated against it.
  Stages that read untrusted content have no tools.
- **Untrusted content is data.** Job pages, emails and attachments go only inside
  ``DataBlock`` parts, which adapters wrap in delimiters and never treat as instructions.
- **No secrets in prompts.** Facts marked "keep out of AI prompts", ID documents, referee
  contacts and credentials are excluded before a message is built; adapters assert nothing
  in ``messages`` matches the secret-redaction patterns.
- **Model by stage.** The model comes from the ``ai.model_*`` setting for the stage unless
  the caller passes an explicit escalation model.
- **Tests use ``FakeLLMClient``** (wave 1); no test calls a provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

Stage = Literal["extract", "classify_email", "score", "custom_facet", "tailor", "claim_check", "browser_agent",
                "interview", "import"]

ResultT = TypeVar("ResultT", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class DataBlock:
    """Untrusted content. Rendered inside delimiters with a label; never instructions."""

    label: str
    content: str


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    parts: Sequence[TextPart | DataBlock]


@dataclass(frozen=True)
class Usage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_minor: int
    currency: str
    billed: bool


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        stage: Stage,
        messages: Sequence[Message],
        schema: type[ResultT],
        *,
        max_cost_minor: int,
        model: str | None = None,
    ) -> tuple[ResultT, Usage]:
        ...

    async def estimate_cost_minor(self, stage: Stage, messages: Sequence[Message], *, model: str | None = None) -> int:
        """Upper bound on the cost of ``complete`` with these messages (used for reservations)."""
        ...
