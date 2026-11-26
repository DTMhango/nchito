"""Endpoints: provider records, route tests and activation, prices, spend, prompts."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.llm.deps import llm_service
from app.models.platform import AuditEvent, ConfigKind, ConfigRevision, Connection
from tests.llm.conftest import ScriptedAdapter, make_service, reply, set_settings

KEY = "sk-test-not-a-real-key-123456"


@pytest.fixture
def adapter(app) -> ScriptedAdapter:
    scripted = ScriptedAdapter()
    app.dependency_overrides[llm_service] = lambda: make_service(scripted)
    yield scripted
    app.dependency_overrides.pop(llm_service, None)


async def create_provider(client: httpx.AsyncClient) -> dict:
    r = await client.post("/api/connections", json={"provider": "anthropic", "label": "Main",
                                                    "secrets": {"api_key": KEY}})
    assert r.status_code == 201, r.text
    return r.json()


async def test_provider_keys_are_encrypted_masked_and_never_logged(owner_client: httpx.AsyncClient) -> None:
    created = await create_provider(owner_client)
    assert created["secrets_masked"]["api_key"].endswith(KEY[-4:]) and KEY not in str(created)
    listed = (await owner_client.get("/api/connections")).json()
    assert KEY not in str(listed)
    async with get_sessionmaker()() as s:
        row = await s.get(Connection, created["id"])
        audit_rows = (await s.scalars(select(AuditEvent))).all()
    assert row is not None and KEY not in (row.secrets_enc or "")
    assert all(KEY not in str(a.detail) for a in audit_rows)

    r = await owner_client.put(f"/api/connections/{created['id']}",
                               json={"label": "Renamed", "secrets": {"api_key": ""}})
    assert r.status_code == 200 and r.json()["secrets_masked"]["api_key"].endswith(KEY[-4:])
    assert (await owner_client.delete(f"/api/connections/{created['id']}")).status_code == 204


async def test_provider_validation_and_non_llm_providers_wait_for_wave_2(owner_client: httpx.AsyncClient) -> None:
    r = await owner_client.post("/api/connections", json={"provider": "openai_compatible", "label": "Local"})
    assert r.status_code == 422 and "base_url" in r.text
    r = await owner_client.post("/api/connections", json={"provider": "anthropic", "label": "x",
                                                          "config": {"api_key": "oops"}})
    assert r.status_code == 422
    # OneDrive (wave 4 msgraph) signs in with OAuth: pasting keys is refused.
    r = await owner_client.post("/api/connections", json={"provider": "onedrive", "label": "Drive"})
    assert r.status_code == 422 and "Connect button" in r.text


async def test_connection_test_makes_one_tiny_budgeted_call(owner_client: httpx.AsyncClient,
                                                            adapter: ScriptedAdapter) -> None:
    created = await create_provider(owner_client)
    r = await owner_client.post(f"/api/connections/{created['id']}/test")
    assert r.json() == {"ok": False, "detail": "Set a monthly cap first: paid calls stay off without one.",
                        "cost_minor": 0, "cost_micros": 0}
    await set_settings(budget__monthly_cap_minor=500)
    adapter.replies.append(reply({"ok": True}, input_tokens=80, output_tokens=5))
    r = await owner_client.post(f"/api/connections/{created['id']}/test")
    assert r.json()["ok"] is True and r.json()["cost_minor"] == 0
    assert r.json()["cost_micros"] > 0  # a fraction of a cent
    request, creds = adapter.requests[0]
    assert request.max_output_tokens == 256 and creds.api_key == KEY
    listed = (await owner_client.get("/api/connections")).json()
    assert listed[0]["health"] == "ok" and listed[0]["last_checked_at"]


async def test_route_must_pass_a_test_before_activation(owner_client: httpx.AsyncClient,
                                                        adapter: ScriptedAdapter) -> None:
    await create_provider(owner_client)
    await set_settings(budget__monthly_cap_minor=500)
    body = {"stage": "score", "model": "claude-sonnet-5-5"}
    r = await owner_client.post("/api/ai/routing/activate", json=body)
    assert r.status_code == 409
    adapter.replies.append(reply({"ok": True}))
    r = await owner_client.post("/api/ai/routing/test", json=body)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["model"] == "claude-sonnet-5-5"
    r = await owner_client.post("/api/ai/routing/activate", json=body)
    assert r.status_code == 200 and r.json()["model"] == "claude-sonnet-5-5"
    routes = {x["stage"]: x for x in (await owner_client.get("/api/ai/routing")).json()}
    assert routes["score"]["model"] == "claude-sonnet-5-5" and routes["score"]["last_test"]["ok"]
    assert (await owner_client.get("/api/settings/ai.model_score")).json()["value"] == "claude-sonnet-5-5"
    async with get_sessionmaker()() as s:
        rev = await s.scalar(select(ConfigRevision).where(ConfigRevision.kind == ConfigKind.model_routing))
    assert rev is not None and rev.diff == {"setting": "ai.model_score", "old": "claude-haiku-5-5",
                                            "new": "claude-sonnet-5-5"}


async def test_failed_route_test_does_not_allow_activation(owner_client: httpx.AsyncClient,
                                                           adapter: ScriptedAdapter) -> None:
    from app.llm.providers import ProviderCallError

    await create_provider(owner_client)
    await set_settings(budget__monthly_cap_minor=500)
    adapter.replies.append(ProviderCallError("Anthropic error 404", retryable=False))
    r = await owner_client.post("/api/ai/routing/test", json={"stage": "tailor", "model": "claude-opus-5-5"})
    assert r.json()["ok"] is False and "404" in r.json()["detail"]
    r = await owner_client.post("/api/ai/routing/activate", json={"stage": "tailor", "model": "claude-opus-5-5"})
    assert r.status_code == 409


async def test_price_table_is_seeded_editable_and_resettable(owner_client: httpx.AsyncClient) -> None:
    prices = (await owner_client.get("/api/ai/prices")).json()
    assert {p["model"] for p in prices} >= {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}
    assert all(p["as_of"] == "2026-11-03" for p in prices)
    edited = [{k: v for k, v in p.items() if k not in ("id", "updated_at")} for p in prices]
    edited.append({"provider": "openai_compatible", "model": "local-llama", "currency": "USD",
                   "input_per_mtok": "0", "output_per_mtok": "0", "as_of": "2026-11-26"})
    r = await owner_client.put("/api/ai/prices", json={"prices": edited})
    assert r.status_code == 200 and len(r.json()) == len(prices) + 1
    r = await owner_client.put("/api/ai/prices", json={"prices": edited + edited[-1:]})
    assert r.status_code == 422
    r = await owner_client.post("/api/ai/prices/reset")
    assert len(r.json()) == len(prices)


async def test_spend_summary_and_meter(owner_client: httpx.AsyncClient, adapter: ScriptedAdapter) -> None:
    await create_provider(owner_client)
    await set_settings(budget__monthly_cap_minor=500)
    adapter.replies.append(reply({"ok": True}))
    await owner_client.post("/api/ai/routing/test", json={"stage": "extract"})
    summary = (await owner_client.get("/api/ai/spend")).json()
    assert summary["month_to_date_minor"] == 0 and summary["by_stage"][0]["key"] == "extract"
    assert summary["timezone"] == "Africa/Lusaka" and summary["cap_minor"] == 500
    meter = (await owner_client.get("/api/ai/spend/meter")).json()
    # a sub-cent call shows 0 in minor units but is visible in micros
    assert meter["month_to_date_minor"] == 0 and meter["month_to_date_micros"] > 0
    assert meter["cap_minor"] == 500 and meter["cap_micros"] == 5_000_000 and meter["currency"] == "USD"
    assert (await owner_client.get("/api/ai/spend?month=2026-13")).status_code == 422


async def test_prompts_seed_version_activate_and_record_history(owner_client: httpx.AsyncClient) -> None:
    prompts = (await owner_client.get("/api/kit/prompts")).json()
    assert {p["stage"] for p in prompts} == {"extract", "score", "tailor", "claim_check", "classify_email", "interview"}
    assert all(p["active"] and p["version"] == 1 for p in prompts)
    r = await owner_client.post("/api/kit/prompts", json={"stage": "score", "text": "Score strictly.", "note": "v2"})
    assert r.status_code == 201 and r.json()["version"] == 2 and r.json()["active"] is False
    r = await owner_client.post(f"/api/kit/prompts/{r.json()['id']}/activate")
    assert r.json()["active"] is True
    score = (await owner_client.get("/api/kit/prompts?stage=score")).json()
    assert [(p["version"], p["active"]) for p in score] == [(2, True), (1, False)]
    async with get_sessionmaker()() as s:
        revs = (await s.scalars(select(ConfigRevision).where(ConfigRevision.kind == ConfigKind.prompt)
                                .order_by(ConfigRevision.version))).all()
    assert [r.diff["change"] for r in revs] == ["saved", "activated"]
    assert (await owner_client.post("/api/kit/prompts", json={"stage": "nope", "text": "x"})).status_code == 422
    import uuid

    assert (await owner_client.post(f"/api/kit/prompts/{uuid.uuid4()}/activate")).status_code == 404


async def test_ai_endpoints_require_the_owner(client: httpx.AsyncClient) -> None:
    for path in ("/api/ai/spend", "/api/ai/prices", "/api/ai/routing", "/api/connections", "/api/kit/prompts"):
        assert (await client.get(path)).status_code == 401
