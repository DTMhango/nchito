"""LLMService end to end with scripted adapters (no provider is ever called) and the real ledger."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.llm.client import BudgetExhausted, DataBlock, LLMClient, LLMConfigError, LLMError, Message, TextPart
from app.llm.fake import FakeLLMClient
from app.llm.ledger import Ledger
from app.llm.money import MICROS_PER_MINOR as M
from app.llm.money import micros_to_minor
from app.llm.providers import Credentials, OpenAICompatibleAdapter, ProviderCallError, ProviderRequest
from app.llm.render import SecretInPrompt
from app.models.platform import LedgerEntry, LedgerKind
from tests.llm.conftest import ScriptedAdapter, make_run, make_service, reply, set_settings


class Score(BaseModel):
    score: int
    reason: str


MESSAGES = [Message("system", [TextPart("Score the job.")]),
            Message("user", [TextPart("Job:"), DataBlock("job", "Data analyst in Lusaka, ZMW 30,000 a month")])]


async def ledger_rows() -> list[LedgerEntry]:
    async with get_sessionmaker()() as s:
        return list((await s.scalars(select(LedgerEntry).order_by(LedgerEntry.created_at))).all())


@pytest.mark.usefixtures("anthropic_record")
async def test_complete_reserves_calls_and_reconciles_to_usage() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    adapter = ScriptedAdapter(reply({"score": 72, "reason": "fits"}, input_tokens=2000, output_tokens=200))
    service = make_service(adapter)
    assert isinstance(service, LLMClient)
    result, usage = await service.complete("score", MESSAGES, Score, max_cost_micros=50 * M)
    assert result.score == 72
    # haiku 5.5 default prices: 2000 * 10/1e6 + 200 * 50/1e6 cents = 0.03 cents = 300 micros (no rounding up)
    assert (usage.model, usage.cost_micros, usage.billed, usage.currency) == ("claude-haiku-5-5", 300, True, "USD")
    request, creds = adapter.requests[0]
    assert creds.api_key == "test-key-not-real-0000"
    assert "<<<DATA" in request.turns[0][1] and "untrusted DATA" in request.system
    assert request.json_schema["required"] == ["score", "reason"]
    kinds = [(r.kind, r.amount_micros) for r in await ledger_rows()]
    assert kinds[0][0] == LedgerKind.reservation and kinds[1] == (LedgerKind.reconciliation, 300)


@pytest.mark.usefixtures("anthropic_record")
async def test_escalation_model_is_used_when_passed() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    adapter = ScriptedAdapter(reply({"score": 61, "reason": "near"}))
    _, usage = await make_service(adapter).complete("score", MESSAGES, Score, max_cost_micros=500 * M,
                                                    model="claude-sonnet-5-5")
    assert usage.model == "claude-sonnet-5-5" and adapter.requests[0][0].model == "claude-sonnet-5-5"


@pytest.mark.usefixtures("anthropic_record")
async def test_invalid_reply_is_retried_and_every_attempt_is_budgeted() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    adapter = ScriptedAdapter(reply({"wrong": True}), ProviderCallError("rate limited", retryable=True),
                              reply({"score": 50, "reason": "ok"}))
    result, usage = await make_service(adapter).complete("score", MESSAGES, Score, max_cost_micros=50 * M)
    assert result.score == 50 and usage.cost_micros == 2 * 150  # two paid replies; the 429 was released
    rows = await ledger_rows()
    assert [r.kind for r in rows].count(LedgerKind.reservation) == 3
    assert [r.kind for r in rows].count(LedgerKind.release) == 1


@pytest.mark.usefixtures("anthropic_record")
async def test_timeouts_are_charged_at_estimate_and_retries_are_bounded() -> None:
    await set_settings(budget__monthly_cap_minor=1000, ai__max_retries=1)
    adapter = ScriptedAdapter(*(ProviderCallError("timeout", retryable=True, may_have_billed=True),) * 2)
    service = make_service(adapter)
    with pytest.raises(LLMError, match="no valid reply after 2 attempts"):
        await service.complete("score", MESSAGES, Score, max_cost_micros=500 * M)
    recon = [r for r in await ledger_rows() if r.kind == LedgerKind.reconciliation]
    assert len(recon) == 2 and all(r.amount_micros > 0 and "estimate" in (r.note or "") for r in recon)


@pytest.mark.usefixtures("anthropic_record")
async def test_non_retryable_errors_stop_at_once() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    adapter = ScriptedAdapter(ProviderCallError("bad request", retryable=False), reply({"score": 1, "reason": ""}))
    with pytest.raises(LLMError, match="bad request"):
        await make_service(adapter).complete("score", MESSAGES, Score, max_cost_micros=500 * M)
    assert len(adapter.requests) == 1


@pytest.mark.usefixtures("anthropic_record")
async def test_budget_refusals_send_nothing() -> None:
    adapter = ScriptedAdapter(reply({"score": 1, "reason": ""}))
    service = make_service(adapter)
    with pytest.raises(BudgetExhausted) as exc:  # no monthly cap set
        await service.complete("score", MESSAGES, Score, max_cost_micros=500 * M)
    assert exc.value.scope == "no_cap"
    await set_settings(budget__monthly_cap_minor=1000)
    with pytest.raises(BudgetExhausted) as exc:  # the caller's ceiling is below the estimate
        await service.complete("tailor", MESSAGES, Score, max_cost_micros=1 * M)
    assert exc.value.scope == "call"
    assert adapter.requests == []


@pytest.mark.usefixtures("anthropic_record")
async def test_per_run_cap_applies_through_for_run() -> None:
    await set_settings(budget__monthly_cap_minor=1000, budget__per_run_cap_minor=1)
    run_id = await make_run()
    service = make_service(ScriptedAdapter(reply({"score": 1, "reason": ""}))).for_run(run_id)
    with pytest.raises(BudgetExhausted) as exc:
        await service.complete("tailor", MESSAGES, Score, max_cost_micros=500 * M)
    assert exc.value.scope == "per_run"


async def test_missing_provider_record_or_price_is_a_config_error() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    service = make_service(ScriptedAdapter())
    with pytest.raises(LLMConfigError, match="no enabled anthropic provider"):
        await service.complete("score", MESSAGES, Score, max_cost_micros=500 * M)


@pytest.mark.usefixtures("anthropic_record")
async def test_unpriced_model_is_refused() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    with pytest.raises(LLMConfigError, match="no price"):
        await make_service(ScriptedAdapter()).complete("score", MESSAGES, Score, max_cost_micros=500 * M,
                                                       model="claude-unknown-1")


async def test_cli_route_is_logged_as_not_billed_and_needs_no_cap() -> None:
    await set_settings(ai__provider="claude_cli", ai__claude_cli_enabled=True)
    adapter = ScriptedAdapter(reply({"score": 9, "reason": "x"}), name="claude_cli", billed=False)
    _, usage = await make_service(adapter).complete("score", MESSAGES, Score, max_cost_micros=500 * M)
    assert usage.billed is False
    assert all(r.billed is False for r in await ledger_rows())
    async with get_sessionmaker()() as s:
        summary = await Ledger().summary(s)
    assert summary.month_to_date_minor == 0 and summary.estimated_unbilled_minor == micros_to_minor(usage.cost_micros)


@pytest.mark.usefixtures("anthropic_record")
async def test_secrets_are_refused_before_any_reservation() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    adapter = ScriptedAdapter()
    bad = [Message("user", [DataBlock("email", "my key is sk-ant-api03-" + "x" * 30)])]
    with pytest.raises(SecretInPrompt):
        await make_service(adapter).complete("classify_email", bad, Score, max_cost_micros=500 * M)
    assert await ledger_rows() == []


async def test_openai_compatible_adapter_sends_schema_and_reads_usage() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"score": 3, "reason": "r"}'}}],
                                         "usage": {"prompt_tokens": 120, "completion_tokens": 7,
                                                   "prompt_tokens_details": {"cached_tokens": 20}}})

    adapter = OpenAICompatibleAdapter(transport=httpx.MockTransport(handler))
    out = await adapter.call(ProviderRequest(model="m", system="sys", turns=[("user", "u")],
                                             json_schema={"type": "object"}, max_output_tokens=50, timeout_seconds=5),
                             Credentials(api_key="k", base_url="http://llm.example.com/v1"))
    assert seen["url"] == "http://llm.example.com/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert (out.data, out.input_tokens, out.cache_read_tokens, out.output_tokens) == (
        {"score": 3, "reason": "r"}, 100, 20, 7)


async def test_openai_compatible_adapter_maps_errors() -> None:
    adapter = OpenAICompatibleAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(ProviderCallError) as exc:
        await adapter.call(ProviderRequest(model="m", system="s", turns=[("user", "u")], json_schema={},
                                           max_output_tokens=5, timeout_seconds=5), Credentials(base_url="http://x"))
    assert exc.value.retryable


def test_credentials_never_show_the_key() -> None:
    assert "secret-value" not in repr(Credentials(api_key="secret-value"))


async def test_fake_client_scripts_records_and_keeps_invariants() -> None:
    fake = FakeLLMClient(cost_micros=3).script("score", {"score": 1, "reason": "a"},
                                              lambda call: Score(score=len(call.messages), reason="b"))
    fake.script("*", BudgetExhausted("monthly", needed_micros=1, available_micros=0, currency="USD"))
    assert isinstance(fake, LLMClient)
    first, usage = await fake.complete("score", MESSAGES, Score, max_cost_micros=10)
    second, _ = await fake.complete("score", MESSAGES, Score, max_cost_micros=10)
    assert (first.score, second.score, usage.cost_micros) == (1, 2, 3)
    with pytest.raises(BudgetExhausted):
        await fake.complete("tailor", MESSAGES, Score, max_cost_micros=10)
    assert [c.stage for c in fake.calls] == ["score", "score", "tailor"]
    assert fake.calls[0].prompt.has_untrusted
    with pytest.raises(AssertionError, match="no scripted reply"):
        await fake.complete("extract", MESSAGES, Score, max_cost_micros=10)
