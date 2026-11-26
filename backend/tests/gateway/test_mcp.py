"""The MCP server at /mcp through the official client, in process (no network)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.core.clock import FakeClock
from app.gateway import accounts_bridge, common, server
from app.gateway.tools import TOOLS
from tests.gateway.helpers import URL, make_token, world
from tests.pipeline.matching.helpers import NOW


@pytest.fixture(autouse=True)
def clock():
    common.set_clock(FakeClock(NOW))
    accounts_bridge.set_module(None)
    server.limiter.reset()
    yield
    common.set_clock(None)
    accounts_bridge.set_module()


@asynccontextmanager
async def mcp_client(app, secret: str | None):
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers=headers,
                             timeout=30)
    async with http, streamable_http_client("http://testserver/mcp", http_client=http) as (read, write, _), \
            ClientSession(read, write) as session:
        await session.initialize()
        yield session


def structured(result) -> dict:
    assert not result.isError, result.content
    return result.structuredContent


async def test_tools_and_a_full_application_over_mcp(app):
    w = await world()
    async with mcp_client(app, w.secret_a) as mcp:
        tools = await mcp.list_tools()
        assert {t.name for t in tools.tools} == set(TOOLS)
        task = structured(await mcp.call_tool("next_task", {}))
        assert task["type"] == "apply"
        packet = structured(await mcp.call_tool("get_packet", {"task_id": task["task_id"]}))
        assert packet["destination_domain"] == "boards.greenhouse.io"
        granted = structured(await mcp.call_tool("request_submit_permit", {
            "task_id": task["task_id"], "summary": "submit", "current_url": URL, "attached_files_sha256": [],
            "entered_answers": [{"question": "Notice period", "value": "One month"}]}))
        assert granted["decision"] == "granted"
        done = structured(await mcp.call_tool("report_result", {
            "task_id": task["task_id"], "outcome": "submitted", "permit_id": granted["permit_id"],
            "confirmation_text": "Thank you for applying"}))
        assert done["application_stage"] == "submitted"
        # A refusal is a tool error carrying a stable code.
        bad = await mcp.call_tool("get_packet", {"task_id": task["task_id"]})
        assert bad.isError and json.loads(bad.content[0].text)["code"] == "task_not_active"


async def test_unknown_missing_and_revoked_tokens_are_refused(app, owner_client):
    w = await world()
    for secret in (None, "nch_not-a-real-token"):
        r = await owner_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                    headers={"Authorization": f"Bearer {secret}"} if secret else {})
        assert r.status_code == 401
    r = await owner_client.post(f"/api/tokens/{w.runner_a}/revoke")
    assert r.status_code == 200 and r.json()["revoked_at"]
    with pytest.raises(Exception):
        async with mcp_client(app, w.secret_a):
            pass


async def test_scope_refused_over_mcp(app):
    await world()
    _, secret = await make_token("sweeper", scopes=["gateway:sweep"])
    async with mcp_client(app, secret) as mcp:
        out = await mcp.call_tool("next_task", {"kinds": ["apply"]})
        assert out.isError and json.loads(out.content[0].text)["code"] == "scope_missing"


async def test_rate_limit(app):
    w = await world()
    from app.core.db import get_sessionmaker
    from app.core.settings import service as settings_service

    async with get_sessionmaker()() as s:
        await settings_service.set_value(s, "runners.calls_per_minute", 1, actor="owner")
        await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        headers = {"Authorization": f"Bearer {w.secret_a}", "Accept": "application/json, text/event-stream"}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        await http.post("/mcp", json=body, headers=headers)
        r = await http.post("/mcp", json=body, headers=headers)
        assert r.status_code == 429


async def test_evidence_upload_through_a_signed_link(app, monkeypatch, tmp_path):
    from app.connect import local_store
    from tests.gateway.helpers import call

    monkeypatch.setattr(local_store, "default_file_store", lambda: local_store.LocalFileStore(tmp_path))
    w = await world()
    task_id = (await call(w.runner_a, "next_task"))["task_id"]
    link = await call(w.runner_a, "evidence_upload_url", task_id=task_id, content_type="image/png")
    path = link["upload_url"].removeprefix("http://testserver")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        assert (await http.put(path, content=b"x", headers={"Content-Type": "text/plain"})).status_code == 415
        r = await http.put(path, content=b"\x89PNG fake", headers={"Content-Type": "image/png"})
        assert r.status_code == 201, r.text
        assert (await http.put(path, content=b"\x89PNG", headers={"Content-Type": "image/png"})).status_code == 409
        assert (await http.put(path[:-3] + "abc", content=b"x",
                               headers={"Content-Type": "image/png"})).status_code == 403
    saved = await call(w.runner_a, "save_checkpoint", task_id=task_id,
                       state={"step": "confirm", "screenshot_ref": link["ref"]})
    assert saved["ok"]
