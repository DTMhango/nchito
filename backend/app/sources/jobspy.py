"""JobSpy connector: LinkedIn, Indeed, Glassdoor and Google Jobs through the optional ``jobspy`` library.

Best effort and **off by default** (``sources.jobspy.enabled``): datacentre IPs get blocked and the
boards forbid automated reading. These boards are *discovery only*: the connector never applies,
and a posting's actions are whatever the ``Source`` row's ``permitted_actions`` allows (a scraped
board is registered without any ``apply_*`` action).

- The library is an optional extra (``pip install nchito[jobspy]``). Importing this module never
  imports it; ``validate_config`` reports "not installed" instead of failing.
- The library does its own HTTP, so it sits behind ``JobBoardScraper``, a thin adapter that tests
  replace. It is the one place the connector reaches the network outside the injected fetcher, and
  it is paced by ``sources.jobspy.board_delay_seconds`` between calls.
- Every found link is opened through the injected (rate-limited, robots-aware) fetcher to confirm it
  is real and live (``sources.jobspy.verify_links``). A page that is blocked or off-limits stays,
  marked ``link_verified: "unknown"``; a 404/410 or a "no longer available" page is dropped.
- Unknown stays unknown: remote status, requisition id and pay are filled only when the board states them.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Protocol

from app.sources.base import (
    Availability,
    HttpFetcher,
    RateLimitSpec,
    RawJob,
    SearchContext,
    SourceError,
    register_connector,
)
from app.sources.common import ConnectorBase, closed_by_page, join_text, queries_for
from app.sources.page import fetch_page
from app.sources.text import parse_iso
from app.sources.web import RobotsGuard, canonical_url, knob

BOARD_LABELS = {"linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor", "google": "Google Jobs",
                "zip_recruiter": "ZipRecruiter"}
Sleep = Callable[[float], Awaitable[None]]


def jobspy_installed() -> bool:
    return importlib.util.find_spec("jobspy") is not None


class JobBoardScraper(Protocol):
    """One board search, as a list of row dicts (JobSpy's DataFrame columns)."""

    def scrape(self, board: str, query: str, location: str | None, results: int,
               hours_old: int) -> list[dict[str, Any]]: ...


class JobSpyScraper:
    """The real adapter. Imports the library on first use, so a missing install fails only here."""

    def scrape(self, board: str, query: str, location: str | None, results: int,
               hours_old: int) -> list[dict[str, Any]]:
        try:
            from jobspy import scrape_jobs  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SourceError("JobSpy is not installed (pip install 'nchito[jobspy]')") from exc
        try:
            frame = scrape_jobs(site_name=[board], search_term=query, location=location or None,
                                results_wanted=results, hours_old=hours_old)
        except Exception as exc:  # the library raises whatever the board's blocking looks like
            raise SourceError(f"{board}: {type(exc).__name__}") from exc
        return list(frame.to_dict("records"))


def _clean(value: Any) -> Any:
    """DataFrame gaps arrive as NaN/NaT/None: all mean "not stated"."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if type(value).__name__ in ("NaTType", "NAType"):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _posted(value: Any) -> datetime | None:
    value = _clean(value)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return parse_iso(str(value)) if value is not None else None


def _pay(row: Mapping[str, Any]) -> str | None:
    low, high = _clean(row.get("min_amount")), _clean(row.get("max_amount"))
    if low is None and high is None:
        return None
    span = f"{low:g} - {high:g}" if low is not None and high is not None and low != high \
        else f"{(low if low is not None else high):g}"
    currency = _clean(row.get("currency")) or ""
    interval = _clean(row.get("interval"))
    return f"{currency} {span}{f' per {interval}' if interval else ''}".strip()


def row_to_raw(row: Mapping[str, Any], board: str) -> RawJob | None:
    url, title, company = _clean(row.get("job_url")), _clean(row.get("title")), _clean(row.get("company"))
    if not url or not title:
        return None
    direct = _clean(row.get("job_url_direct"))
    remote = _clean(row.get("is_remote"))
    description = str(_clean(row.get("description")) or "")
    return RawJob(
        source_url=canonical_url(str(url)), title=str(title).strip(),
        employer=str(company).strip() if company else "Unknown employer",
        raw_text=join_text(str(title), description), apply_url=canonical_url(str(direct)) if direct else None,
        location_raw=_clean(row.get("location")), posted_at=_posted(row.get("date_posted")),
        pay_text=_pay(row), remote_hint="remote" if remote is True else None,
        extra={"discovered_via": "jobspy", "board": board, "board_name": BOARD_LABELS.get(board, board),
               "board_job_id": _clean(row.get("id")), "job_type": _clean(row.get("job_type")),
               "listing_open": None, "scraped": True})


@register_connector
class JobSpyConnector(ConnectorBase):
    connector = "jobspy"
    access = "html"
    default_rate_limit = RateLimitSpec(requests_per_minute=6, burst=1)
    # Discovery and plain reads only. Applying is never declared here; the Source row decides.
    permitted_actions = frozenset({"search", "fetch", "check_open"})

    def __init__(self, fetcher: HttpFetcher, *, scraper: JobBoardScraper | None = None,
                 settings: Mapping[str, Any] | None = None, sleep: Sleep = asyncio.sleep,
                 installed: Callable[[], bool] = jobspy_installed) -> None:
        super().__init__(fetcher)
        self._scraper = scraper
        self.settings = settings
        self._sleep = sleep
        self._installed = installed
        self.robots = RobotsGuard(fetcher)

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        if self._scraper is None and not self._installed():
            raise ValueError("JobSpy is not installed on this server (pip install 'nchito[jobspy]')")
        out = dict(config)
        for key in ("boards", "results_per_board", "board_delay_seconds", "max_age_hours", "verify_links"):
            if config.get(key) is not None:
                out[key] = knob(f"sources.jobspy.{key}", config)
        return out

    # ----- search -------------------------------------------------------------------------

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        self.warnings = []
        cfg = ctx.source_config
        if not knob("sources.jobspy.enabled", cfg, self.settings):
            raise SourceError("JobSpy is switched off (setting sources.jobspy.enabled)")
        scraper = self._scraper
        if scraper is None:
            if not self._installed():
                raise SourceError("JobSpy is not installed on this server")
            scraper = JobSpyScraper()
        boards = knob("sources.jobspy.boards", cfg, self.settings)
        per_board = knob("sources.jobspy.results_per_board", cfg, self.settings)
        delay = knob("sources.jobspy.board_delay_seconds", cfg, self.settings)
        hours = self._window_hours(knob("sources.jobspy.max_age_hours", cfg, self.settings), since)
        queries = queries_for(ctx, cfg)
        if not queries:
            raise SourceError("the campaign has no titles or keywords to search for")
        location = next((loc for loc in ctx.locations if loc.strip()), None)

        found: dict[str, RawJob] = {}
        calls = failures = 0
        for board in boards:
            for query in queries:
                if calls:
                    await self._sleep(delay)
                calls += 1
                try:
                    rows = await asyncio.to_thread(scraper.scrape, board, query, location, per_board, hours)
                except SourceError as exc:
                    failures += 1
                    self.warnings.append(str(exc))
                    continue
                for row in rows[:per_board]:
                    raw = row_to_raw(row, board)
                    if raw is not None and (since is None or raw.posted_at is None or raw.posted_at >= since):
                        found.setdefault(raw.source_url, raw)
        if failures == calls:
            raise SourceError("; ".join(self.warnings) or "no board could be searched")
        jobs = list(found.values())
        if knob("sources.jobspy.verify_links", cfg, self.settings):
            jobs = await self._verified(jobs)
        return jobs

    @staticmethod
    def _window_hours(cap: int, since: datetime | None) -> int:
        if since is None:
            return cap
        elapsed = (datetime.now(UTC) - since).total_seconds() / 3600
        return max(1, min(cap, math.ceil(elapsed)))

    async def _verified(self, jobs: list[RawJob]) -> list[RawJob]:
        kept: list[RawJob] = []
        for job in jobs:
            state = await self._link_state(job.source_url)
            if state == "closed":
                self.warnings.append(f"{job.source_url}: dropped, the posting is gone")
                continue
            job.extra["link_verified"] = state
            kept.append(job)
        return kept

    async def _link_state(self, url: str) -> Availability:
        try:
            if not await self.robots.allowed(url):
                return "unknown"
            status, body = await self.fetcher.get(url)
        except SourceError:
            return "unknown"
        if status in (404, 410):
            return "closed"
        if status != 200:
            return "unknown"
        return "closed" if closed_by_page(body) else "open"

    # ----- fetch and check_open ------------------------------------------------------------

    async def fetch(self, url: str) -> RawJob:
        if not await self.robots.allowed(url):
            raise SourceError("robots.txt does not allow reading this page")
        return await fetch_page(self.fetcher, url)

    async def check_open(self, url: str) -> Availability:
        # A plain 200 on a scraped board proves nothing (login walls, soft 404s): only "gone" is certain.
        state = await self._link_state(url)
        return "closed" if state == "closed" else "unknown"
