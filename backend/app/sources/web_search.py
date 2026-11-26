"""Web search connector: search results are leads, never postings (DESIGN.md 6, wave 2).

A search provider returns candidate URLs for queries built from the campaign's titles and
locations. Each lead is then opened through the injected fetcher and kept only when the page
holds a real posting: a known ATS posting URL (read through that ATS's own connector) or a page
with JSON-LD ``JobPosting`` data. Anything else is dropped. The URL actually requested is recorded
in ``extra["visited_url"]``, next to the lead URL and the query that found it.

``SearchProvider`` is provider-agnostic. DESIGN names no provider, so the concrete one is a generic
JSON search API (``JsonSearchProvider``) configured by endpoint, key placement and field names. The
endpoint, response shape and API key all belong to the owner's **Search API connection**
(``app.connect.search_api``), handed to the connector at construction as a ``SearchConnection``; a
source's own config may only pick that connection (``connection_id``), override the query template and set
its search limits. Provider keys left in an older source config are ignored. The key is never logged.
robots.txt is honoured for every lead page. Result text is never read as a posting: only the URL is used,
and the posting text comes from the page itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

from app.sources.base import (
    Availability,
    HttpFetcher,
    RateLimitSpec,
    RawJob,
    SearchContext,
    SourceError,
    connector_class,
    register_connector,
)
from app.sources.common import ConnectorBase, closed_by_page
from app.sources.detect import detect_from_url
from app.sources.http import parse_json
from app.sources.page import job_postings, parse_page
from app.sources.web import RobotsGuard, ats_target, canonical_url, knob


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str = ""


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchHit]: ...


class JsonSearchProvider:
    """A generic JSON search API: GET ``endpoint?<query_param>=...&<limit_param>=...`` returning a list of results.

    ``api_key`` goes in the header ``key_header`` or the query parameter ``key_param``. ``result_path`` is a
    dotted path to the result list; ``url_field`` and ``title_field`` name the fields of one result.
    """

    def __init__(self, fetcher: HttpFetcher, *, endpoint: str, api_key: str, query_param: str, limit_param: str | None,
                 key_header: str | None, key_param: str | None, result_path: str, url_field: str,
                 title_field: str) -> None:
        self._fetcher = fetcher
        self._endpoint = endpoint
        self._key = api_key
        self._query_param = query_param
        self._limit_param = limit_param
        self._key_header = key_header
        self._key_param = key_param
        self._result_path = result_path
        self._url_field = url_field
        self._title_field = title_field

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        params = {self._query_param: query}
        if self._limit_param:
            params[self._limit_param] = str(limit)
        if self._key_param:
            params[self._key_param] = self._key
        headers = {self._key_header: self._key, "Accept": "application/json"} if self._key_header \
            else {"Accept": "application/json"}
        joiner = "&" if urlsplit(self._endpoint).query else "?"
        status, body = await self._fetcher.get(f"{self._endpoint}{joiner}{urlencode(params)}", headers=headers)
        data: Any = parse_json(status, body, "search provider")
        for part in filter(None, self._result_path.split(".")):
            data = data.get(part) if isinstance(data, dict) else None
        if not isinstance(data, list):
            raise SourceError("search provider: no result list at the configured path")
        hits: list[SearchHit] = []
        for item in data[:limit]:
            if isinstance(item, dict) and isinstance(item.get(self._url_field), str):
                hits.append(SearchHit(url=item[self._url_field].strip(), title=str(item.get(self._title_field) or "")))
        return hits


PROVIDER_SHAPE = {"query_param": "q", "limit_param": None, "key_header": None, "key_param": None,
                  "result_path": "results", "url_field": "url", "title_field": "title"}
PROVIDER_KEYS = frozenset({"endpoint", *PROVIDER_SHAPE})
SOURCE_KNOBS = ("max_queries", "results_per_query", "max_leads", "query_template")


@dataclass(frozen=True)
class SearchConnection:
    """What the Search API connection gives a web search source: where to search, how, and the key."""

    endpoint: str
    api_key: str
    shape: Mapping[str, Any]

    def provider(self, fetcher: HttpFetcher) -> JsonSearchProvider:
        shape = {key: self.shape.get(key, default) for key, default in PROVIDER_SHAPE.items()}
        return JsonSearchProvider(fetcher, endpoint=self.endpoint, api_key=self.api_key, **shape)


def _location_words(locations: Sequence[str]) -> list[str]:
    return [loc.strip() for loc in locations if loc.strip()] or [""]


def build_queries(ctx: SearchContext, template: str, limit: int) -> list[str]:
    """One phrase per title (rotating through the campaign's locations), at most ``limit``."""
    titles = [t.strip() for t in [*ctx.titles, *ctx.keywords] if t.strip()]
    places = _location_words(ctx.locations)
    queries: list[str] = []
    unique = {t.lower(): t for t in reversed(titles)}  # case-insensitive, first spelling wins
    for index, title in enumerate(t for t in titles if unique[t.lower()] == t):
        phrase = " ".join(template.format(title=title, location=places[index % len(places)]).split())
        if phrase not in queries:
            queries.append(phrase)
    return queries[:limit]


@register_connector
class WebSearchConnector(ConnectorBase):
    connector = "web_search"
    access = "api"
    default_rate_limit = RateLimitSpec(requests_per_minute=10, burst=2)
    permitted_actions = frozenset({"search", "fetch", "check_open"})

    def __init__(self, fetcher: HttpFetcher, *, search_connection: SearchConnection | None = None,
                 provider: SearchProvider | None = None, settings: Mapping[str, Any] | None = None) -> None:
        super().__init__(fetcher)
        self._connection = search_connection
        self._provider = provider
        self.settings = settings
        self.robots = RobotsGuard(fetcher)
        self.dropped: list[str] = []

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """The source's own part: ``connection_id``, the query template and its search limits. The endpoint and
        response shape belong to the Search API connection, so any left here are dropped."""
        out = {k: v for k, v in config.items() if k not in PROVIDER_KEYS}
        if out.get("connection_id") is not None and not str(out["connection_id"]).strip():
            out.pop("connection_id")
        for key in SOURCE_KNOBS:
            if config.get(key) is not None:
                out[key] = knob(f"sources.search.{key}", config)
        return out

    def _search_provider(self) -> SearchProvider:
        if self._provider is not None:
            return self._provider
        if self._connection is None or not self._connection.api_key:
            raise SourceError("no search API connection: connect the search provider first (Settings, Connections)")
        return self._connection.provider(self.fetcher)

    # ----- search -------------------------------------------------------------------------

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        self.warnings, self.dropped = [], []
        cfg = ctx.source_config
        provider = self._search_provider()
        template = knob("sources.search.query_template", cfg, self.settings)
        queries = build_queries(ctx, template, knob("sources.search.max_queries", cfg, self.settings))
        if not queries:
            raise SourceError("the campaign has no titles or keywords to search for")
        per_query = knob("sources.search.results_per_query", cfg, self.settings)
        max_leads = knob("sources.search.max_leads", cfg, self.settings)

        leads: dict[str, str] = {}  # canonical url -> query that found it
        failures = 0
        for query in queries:
            try:
                hits = await provider.search(query, per_query)
            except SourceError as exc:
                failures += 1
                self.warnings.append(f"{query!r}: {exc}")
                continue
            for hit in hits:
                if urlsplit(hit.url).scheme in ("http", "https"):
                    leads.setdefault(canonical_url(hit.url), query)
        if failures == len(queries):
            raise SourceError("; ".join(self.warnings))

        found: dict[str, RawJob] = {}
        for url, query in list(leads.items())[:max_leads]:
            job = await self._verify(url, query)
            if job is None:
                self.dropped.append(url)
                continue
            if since is None or job.posted_at is None or job.posted_at >= since:
                found.setdefault(job.source_url, job)
        return list(found.values())

    async def _verify(self, url: str, query: str) -> RawJob | None:
        """The posting behind a lead, or ``None`` when the page does not hold a real, live one."""
        try:
            job = await self._read_posting(url)
        except SourceError as exc:
            self.warnings.append(f"{url}: {exc}")
            return None
        if job is None:
            return None
        job.extra.update(discovered_via="web_search", lead_url=url, visited_url=job.extra.get("visited_url", url),
                         query=query)
        return job

    async def _read_posting(self, url: str) -> RawJob | None:
        found = detect_from_url(url)
        if found.connector:
            name, _ = ats_target(found)
            try:
                job = await connector_class(name)(self.fetcher).fetch(url)  # type: ignore[call-arg]
            except SourceError:
                return None  # a board page, not one posting
            job.extra.update(verified_by=f"ats:{found.connector}", visited_url=url)
            return job
        if not await self.robots.allowed(url):
            self.warnings.append(f"{url}: robots.txt does not allow reading this page")
            return None
        status, body = await self.fetcher.get(url)
        if status != 200 or closed_by_page(body) or not job_postings(body):
            return None
        job = parse_page(url, body)
        job.source_url = canonical_url(url)
        job.extra.update(verified_by="json_ld", visited_url=url)
        return job

    # ----- fetch and check_open ------------------------------------------------------------

    async def fetch(self, url: str) -> RawJob:
        job = await self._read_posting(url)
        if job is None:
            raise SourceError("the page does not hold a readable job posting")
        return job

    async def check_open(self, url: str) -> Availability:
        found = detect_from_url(url)
        if found.connector:
            name, _ = ats_target(found)
            return await connector_class(name)(self.fetcher).check_open(url)  # type: ignore[call-arg]
        try:
            if not await self.robots.allowed(url):
                return "unknown"
            status, body = await self.fetcher.get(url)
        except SourceError:
            return "unknown"
        if status in (404, 410) or (status == 200 and closed_by_page(body)):
            return "closed"
        return "open" if status == 200 and job_postings(body) else "unknown"
