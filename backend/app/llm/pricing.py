"""Price table: editable data with a dated default (``prices_default.json``).

Prices are minor currency units per million tokens. Estimates are upper bounds (ledger
integrity): input is counted at no fewer tokens than ``len(text) / CHARS_PER_TOKEN_FLOOR``, at
the dearer of the plain and cache-write rate, with long-context rates once the estimate passes
the threshold, and the output at the full token limit.
"""

from __future__ import annotations

import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import LlmPrice

DEFAULTS_FILE = Path(__file__).with_name("prices_default.json")
CHARS_PER_TOKEN_FLOOR = 2  # real text runs at 3-4 characters per token; 2 keeps the estimate an upper bound
MESSAGE_OVERHEAD_TOKENS = 64
MILLION = Decimal(1_000_000)


class PriceIn(BaseModel):
    provider: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_per_mtok: Decimal = Field(ge=0)
    output_per_mtok: Decimal = Field(ge=0)
    cache_write_per_mtok: Decimal | None = Field(default=None, ge=0)
    cache_read_per_mtok: Decimal | None = Field(default=None, ge=0)
    long_context_threshold: int | None = Field(default=None, ge=1)
    long_input_per_mtok: Decimal | None = Field(default=None, ge=0)
    long_output_per_mtok: Decimal | None = Field(default=None, ge=0)
    as_of: date
    source: str | None = None


def load_defaults() -> list[PriceIn]:
    raw: dict[str, Any] = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    return [PriceIn(currency=raw["currency"], as_of=raw["as_of"], source=raw["source"], **row)
            for row in raw["prices"]]


async def ensure_default_prices(session: AsyncSession) -> None:
    """Seed the dated default table the first time it is needed (never overwrites owner edits)."""
    if await session.scalar(select(func.count()).select_from(LlmPrice)):
        return
    for row in load_defaults():
        session.add(LlmPrice(**row.model_dump()))
    await session.flush()


async def list_prices(session: AsyncSession) -> list[LlmPrice]:
    await ensure_default_prices(session)
    return list((await session.scalars(select(LlmPrice).order_by(LlmPrice.provider, LlmPrice.model))).all())


async def get_price(session: AsyncSession, provider: str, model: str) -> LlmPrice | None:
    await ensure_default_prices(session)
    return await session.scalar(select(LlmPrice).where(LlmPrice.provider == provider, LlmPrice.model == model))


def estimate_input_tokens(text: str, *, messages: int = 1) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN_FLOOR) + MESSAGE_OVERHEAD_TOKENS * max(messages, 1)


def _rates(price: LlmPrice | PriceIn, input_tokens: int) -> tuple[Decimal, Decimal]:
    long = price.long_context_threshold is not None and input_tokens > price.long_context_threshold
    inp = price.long_input_per_mtok if long and price.long_input_per_mtok is not None else price.input_per_mtok
    out = price.long_output_per_mtok if long and price.long_output_per_mtok is not None else price.output_per_mtok
    return Decimal(inp), Decimal(out)


def max_cost_minor(price: LlmPrice | PriceIn, input_tokens: int, max_output_tokens: int) -> int:
    inp, out = _rates(price, input_tokens)
    write = Decimal(price.cache_write_per_mtok) if price.cache_write_per_mtok is not None else inp
    total = (Decimal(input_tokens) * max(inp, write) + Decimal(max_output_tokens) * out) / MILLION
    return max(1, math.ceil(total))


def cost_minor(price: LlmPrice | PriceIn, *, input_tokens: int, output_tokens: int, cache_write_tokens: int = 0,
               cache_read_tokens: int = 0) -> int:
    """Cost of reported usage. ``input_tokens`` excludes cached tokens (Anthropic's convention)."""
    total_in = input_tokens + cache_write_tokens + cache_read_tokens
    inp, out = _rates(price, total_in)
    write = Decimal(price.cache_write_per_mtok) if price.cache_write_per_mtok is not None else inp
    read = Decimal(price.cache_read_per_mtok) if price.cache_read_per_mtok is not None else inp
    total = (Decimal(input_tokens) * inp + Decimal(cache_write_tokens) * write + Decimal(cache_read_tokens) * read
             + Decimal(output_tokens) * out) / MILLION
    return math.ceil(total)
