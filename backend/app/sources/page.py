"""Read one posting page: JSON-LD ``JobPosting`` when present, else title and visible text.

Used by manual capture and as the ``fetch`` fallback of feed sources. The page is untrusted
data; nothing in it is executed or followed beyond the single GET.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any

from app.sources.base import (
    Availability,
    HttpFetcher,
    RateLimitSpec,
    RawJob,
    SearchContext,
    SourceError,
    register_connector,
)
from app.sources.common import ConnectorBase, page_availability
from app.sources.text import html_to_text, parse_date, parse_iso

UNKNOWN_EMPLOYER = "Unknown employer"
MAX_TEXT_CHARS = 60_000


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._in_ld = False
        self.ld: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self.ld.append("")
        elif tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta.setdefault(key.lower(), a["content"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_ld and self.ld:
            self.ld[-1] += data


def _find_job_posting(node: Any) -> dict[str, Any] | None:
    if isinstance(node, list):
        for item in node:
            found = _find_job_posting(item)
            if found:
                return found
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            return node
        for value in node.values():
            if isinstance(value, (dict, list)):
                found = _find_job_posting(value)
                if found:
                    return found
    return None


def _ld_location(posting: Mapping[str, Any]) -> str | None:
    loc = posting.get("jobLocation")
    loc = loc[0] if isinstance(loc, list) and loc else loc
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
            parts = [p.get("name") if isinstance(p, dict) else p for p in parts]
            return ", ".join(str(p) for p in parts if p) or None
    return None


def _ld_pay(posting: Mapping[str, Any]) -> str | None:
    salary = posting.get("baseSalary")
    if not isinstance(salary, dict):
        return None
    value = salary.get("value")
    if not isinstance(value, dict):
        return None
    low, high = value.get("minValue"), value.get("maxValue") or value.get("value")
    if low is None and high is None:
        return None
    if low is not None and high is not None and low != high:
        span = f"{low} - {high}"
    else:
        span = str(low if low is not None else high)
    return f"{salary.get('currency', '')} {span} per {str(value.get('unitText', 'year')).lower()}".strip()


def job_postings(body: str) -> list[dict[str, Any]]:
    """Every JSON-LD ``JobPosting`` object in a page (a listing page may carry many)."""
    head = _Head()
    head.feed(body)
    head.close()
    found: list[dict[str, Any]] = []
    for blob in head.ld:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        found.extend(_all_postings(data))
    return found


def _all_postings(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [p for item in node for p in _all_postings(item)]
    if not isinstance(node, dict):
        return []
    kind = node.get("@type")
    if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
        return [node]
    return [p for value in node.values() if isinstance(value, (dict, list)) for p in _all_postings(value)]


def posting_to_raw(url: str, posting: Mapping[str, Any], *, fallback_text: str = "", fallback_title: str = "",
                   employer: str | None = None) -> RawJob:
    """A JSON-LD ``JobPosting`` as a ``RawJob``; only what the posting states is filled."""
    org = posting.get("hiringOrganization")
    stated = org.get("name") if isinstance(org, dict) else org
    description = html_to_text(str(posting.get("description") or "")) or fallback_text
    identifier = posting.get("identifier")
    req = identifier.get("value") if isinstance(identifier, dict) else identifier
    valid = posting.get("validThrough")
    return RawJob(
        source_url=url, title=str(posting.get("title") or fallback_title).strip(),
        employer=str(stated or employer or UNKNOWN_EMPLOYER).strip(), raw_text=description[:MAX_TEXT_CHARS],
        apply_url=url, location_raw=_ld_location(posting), posted_at=parse_iso(posting.get("datePosted")),
        deadline=parse_date(valid) if isinstance(valid, str) else None,
        requisition_id=str(req) if req else None, pay_text=_ld_pay(posting),
        remote_hint="remote" if posting.get("jobLocationType") == "TELECOMMUTE" else None,
        extra={"structured_data": True})


def parse_page(url: str, body: str) -> RawJob:
    head = _Head()
    head.feed(body)
    head.close()
    posting: dict[str, Any] | None = None
    for blob in head.ld:
        try:
            posting = _find_job_posting(json.loads(blob))
        except ValueError:
            continue
        if posting:
            break
    text = html_to_text(body)[:MAX_TEXT_CHARS]
    if posting:
        return posting_to_raw(url, posting, fallback_text=text, fallback_title=head.title)
    title = (head.meta.get("og:title") or head.title or "").strip()
    return RawJob(source_url=url, title=re.sub(r"\s+", " ", title) or url, employer=head.meta.get("og:site_name")
                  or UNKNOWN_EMPLOYER, raw_text=text, apply_url=url, extra={"structured_data": False})


async def fetch_page(fetcher: HttpFetcher, url: str) -> RawJob:
    status, body = await fetcher.get(url)
    if status != 200:
        raise SourceError(f"page returned HTTP {status}")
    return parse_page(url, body)


@register_connector
class ManualConnector(ConnectorBase):
    """Pasted links and text. Never searches; ``fetch`` reads one page."""

    connector = "manual"
    access = "html"
    default_rate_limit = RateLimitSpec(requests_per_minute=20, burst=3)
    permitted_actions = frozenset({"fetch", "check_open"})

    async def search(self, ctx: SearchContext, since: Any) -> list[RawJob]:
        return []

    async def fetch(self, url: str) -> RawJob:
        return await fetch_page(self.fetcher, url)

    async def check_open(self, url: str) -> Availability:
        return await page_availability(self.fetcher, url, trust_200=False)
