"""The OpenAPI document describes the whole product, and docs/openapi.json is current."""

from __future__ import annotations

import json
import uuid

import pytest

from app.gateway.tools import TOOLS, tool_schemas
from tests.conftest import REPO

TAGS = {"setup", "auth", "settings", "themes", "system", "audit", "events", "kit", "campaigns", "sources", "jobs",
        "assessments", "applications", "pending_actions", "runs", "connections", "tokens", "insights", "data"}


@pytest.mark.nodb
def test_every_area_present(app):
    spec = app.openapi()
    tags = {t for path in spec["paths"].values() for op in path.values() for t in op.get("tags", [])}
    assert tags >= TAGS, TAGS - tags
    op_ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]
    assert len(op_ids) == len(set(op_ids)), "operation ids must be unique"


@pytest.mark.nodb
def test_committed_contracts_are_current():
    from app.cli import contract_documents

    for rel, doc in contract_documents().items():
        committed = json.loads((REPO / "docs" / rel).read_text(encoding="utf-8"))
        assert committed == json.loads(json.dumps(doc)), f"docs/{rel} is stale: run `python -m app.cli contracts`"


@pytest.mark.nodb
def test_gateway_tools_have_schemas():
    schemas = tool_schemas()
    assert set(schemas) == {"next_task", "get_packet", "find_answer", "save_checkpoint", "raise_blocker",
                            "request_submit_permit", "report_result", "report_jobs"} == set(TOOLS)
    assert "entered_answers" in schemas["request_submit_permit"]["input"]["properties"]


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/jobs/00000000-0000-4000-8000-000000000001/interview-pack"),
    ("GET", "/api/jobs/00000000-0000-4000-8000-000000000001"),
    ("GET", "/api/campaigns"),
    ("POST", "/api/rubrics/backtest"),
    ("GET", "/api/mail-threads"),
    ("GET", "/api/insights"),
])
async def test_later_wave_endpoints_answer_501(owner_client, method, path):
    body = {"rubric_id": str(uuid.uuid4()), "campaign_id": str(uuid.uuid4())} if method == "POST" else None
    r = await owner_client.request(method, path, json=body)
    assert r.status_code == 501, r.text
    assert r.json()["detail"]["code"] == "not_implemented"


async def test_later_wave_endpoints_still_require_owner(client):
    assert (await client.get("/api/kit/facts")).status_code == 401
