"""Wave 3 sources wiring: what connectors are built with, the search API connection, sweeps feeding change
detection, and the permit's job-version gate following the material-change rule."""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select

from app.apply import dispatch, gates, packets
from app.connect import search_api
from app.models.changes import JobChange
from app.models.search import Source
from app.pipeline import changes, orchestrator
from app.schemas.json_types import RateLimit
from app.sources.careers_page import CareersPageConnector
from app.sources.jobspy import JobSpyConnector
from app.sources.registry import build_connector
from app.sources.web_search import SearchConnection, WebSearchConnector
from tests.apply.helpers import browser_draft, setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW
from tests.sources.support import FakeFetcher

API = "https://api.search.example.com/v1/search"


def source(connector: str, **config) -> Source:
    return Source(name=connector, connector=connector, config=config, rate_limit=RateLimit(requests_per_minute=600,
                                                                                         burst=10))


def test_build_connector_passes_only_what_each_connector_takes():
    values = {"sources.search.max_queries": 2}
    llm = object()
    connection = SearchConnection(endpoint=API, api_key="k-123", shape={})
    extras = {"search_connection": connection, "llm": llm, "settings": values}
    web = build_connector(source("web_search"), FakeFetcher({}), extras=extras)
    assert isinstance(web, WebSearchConnector) and web._connection is connection and web.settings is values
    careers = build_connector(source("careers_page"), FakeFetcher({}), extras=extras)
    assert isinstance(careers, CareersPageConnector) and careers.llm is llm and careers.settings is values
    spy = build_connector(source("jobspy"), FakeFetcher({}), extras=extras)
    assert isinstance(spy, JobSpyConnector) and spy.settings is values  # no search_connection or llm parameter


async def test_search_api_connection_gives_the_web_search_source_its_key(owner_client, session):
    r = await owner_client.post("/api/connections", json={
        "provider": "search_api", "label": "Search", "config": {"endpoint": API, "key_header": "X-Api-Key"},
        "secrets": {"api_key": "secret-key-1"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "secret-key-1" not in json.dumps(body) and set(body["secrets_masked"]) == {"api_key"}
    bad = await owner_client.post("/api/connections", json={"provider": "search_api", "label": "x",
                                                             "config": {"endpoint": API}})
    assert bad.status_code == 422  # no key

    search_api.set_fetcher(FakeFetcher({API + "?q=jobs": (200, json.dumps({"results": [
        {"url": "https://jobs.example.com/1", "title": "One"}]}))}))
    try:
        tested = await owner_client.post(f"/api/connections/{body['id']}/test")
    finally:
        search_api.set_fetcher(None)
    assert tested.status_code == 200 and tested.json()["ok"] is True, tested.text

    src = source("web_search", endpoint="https://stale.example.com/search")  # an old per-source endpoint: ignored
    extras = await orchestrator.connector_extras(session, src, None, {"x": 1})
    found = extras["search_connection"]
    assert found.api_key == "secret-key-1" and found.endpoint == API and found.shape["key_header"] == "X-Api-Key"
    assert extras["settings"] == {"x": 1}
    src.config = {"connection_id": "00000000-0000-4000-8000-000000000009"}
    assert (await orchestrator.connector_extras(session, src, None, {}))["search_connection"] is None  # unknown


async def test_a_posting_seen_again_by_a_sweep_feeds_change_detection(session):
    campaign = await setup_campaign(session)
    job, _app = await setup_app(session, campaign, now=NOW)
    await changes.capture_version(session, job, now=NOW)
    before = (changes.snapshot_of(job), job.availability)
    job.deadline = date(2026, 12, 15)  # what extraction of the re-seen posting found
    counts: orchestrator.Counter[str] = orchestrator.Counter()
    await orchestrator._note_changes(session, job, before, NOW, counts)
    change = await session.scalar(select(JobChange).where(JobChange.job_id == job.id))
    assert change is not None and change.source == "sweep" and "deadline_moved" in change.kinds
    assert counts["posting_changes"] == 1


async def test_a_reworded_posting_does_not_fail_the_job_version_gate_but_a_material_change_does(session):
    campaign = await setup_campaign(session)
    job, app = await setup_app(session, campaign, now=NOW)
    built = await packets.build(session, app, browser_draft(), actor="owner", now=NOW)
    packet = built.packet
    assert (await gates._job_version(session, job, packet))[0] == "pass"
    job.content_hash = "f" * 64  # the text was reworded; nothing material moved
    assert await gates._job_version(session, job, packet) == (
        "pass", "the posting was only reworded since the packet was built")
    assert await dispatch._sources_changed(session, app, packet) is None
    job.deadline = date(2026, 12, 1)
    outcome, reason = await gates._job_version(session, job, packet)
    assert outcome == "fail" and "deadline" in reason.lower()
