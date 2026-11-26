"""Applicant-tracking-system board connectors: Greenhouse, Lever, Ashby, Workable.

Each reads the public JSON API of an employer's hosted board. Driven by the watched-employer
list: the orchestrator merges watched employers of the matching board type into
``config["boards"]``. A posting present in a board listing is open (``extra["listing_open"]``);
pay and deadline are carried only when the board states them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.sources.base import (
    Availability,
    RateLimitSpec,
    RawJob,
    SearchContext,
    SourceError,
    register_connector,
)
from app.sources.common import ConnectorBase, join_text, normalise_boards
from app.sources.text import from_epoch, html_to_text, parse_date, parse_iso, path_parts

ACTIONS = frozenset({"search", "fetch", "check_open"})
BOARD_RATE = RateLimitSpec(requests_per_minute=60, burst=5)


def _recent(posted: datetime | None, since: datetime | None) -> bool:
    return since is None or posted is None or posted >= since


class _BoardConnector(ConnectorBase):
    access = "api"
    default_rate_limit = BOARD_RATE
    permitted_actions = ACTIONS

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(config)
        out["boards"] = normalise_boards(config)
        return out

    async def _board_jobs(self, board: dict[str, str], config: Mapping[str, Any]) -> list[RawJob]:
        raise NotImplementedError

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        boards = normalise_boards(ctx.source_config)
        self.warnings = []
        found: list[RawJob] = []
        failures = 0
        for board in boards:
            try:
                jobs = await self._board_jobs(board, ctx.source_config)
                found.extend(job for job in jobs if _recent(job.posted_at, since))
            except SourceError as exc:
                failures += 1
                self.warnings.append(f"{board['slug']}: {exc}")
        if failures == len(boards):
            raise SourceError("; ".join(self.warnings))
        return found


# ----- Greenhouse -------------------------------------------------------------------------

GH_API = "https://boards-api.greenhouse.io/v1/boards"
_GH_JOB = re.compile(r"/(?P<slug>[^/]+)/jobs/(?P<id>\d+)")


def _gh_pay(job: Mapping[str, Any]) -> str | None:
    ranges = job.get("pay_input_ranges") or []
    if not ranges:
        return None
    r = ranges[0]
    low, high = r.get("min_cents"), r.get("max_cents")
    if low is None or high is None:
        return None
    return f"{r.get('currency_type', '')} {low / 100:,.0f} - {high / 100:,.0f}".strip()


def greenhouse_raw(job: Mapping[str, Any], slug: str, name: str | None) -> RawJob:
    offices = ", ".join(o.get("name", "") for o in job.get("offices") or [] if o.get("name"))
    departments = [d.get("name") for d in job.get("departments") or [] if d.get("name")]
    title = job.get("title") or ""
    employer = job.get("company_name") or name or slug
    url = job.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{job.get('id')}"
    deadline = parse_date(job.get("application_deadline")) if isinstance(job.get("application_deadline"), str) else None
    return RawJob(
        source_url=url,
        title=title,
        employer=employer,
        raw_text=join_text(title, html_to_text(job.get("content"))),
        apply_url=url,
        location_raw=(job.get("location") or {}).get("name") or offices or None,
        posted_at=parse_iso(job.get("first_published")) or parse_iso(job.get("updated_at")),
        deadline=deadline,
        requisition_id=str(job["requisition_id"]) if job.get("requisition_id") else None,
        apply_method_hint="greenhouse",
        pay_text=_gh_pay(job),
        extra={"listing_open": True, "board": slug, "departments": departments, "job_id": str(job.get("id")),
               "updated_at": job.get("updated_at")},
    )


@register_connector
class GreenhouseConnector(_BoardConnector):
    connector = "greenhouse"

    async def _board_jobs(self, board: dict[str, str], config: Mapping[str, Any]) -> list[RawJob]:
        data = await self.get_json(f"{GH_API}/{board['slug']}/jobs?content=true", f"greenhouse {board['slug']}")
        return [greenhouse_raw(j, board["slug"], board.get("name")) for j in data.get("jobs", [])]

    async def fetch(self, url: str) -> RawJob:
        m = _GH_JOB.search(url)
        if not m:
            raise SourceError("not a Greenhouse posting URL")
        data = await self.get_json(f"{GH_API}/{m['slug']}/jobs/{m['id']}?pay_transparency=true", "greenhouse job")
        return greenhouse_raw(data, m["slug"], None)

    async def check_open(self, url: str) -> Availability:
        m = _GH_JOB.search(url)
        if not m:
            return "unknown"
        return await self.exists_status(f"{GH_API}/{m['slug']}/jobs/{m['id']}")


# ----- Lever ------------------------------------------------------------------------------

_LEVER_URL = re.compile(r"/(?P<slug>[^/]+)/(?P<id>[0-9a-f]{8}-[0-9a-f-]{27})")


def _lever_api(config_or_url: Mapping[str, Any] | str) -> str:
    eu = "lever.co" in config_or_url and ".eu." in config_or_url if isinstance(config_or_url, str) \
        else bool(config_or_url.get("eu"))
    return "https://api.eu.lever.co/v0/postings" if eu else "https://api.lever.co/v0/postings"


def lever_raw(post: Mapping[str, Any], slug: str, name: str | None) -> RawJob:
    cats = post.get("categories") or {}
    lists = "\n".join(f"{item.get('text', '')}\n{html_to_text(item.get('content'))}"
                      for item in post.get("lists") or [])
    salary = post.get("salaryRange")
    pay = None
    if salary and salary.get("min") is not None and salary.get("max") is not None:
        pay = f"{salary.get('currency', '')} {salary['min']:,} - {salary['max']:,} per {salary.get('interval', 'year')}"
    title = post.get("text") or ""
    return RawJob(
        source_url=post.get("hostedUrl") or "",
        title=title,
        employer=name or slug.replace("-", " ").title(),
        raw_text=join_text(title, post.get("descriptionPlain") or html_to_text(post.get("description")), lists,
                           post.get("additionalPlain")),
        apply_url=post.get("applyUrl") or post.get("hostedUrl"),
        location_raw=cats.get("location") or ", ".join(cats.get("allLocations") or []) or None,
        posted_at=from_epoch(post.get("createdAt"), millis=True),
        apply_method_hint="lever",
        pay_text=pay.strip() if pay else None,
        remote_hint=post.get("workplaceType"),
        extra={"listing_open": True, "board": slug, "team": cats.get("team"), "commitment": cats.get("commitment"),
               "job_id": post.get("id"), "country": post.get("country")},
    )


@register_connector
class LeverConnector(_BoardConnector):
    connector = "lever"

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        out = super().validate_config(config)
        out["eu"] = bool(config.get("eu", False))
        return out

    async def _board_jobs(self, board: dict[str, str], config: Mapping[str, Any]) -> list[RawJob]:
        data = await self.get_json(f"{_lever_api(config)}/{board['slug']}?mode=json", f"lever {board['slug']}")
        if not isinstance(data, list):
            raise SourceError("lever: unexpected response shape")
        return [lever_raw(p, board["slug"], board.get("name")) for p in data]

    async def fetch(self, url: str) -> RawJob:
        m = _LEVER_URL.search(url)
        if not m:
            raise SourceError("not a Lever posting URL")
        data = await self.get_json(f"{_lever_api(url)}/{m['slug']}/{m['id']}", "lever posting")
        return lever_raw(data, m["slug"], None)

    async def check_open(self, url: str) -> Availability:
        m = _LEVER_URL.search(url)
        if not m:
            return "unknown"
        return await self.exists_status(f"{_lever_api(url)}/{m['slug']}/{m['id']}")


# ----- Ashby ------------------------------------------------------------------------------

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"


def ashby_raw(job: Mapping[str, Any], slug: str, name: str | None) -> RawJob:
    comp = job.get("compensation") or {}
    title = job.get("title") or ""
    address = ((job.get("address") or {}).get("postalAddress") or {})
    places = (address.get("addressLocality"), address.get("addressCountry"))
    location = job.get("location") or ", ".join(x for x in places if x)
    return RawJob(
        source_url=job.get("jobUrl") or "",
        title=title,
        employer=name or slug.replace("-", " ").title(),
        raw_text=join_text(title, job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml"))),
        apply_url=job.get("applyUrl") or job.get("jobUrl"),
        location_raw=location or None,
        posted_at=parse_iso(job.get("publishedAt")),
        apply_method_hint="ashby",
        pay_text=comp.get("compensationTierSummary") or None,
        remote_hint=job.get("workplaceType") or ("Remote" if job.get("isRemote") else None),
        extra={"listing_open": True, "board": slug, "department": job.get("department"), "team": job.get("team"),
               "employment_type": job.get("employmentType"), "job_id": job.get("id")},
    )


@register_connector
class AshbyConnector(_BoardConnector):
    connector = "ashby"

    async def _load(self, slug: str) -> list[dict[str, Any]]:
        data = await self.get_json(f"{ASHBY_API}/{slug}?includeCompensation=true", f"ashby {slug}")
        return [j for j in data.get("jobs", []) if j.get("isListed", True)]

    async def _board_jobs(self, board: dict[str, str], config: Mapping[str, Any]) -> list[RawJob]:
        return [ashby_raw(j, board["slug"], board.get("name")) for j in await self._load(board["slug"])]

    def _parts(self, url: str) -> tuple[str, str]:
        parts = path_parts(url)
        if len(parts) < 2:
            raise SourceError("not an Ashby posting URL")
        return parts[0], parts[1]

    async def fetch(self, url: str) -> RawJob:
        slug, job_id = self._parts(url)
        for job in await self._load(slug):
            if job.get("id") == job_id:
                return ashby_raw(job, slug, None)
        raise SourceError("posting not found on the board")

    async def check_open(self, url: str) -> Availability:
        try:
            slug, job_id = self._parts(url)
            jobs = await self._load(slug)
        except SourceError:
            return "unknown"
        return "open" if any(j.get("id") == job_id for j in jobs) else "closed"


# ----- Workable ---------------------------------------------------------------------------

WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts"


def workable_raw(job: Mapping[str, Any], slug: str, account_name: str | None) -> RawJob:
    location = ", ".join(x for x in (job.get("city"), job.get("state"), job.get("country")) if x)
    title = job.get("title") or ""
    url = job.get("url") or job.get("shortlink") or ""
    return RawJob(
        source_url=url,
        title=title,
        employer=account_name or slug.replace("-", " ").title(),
        raw_text=join_text(title, html_to_text(job.get("description"))),
        apply_url=job.get("application_url") or url,
        location_raw=location or None,
        posted_at=parse_iso(job.get("published_on") or job.get("created_at")),
        requisition_id=job.get("code") or None,
        apply_method_hint="workable",
        remote_hint="remote" if job.get("telecommuting") else None,
        extra={"listing_open": True, "board": slug, "shortcode": job.get("shortcode"),
               "employment_type": job.get("employment_type"), "department": job.get("department"),
               "function": job.get("function"), "industry": job.get("industry")},
    )


@register_connector
class WorkableConnector(_BoardConnector):
    connector = "workable"

    async def _load(self, slug: str) -> dict[str, Any]:
        data = await self.get_json(f"{WORKABLE_API}/{slug}?details=true", f"workable {slug}")
        if not isinstance(data, dict):
            raise SourceError("workable: unexpected response shape")
        return data

    async def _board_jobs(self, board: dict[str, str], config: Mapping[str, Any]) -> list[RawJob]:
        data = await self._load(board["slug"])
        name = board.get("name") or data.get("name")
        return [workable_raw(j, board["slug"], name) for j in data.get("jobs", [])]

    def _parts(self, url: str) -> tuple[str, str]:
        parts = path_parts(url)
        if len(parts) >= 3 and parts[1] == "j":
            return parts[0], parts[2]
        raise SourceError("a Workable posting URL with the company in it is needed "
                          "(apply.workable.com/<company>/j/<id>)")

    async def fetch(self, url: str) -> RawJob:
        slug, shortcode = self._parts(url)
        data = await self._load(slug)
        for job in data.get("jobs", []):
            if job.get("shortcode") == shortcode:
                return workable_raw(job, slug, data.get("name"))
        raise SourceError("posting not found on the board")

    async def check_open(self, url: str) -> Availability:
        try:
            slug, shortcode = self._parts(url)
            data = await self._load(slug)
        except SourceError:
            return "unknown"
        return "open" if any(j.get("shortcode") == shortcode for j in data.get("jobs", [])) else "closed"


__all__ = ["AshbyConnector", "GreenhouseConnector", "LeverConnector", "WorkableConnector"]
