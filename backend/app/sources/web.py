"""Shared plumbing for the connectors that read arbitrary web pages (careers page, web search, JobSpy).

- ``RobotsGuard``: robots.txt is an invariant here, not a setting. Every page outside a known ATS
  API is checked first; an unreadable robots.txt (5xx, timeout) means "do not read".
- ``canonical_url``: one spelling of a posting URL so the same posting from two sources merges.
- ``knob``: a numeric or list knob from the source's own config, else injected settings, else the
  registry default (the one place defaults live).
- Link, sitemap and ATS-delegation helpers. Everything read here is untrusted data.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from app.core.settings.registry import get_def
from app.sources.base import HttpFetcher, RawJob, SearchContext, SourceError, connector_class
from app.sources.detect import Detected
from app.sources.text import parse_iso
from app.sources.workday import parse_board

ROBOTS_AGENT = "NchitoJobReader"  # the product token inside http.USER_AGENT
_TRACKING = re.compile(r"^(utm_|gclid$|fbclid$|mc_|ref$|source$|src$|trk|gh_src$|lever-source)", re.I)
JOB_PATH = re.compile(r"/(jobs?|careers?|vacanc(?:y|ies)|openings?|positions?|opportunit(?:y|ies)|"
                      r"requisitions?|postings?|roles?)/[^/?#]+", re.I)
_NOT_POSTING_TAIL = re.compile(r"\.(pdf|docx?|jpe?g|png|gif|svg|css|js|zip)$|/(search|apply|login|alerts?|"
                               r"saved|category|categories|teams?|locations?)/?$", re.I)
MAX_ANCHORS = 2000
MAX_SITEMAP_CHILDREN = 3


def knob(key: str, config: Mapping[str, Any], settings: Mapping[str, Any] | None = None) -> Any:
    """``sources.<group>.<name>``: source config ``<name>`` wins, then ``settings[key]``, then the default."""
    name = key.rsplit(".", 1)[-1]
    definition = get_def(key)
    if name in config and config[name] is not None:
        return definition.coerce(config[name])
    if settings is not None and key in settings:
        return definition.coerce(settings[key])
    return definition.effective_default()


def canonical_url(url: str) -> str:
    """Lower-case host, no fragment, no tracking parameters, no trailing slash: one spelling per posting."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def http_url(value: Any) -> str:
    parts = urlsplit(str(value).strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{value!r} is not an http(s) URL")
    return str(value).strip()


def same_site(a: str, b: str) -> bool:
    ha, hb = (urlsplit(a).hostname or "").lower(), (urlsplit(b).hostname or "").lower()
    return bool(ha) and ha.removeprefix("www.") == hb.removeprefix("www.")


class RobotsGuard:
    """robots.txt per origin, read once through the injected (rate-limited) fetcher."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher
        self._rules: dict[str, RobotFileParser | None] = {}  # None: unreadable, read nothing

    async def _load(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._rules:
            return self._rules[origin]
        parser: RobotFileParser | None = RobotFileParser()
        try:
            status, body = await self._fetcher.get(f"{origin}/robots.txt")
        except SourceError:
            parser = None
        else:
            if status == 200:
                assert parser is not None
                parser.parse(body.splitlines())
            elif 400 <= status < 500:
                assert parser is not None
                parser.parse([])  # RFC 9309: no robots.txt means everything is allowed
            else:
                parser = None
        self._rules[origin] = parser
        return parser

    async def allowed(self, url: str) -> bool:
        parser = await self._load(url)
        return parser is not None and parser.can_fetch(ROBOTS_AGENT, url)

    async def sitemaps(self, url: str) -> list[str]:
        parser = await self._load(url)
        listed = (parser.site_maps() if parser is not None else None) or []
        parts = urlsplit(url)
        return listed or [f"{parts.scheme}://{parts.netloc}/sitemap.xml"]


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or None
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None and len(self.links) < MAX_ANCHORS:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._text)).strip()))
            self._href = None


def looks_like_posting_url(url: str) -> bool:
    path = urlsplit(url).path
    return bool(JOB_PATH.search(path)) and not _NOT_POSTING_TAIL.search(path)


def listing_links(base_url: str, body: str) -> list[tuple[str, str]]:
    """``(absolute canonical url, anchor text)`` of links on the same site that look like one posting."""
    parser = _Anchors()
    parser.feed(body)
    parser.close()
    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    base = canonical_url(base_url)
    for href, text in parser.links:
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = canonical_url(urljoin(base_url, href))
        if url in seen or url == base or not same_site(url, base_url) or not looks_like_posting_url(url):
            continue
        seen.add(url)
        found.append((url, text))
    return found


def sitemap_entries(body: str) -> tuple[list[str], list[tuple[str, datetime | None]]]:
    """``(child sitemaps, [(url, lastmod)])`` of a sitemap or sitemap index. Unreadable XML gives nothing."""
    if "<!doctype" in body[:4096].lower() or "<!entity" in body[:4096].lower():
        return [], []
    try:
        root = ET.fromstring(body.encode("utf-8"))  # noqa: S314 - DOCTYPE refused above
    except ET.ParseError:
        return [], []

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    children: list[str] = []
    urls: list[tuple[str, datetime | None]] = []
    for node in root:
        fields = {local(c.tag): (c.text or "").strip() for c in node}
        loc = fields.get("loc")
        if not loc:
            continue
        if local(node.tag) == "sitemap":
            children.append(loc)
        elif local(node.tag) == "url":
            urls.append((loc, parse_iso(fields.get("lastmod"))))
    return children, urls


def ats_target(found: Detected) -> tuple[str, dict[str, str]]:
    """``(connector name, board entry)`` for a detected ATS board."""
    assert found.connector and found.board_slug
    if found.connector == "workday":
        return "workday", parse_board(found.board_slug) | {"name": found.employer_name or ""}
    return found.connector, {"slug": found.board_slug, "name": found.employer_name or found.board_slug}


async def ats_search(fetcher: HttpFetcher, found: Detected, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
    """Search one detected board through the existing ATS connector (same RawJob, same dedupe keys)."""
    name, board = ats_target(found)
    sub = SearchContext(campaign_id=ctx.campaign_id, titles=ctx.titles, keywords=ctx.keywords,
                        locations=ctx.locations, source_config={"boards": [board]})
    connector = connector_class(name)(fetcher)  # type: ignore[call-arg]
    return await connector.search(sub, since)
