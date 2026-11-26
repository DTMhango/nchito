"""Web search connector: results are leads, only a real posting becomes a RawJob."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from app.sources import registry  # noqa: F401  (imports every connector)
from app.sources.base import RateLimitSpec, SearchContext, SourceError
from app.sources.http import PoliteFetcher, RateLimiter
from app.sources.web_search import SearchHit, WebSearchConnector, build_queries
from tests.sources.support import FakeFetcher, fixture_text

pytestmark = pytest.mark.nodb

GH = "https://boards-api.greenhouse.io/v1/boards"
OPEN = (200, fixture_text("robots_allow_all.txt"))
DENY_ALL = (200, "User-agent: *\nDisallow: /\n")
API = "https://api.search.example.com/v1/search"
CONFIG = {"endpoint": API, "key_header": "X-Api-Key"}


class HeaderFetcher(FakeFetcher):
    def __init__(self, routes):
        super().__init__(routes)
        self.headers: list[tuple[str, Mapping[str, str] | None]] = []

    async def get(self, url, *, headers=None):
        self.headers.append((url, headers))
        return await super().get(url, headers=headers)


def ctx(titles=("Treaty Actuary",), locations=("Lusaka",), **config) -> SearchContext:
    return SearchContext(campaign_id="c1", titles=list(titles), keywords=[], locations=list(locations),
                         source_config={**CONFIG, **config})


def routes(**extra) -> dict[str, tuple[int, str]]:
    base = {
        f"{API}?*": (200, fixture_text("search_results.json")),
        "https://careers.example.com/robots.txt": OPEN,
        "https://careers.example.com/jobs/treaty-actuary": (200, fixture_text("search_posting.html")),
        "https://blog.example.com/robots.txt": OPEN,
        "https://blog.example.com/top-10-actuary-jobs": (200, fixture_text("search_blog.html")),
        "https://private.example.com/robots.txt": DENY_ALL,
        f"{GH}/acme/jobs/8940982002?pay_transparency=true": (200, fixture_text("greenhouse_job.json")),
    }
    base.update(extra)
    return base


def test_build_queries_from_titles_and_locations():
    c = SearchContext("c1", ["Treaty Actuary", "Risk Analyst", "treaty actuary"], ["pricing"], ["Lusaka", "Ndola"], {})
    assert build_queries(c, "{title} in {location}", 10) == [
        "Treaty Actuary in Lusaka", "Risk Analyst in Ndola", "pricing in Lusaka"]
    assert build_queries(c, "{title} {location} job", 2) == ["Treaty Actuary Lusaka job", "Risk Analyst Ndola job"]
    assert build_queries(SearchContext("c1", ["A"], [], [], {}), "{title} {location} job", 5) == ["A job"]
    assert build_queries(SearchContext("c1", [], [], [], {}), "{title}", 5) == []


def test_validate_config():
    c = WebSearchConnector(FakeFetcher())
    assert c.validate_config(CONFIG)["endpoint"] == API
    for bad in ({}, {"endpoint": "ftp://x"}, {"endpoint": API, "key_header": "a", "key_param": "b"},
                {"endpoint": API, "max_leads": 0}, {"endpoint": API, "query_template": "no title field"}):
        with pytest.raises(ValueError):
            c.validate_config(bad)
    # an injected provider needs no endpoint
    assert WebSearchConnector(FakeFetcher(), provider=object()).validate_config({}) == {}  # type: ignore[arg-type]


async def test_only_leads_with_a_real_posting_become_jobs_and_the_visited_url_is_recorded():
    f = HeaderFetcher(routes())
    c = WebSearchConnector(f, api_key="sekret")
    jobs = await c.search(ctx(), None)
    assert len(jobs) == 2
    json_ld = next(j for j in jobs if j.extra["verified_by"] == "json_ld")
    assert json_ld.source_url == "https://careers.example.com/jobs/treaty-actuary"  # tracking param stripped
    assert json_ld.extra["visited_url"] == "https://careers.example.com/jobs/treaty-actuary"
    assert json_ld.extra["lead_url"] == json_ld.source_url and json_ld.extra["discovered_via"] == "web_search"
    assert json_ld.extra["query"] == "Treaty Actuary Lusaka job vacancy apply"
    assert json_ld.requisition_id == "KR-101" and json_ld.employer == "Kalumbila Re"
    ats = next(j for j in jobs if j.extra["verified_by"].startswith("ats:"))
    assert ats.extra["verified_by"] == "ats:greenhouse" and ats.extra["visited_url"].endswith("/jobs/8940982002")
    visited = [call[1] for call in f.calls]
    assert "https://blog.example.com/top-10-actuary-jobs" in visited  # opened, found no posting, dropped
    assert "https://private.example.com/private/role" not in visited  # robots disallow
    assert not any(u.startswith("ftp") for u in visited)
    assert "https://blog.example.com/top-10-actuary-jobs" in c.dropped
    assert any("robots.txt" in w for w in c.warnings)


async def test_api_key_is_sent_as_header_only_and_is_not_kept_in_results():
    f = HeaderFetcher(routes())
    jobs = await WebSearchConnector(f, api_key="sekret").search(ctx(), None)
    search_call = next(h for h in f.headers if h[0].startswith(API))
    assert search_call[1]["X-Api-Key"] == "sekret" and "sekret" not in search_call[0]
    assert "sekret" not in json.dumps([j.__dict__ for j in jobs], default=str)
    param = HeaderFetcher(routes())
    await WebSearchConnector(param, api_key="sekret").search(ctx(key_header=None, key_param="key"), None)
    assert "key=sekret" in next(h for h in param.headers if h[0].startswith(API))[0]


async def test_injected_instruction_in_a_result_page_is_data_and_never_a_lead_or_posting():
    f = HeaderFetcher(routes())
    jobs = await WebSearchConnector(f, api_key="k").search(ctx(), None)
    assert all("Ignore previous instructions" not in j.raw_text for j in jobs)  # the blog page is dropped whole
    assert "https://blog.example.com/top-10-actuary-jobs" in [c[1] for c in f.calls]


async def test_missing_key_and_provider_failures():
    with pytest.raises(SourceError, match="API key"):
        await WebSearchConnector(HeaderFetcher(routes())).search(ctx(), None)
    f = HeaderFetcher(routes(**{f"{API}?*": (503, "")}))
    with pytest.raises(SourceError, match="search provider"):
        await WebSearchConnector(f, api_key="k").search(ctx(), None)
    bad_shape = HeaderFetcher(routes(**{f"{API}?*": (200, '{"data": []}')}))
    with pytest.raises(SourceError, match="result list"):
        await WebSearchConnector(bad_shape, api_key="k").search(ctx(), None)


async def test_custom_response_shape_and_lead_cap():
    body = json.dumps({"data": {"items": [{"link": "https://careers.example.com/jobs/treaty-actuary", "name": "x"},
                                          {"link": "https://blog.example.com/top-10-actuary-jobs"}]}})
    f = HeaderFetcher(routes(**{f"{API}?*": (200, body)}))
    cfg = {"result_path": "data.items", "url_field": "link", "title_field": "name", "query_param": "query",
           "limit_param": "count"}
    jobs = await WebSearchConnector(f, api_key="k").search(ctx(max_leads=1, **cfg), None)
    assert [j.requisition_id for j in jobs] == ["KR-101"]
    search_url = next(h[0] for h in f.headers if h[0].startswith(API))
    assert "query=" in search_url and "count=10" in search_url
    assert "https://blog.example.com/top-10-actuary-jobs" not in [c[1] for c in f.calls]  # beyond max_leads


async def test_injected_provider_and_dedupe_of_leads():
    class Provider:
        def __init__(self):
            self.queries: list[str] = []

        async def search(self, query: str, limit: int):
            self.queries.append(query)
            return [SearchHit("https://careers.example.com/jobs/treaty-actuary"),
                    SearchHit("https://CAREERS.example.com/jobs/treaty-actuary/#top")]

    provider = Provider()
    f = HeaderFetcher(routes())
    jobs = await WebSearchConnector(f, provider=provider).search(ctx(titles=["A", "B"]), None)
    assert len(jobs) == 1 and len(provider.queries) == 2
    assert [c[1] for c in f.calls].count("https://careers.example.com/jobs/treaty-actuary") == 1


async def test_check_open_three_states_and_fetch():
    f = FakeFetcher({
        "https://careers.example.com/robots.txt": OPEN,
        "https://careers.example.com/jobs/live": (200, fixture_text("search_posting.html")),
        "https://careers.example.com/jobs/gone": (404, ""),
        "https://careers.example.com/jobs/flaky": (500, ""),
        "https://careers.example.com/jobs/text": (200, fixture_text("careers_closed.html")),
        "https://careers.example.com/jobs/blog": (200, fixture_text("search_blog.html")),
        "https://private.example.com/robots.txt": DENY_ALL,
    })
    c = WebSearchConnector(f, api_key="k")
    base = "https://careers.example.com/jobs"
    assert await c.check_open(f"{base}/live") == "open"
    assert await c.check_open(f"{base}/gone") == "closed"
    assert await c.check_open(f"{base}/text") == "closed"
    assert await c.check_open(f"{base}/flaky") == "unknown"
    assert await c.check_open(f"{base}/blog") == "unknown"
    assert await c.check_open("https://private.example.com/jobs/x") == "unknown"
    assert (await c.fetch(f"{base}/live")).extra["visited_url"] == f"{base}/live"
    with pytest.raises(SourceError):
        await c.fetch(f"{base}/blog")


async def test_rate_limit_is_applied_to_search_and_lead_requests():
    now = [0.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    inner = FakeFetcher(routes())
    polite = PoliteFetcher(inner, RateLimiter(RateLimitSpec(requests_per_minute=60, burst=1),
                                              clock=lambda: now[0], sleep=sleep))
    await WebSearchConnector(polite, api_key="k").search(ctx(), None)
    assert len(inner.calls) > 3 and len(slept) == len(inner.calls) - 1  # one second between every request


def test_search_result_type_is_plain_data():
    hit: Any = SearchHit("https://x.example.com")
    assert hit.title == ""
