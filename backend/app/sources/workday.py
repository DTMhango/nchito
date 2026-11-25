"""Workday CXS connector: ``POST https://<host>/wday/cxs/<tenant>/<site>/jobs`` (paged).

A board is ``{host, tenant, site[, name]}`` or the string ``"host/tenant/site"``. The listing has
no description, so each posting that survives the ``since`` window is read from its detail
endpoint (capped by ``max_details``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from app.core.clock import utcnow
from app.sources.base import (
    Availability,
    HttpFetcher,
    RateLimitSpec,
    RawJob,
    SearchContext,
    SourceError,
    register_connector,
)
from app.sources.common import ConnectorBase, join_text, queries_for, status_to_availability
from app.sources.http import parse_json
from app.sources.text import host_of, html_to_text, path_parts

PAGE_SIZE = 20
MAX_PAGES = 10
MAX_DETAILS = 100
_LOCALE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2})?$")
_AGO = re.compile(r"posted\s+(?P<n>\d+)\+?\s+(?P<unit>day|week|month)s?\s+ago", re.I)


def parse_posted_on(text: str | None, now: datetime) -> datetime | None:
    """Workday gives relative dates ("Posted 3 Days Ago", "Posted Today", "Posted 30+ Days Ago").

    Returns the start of that day, or ``None`` when the label is open-ended ("30+").
    """
    if not text:
        return None
    lowered = text.lower()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "today" in lowered:
        return midnight
    if "yesterday" in lowered:
        return midnight - timedelta(days=1)
    m = _AGO.search(text)
    if not m or "+" in text:
        return None
    days = int(m["n"]) * {"day": 1, "week": 7, "month": 30}[m["unit"].lower()]
    return midnight - timedelta(days=days)


def parse_board(entry: Mapping[str, Any] | str) -> dict[str, str]:
    if isinstance(entry, str):
        parts = [p for p in entry.strip().split("/") if p]
        if len(parts) != 3:
            raise ValueError("a Workday board is host/tenant/site")
        entry = {"host": parts[0], "tenant": parts[1], "site": parts[2]}
    board = {k: str(entry.get(k, "")).strip() for k in ("host", "tenant", "site", "name")}
    if not (board["host"] and board["tenant"] and board["site"]):
        raise ValueError("a Workday board needs host, tenant and site")
    if not re.fullmatch(r"[a-z0-9.-]+\.myworkdayjobs\.com", board["host"], re.I) and "." not in board["host"]:
        raise ValueError("host must be the Workday host, e.g. acme.wd5.myworkdayjobs.com")
    return board


def _api(board: Mapping[str, str]) -> str:
    return f"https://{board['host']}/wday/cxs/{board['tenant']}/{board['site']}"


def board_from_url(url: str) -> dict[str, str]:
    host = host_of(url)
    parts = [p for p in path_parts(url) if not _LOCALE.match(p)]
    if not host or not parts or parts[0] in ("job", "wday"):
        raise SourceError("not a Workday posting URL")
    return {"host": host, "tenant": host.split(".")[0], "site": parts[0]}


def detail_path(url: str) -> str:
    """The ``/job/...`` part of a public Workday posting URL."""
    m = re.search(r"(/job/.+?)(?:\?|#|$)", url)
    if not m:
        raise SourceError("not a Workday posting URL")
    return m.group(1)


def workday_raw(board: Mapping[str, str], detail: Mapping[str, Any], listing: Mapping[str, Any] | None,
                now: datetime) -> RawJob:
    info = detail.get("jobPostingInfo") or {}
    org = (detail.get("hiringOrganization") or {}).get("name")
    title = info.get("title") or (listing or {}).get("title") or ""
    path = (listing or {}).get("externalPath") or ""
    url = info.get("externalUrl") or f"https://{board['host']}/{board['site']}{path}"
    bullets = (listing or {}).get("bulletFields") or []
    req = info.get("jobReqId") or (bullets[0] if bullets else None)
    extra_locations = info.get("additionalLocations") or []
    location = ", ".join([x for x in [info.get("location"), *extra_locations] if x])
    return RawJob(
        source_url=url, title=title, employer=board.get("name") or org or board["tenant"].replace("-", " ").title(),
        raw_text=join_text(title, html_to_text(info.get("jobDescription"))), apply_url=url,
        location_raw=location or (listing or {}).get("locationsText"),
        posted_at=parse_posted_on(info.get("postedOn") or (listing or {}).get("postedOn"), now),
        requisition_id=str(req) if req else None, apply_method_hint="workday",
        extra={"listing_open": True, "board": f"{board['host']}/{board['tenant']}/{board['site']}",
               "time_type": info.get("timeType"), "can_apply": info.get("canApply")})


@register_connector
class WorkdayConnector(ConnectorBase):
    connector = "workday"
    access = "api"
    default_rate_limit = RateLimitSpec(requests_per_minute=30, burst=3)
    permitted_actions = frozenset({"search", "fetch", "check_open"})

    def __init__(self, fetcher: HttpFetcher, *, now: Any = utcnow) -> None:
        super().__init__(fetcher)
        self._now = now

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        raw = config.get("boards")
        if not isinstance(raw, list) or not raw:
            raise ValueError("boards must be a non-empty list of Workday boards")
        out = dict(config)
        out["boards"] = [parse_board(b) for b in raw]
        return out

    async def _listing(self, board: Mapping[str, str], query: str, since: datetime | None, now: datetime) -> list[dict[str, Any]]:
        postings: list[dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            status, body = await self.fetcher.post_json(
                f"{_api(board)}/jobs", {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": query})
            data = parse_json(status, body, f"workday {board['tenant']}")
            page = data.get("jobPostings", [])
            postings.extend(page)
            offset += PAGE_SIZE
            if not page or offset >= int(data.get("total") or 0):
                break
        keep = []
        for p in postings:
            posted = parse_posted_on(p.get("postedOn"), now)
            if since is None or posted is None or posted >= since.replace(hour=0, minute=0, second=0, microsecond=0):
                keep.append(p)
        return keep

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        boards = self.validate_config(ctx.source_config)["boards"]
        queries = queries_for(ctx, ctx.source_config) or [""]
        now = self._now()
        self.warnings = []
        found: list[RawJob] = []
        failures = 0
        for board in boards:
            try:
                listed: dict[str, dict[str, Any]] = {}
                for query in queries:
                    for p in await self._listing(board, query, since, now):
                        if p.get("externalPath"):
                            listed.setdefault(p["externalPath"], p)
                for path, p in list(listed.items())[:MAX_DETAILS]:
                    detail = parse_json(*await self.fetcher.get(f"{_api(board)}{quote(path, safe='/')}"),
                                        f"workday {board['tenant']} posting")
                    found.append(workday_raw(board, detail, p, now))
            except SourceError as exc:
                failures += 1
                self.warnings.append(f"{board['tenant']}/{board['site']}: {exc}")
        if failures == len(boards):
            raise SourceError("; ".join(self.warnings))
        return found

    async def fetch(self, url: str) -> RawJob:
        board = board_from_url(url)
        data = parse_json(*await self.fetcher.get(f"{_api(board)}{detail_path(url)}"), "workday posting")
        return workday_raw(board, data, None, self._now())

    async def check_open(self, url: str) -> Availability:
        try:
            board = board_from_url(url)
            status, body = await self.fetcher.get(f"{_api(board)}{detail_path(url)}")
        except SourceError:
            return "unknown"
        result = status_to_availability(status)
        if result == "open":
            try:
                if json.loads(body).get("jobPostingInfo", {}).get("canApply") is False:
                    return "unknown"
            except ValueError:
                return "unknown"
        return result
