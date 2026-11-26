"""Remote-job aggregator APIs: Himalayas and Remotive.

Remote-scope labels on aggregators are unreliable, so connectors pass the label on as a
``remote_hint`` and normalisation re-reads the posting text.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.sources.base import Availability, RateLimitSpec, RawJob, SearchContext, SourceError, register_connector
from app.sources.common import ConnectorBase, join_text, page_availability, queries_for
from app.sources.page import fetch_page
from app.sources.text import from_epoch, html_to_text, parse_iso

ACTIONS = frozenset({"search", "fetch", "check_open"})
HIMALAYAS_API = "https://himalayas.app/jobs/api"
HIMALAYAS_PAGE = 20
HIMALAYAS_MAX_PAGES = 3
REMOTIVE_API = "https://remotive.com/api/remote-jobs"


def _salary(lo: Any, hi: Any, currency: Any, period: Any) -> str | None:
    if lo is None and hi is None:
        return None
    span = f"{lo:,} - {hi:,}" if lo is not None and hi is not None else f"{(lo if lo is not None else hi):,}"
    return f"{currency or ''} {span} {period or ''}".strip()


def himalayas_raw(job: Mapping[str, Any]) -> RawJob:
    expires = from_epoch(job.get("expiryDate"))
    restrictions = [str(r) for r in job.get("locationRestrictions") or []]
    link = job.get("applicationLink") or job.get("guid") or ""
    title = job.get("title") or ""
    return RawJob(
        source_url=job.get("guid") or link, title=title, employer=job.get("companyName") or "",
        raw_text=join_text(title, html_to_text(job.get("description")) or job.get("excerpt")),
        apply_url=link, location_raw=", ".join(restrictions) or None,
        posted_at=from_epoch(job.get("pubDate")),
        pay_text=_salary(job.get("minSalary"), job.get("maxSalary"), job.get("currency"), job.get("salaryPeriod")),
        remote_hint="remote; location restrictions: " + ", ".join(restrictions) if restrictions else "remote",
        extra={"listing_open": True, "employment_type": job.get("employmentType"),
               "seniority": job.get("seniority"), "categories": job.get("categories"),
               "timezone_restrictions": job.get("timezoneRestrictions"),
               "expires_at": expires.isoformat() if expires else None})


@register_connector
class HimalayasConnector(ConnectorBase):
    connector = "himalayas"
    access = "api"
    default_rate_limit = RateLimitSpec(requests_per_minute=10, burst=2)
    permitted_actions = ACTIONS

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        queries = queries_for(ctx, ctx.source_config) or [""]
        found: dict[str, RawJob] = {}
        failures = 0
        self.warnings = []
        for query in queries:
            try:
                for page in range(HIMALAYAS_MAX_PAGES):
                    base = f"{HIMALAYAS_API}/search?q={quote(query)}&" if query else f"{HIMALAYAS_API}?"
                    data = await self.get_json(f"{base}limit={HIMALAYAS_PAGE}&offset={page * HIMALAYAS_PAGE}",
                                               "himalayas")
                    jobs = data.get("jobs", [])
                    for job in jobs:
                        raw = himalayas_raw(job)
                        if raw.title and raw.employer and raw.source_url:
                            found.setdefault(raw.source_url, raw)
                    oldest = min((j.posted_at for j in map(himalayas_raw, jobs) if j.posted_at), default=None)
                    if len(jobs) < HIMALAYAS_PAGE or (since and oldest and oldest < since):
                        break
            except SourceError as exc:
                failures += 1
                self.warnings.append(f"{query or 'all'}: {exc}")
        if failures == len(queries):
            raise SourceError("; ".join(self.warnings))
        return [j for j in found.values() if since is None or j.posted_at is None or j.posted_at >= since]

    async def fetch(self, url: str) -> RawJob:
        return await fetch_page(self.fetcher, url)

    async def check_open(self, url: str) -> Availability:
        return await page_availability(self.fetcher, url, trust_200=True)


def remotive_raw(job: Mapping[str, Any]) -> RawJob:
    place = job.get("candidate_required_location") or ""
    title = job.get("title") or ""
    return RawJob(
        source_url=job.get("url") or "", title=title, employer=job.get("company_name") or "",
        raw_text=join_text(title, html_to_text(job.get("description"))), apply_url=job.get("url"),
        location_raw=place or None, posted_at=parse_iso(job.get("publication_date")),
        pay_text=job.get("salary") or None, remote_hint=f"remote; required location: {place}" if place else "remote",
        extra={"listing_open": True, "category": job.get("category"), "job_type": job.get("job_type"),
               "tags": job.get("tags"), "job_id": job.get("id")})


@register_connector
class RemotiveConnector(ConnectorBase):
    """Remotive asks API users to fetch sparingly, so the default limit is low and one request serves each query."""

    connector = "remotive"
    access = "api"
    default_rate_limit = RateLimitSpec(requests_per_minute=2, burst=1)
    permitted_actions = ACTIONS

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        queries = queries_for(ctx, ctx.source_config) or [""]
        found: dict[str, RawJob] = {}
        failures = 0
        self.warnings = []
        for query in queries:
            url = f"{REMOTIVE_API}?search={quote(query)}" if query else REMOTIVE_API
            try:
                data = await self.get_json(url, "remotive")
            except SourceError as exc:
                failures += 1
                self.warnings.append(f"{query or 'all'}: {exc}")
                continue
            for job in data.get("jobs", []):
                raw = remotive_raw(job)
                if raw.title and raw.employer and raw.source_url:
                    found.setdefault(raw.source_url, raw)
        if failures == len(queries):
            raise SourceError("; ".join(self.warnings))
        return [j for j in found.values() if since is None or j.posted_at is None or j.posted_at >= since]

    async def fetch(self, url: str) -> RawJob:
        return await fetch_page(self.fetcher, url)

    async def check_open(self, url: str) -> Availability:
        return await page_availability(self.fetcher, url, trust_200=True)
