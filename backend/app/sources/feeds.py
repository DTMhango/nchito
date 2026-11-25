"""Feed connectors: We Work Remotely RSS and generic RSS/Atom."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET  # noqa: S405 - DOCTYPE/ENTITY is refused before parsing
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.sources.base import Availability, RateLimitSpec, RawJob, SearchContext, SourceError, register_connector
from app.sources.common import ConnectorBase, join_text, page_availability
from app.sources.page import fetch_page
from app.sources.text import html_to_text, parse_iso, parse_rfc2822

FEED_ACTIONS = frozenset({"search", "fetch", "check_open"})
FEED_RATE = RateLimitSpec(requests_per_minute=6, burst=2)
MAX_ITEMS = 500


@dataclass
class FeedItem:
    title: str
    link: str
    description_html: str
    published: datetime | None
    guid: str
    author: str | None
    fields: dict[str, str]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(body: str) -> tuple[str, list[FeedItem]]:
    """Return ``(feed title, items)`` for RSS 2.0 or Atom. Raises ``SourceError`` when unreadable."""
    head = body[:4096].lower()
    if "<!doctype" in head or "<!entity" in head:
        raise SourceError("feed refused: it declares a DOCTYPE or entities")
    try:
        root = ET.fromstring(body.encode("utf-8"))  # noqa: S314 - DOCTYPE refused above
    except ET.ParseError as exc:
        raise SourceError("feed is not valid XML") from exc
    nodes = [n for n in root.iter() if _local(n.tag) in ("item", "entry")]
    title_node = next((n for n in root.iter() if _local(n.tag) == "title"), None)
    feed_title = (title_node.text or "").strip() if title_node is not None else ""
    items: list[FeedItem] = []
    for node in nodes[:MAX_ITEMS]:
        fields: dict[str, str] = {}
        link = ""
        for child in node:
            name = _local(child.tag)
            if name == "link":
                link = child.get("href") or (child.text or "").strip() or link
            elif child.text and name not in fields:
                fields[name] = child.text.strip()
        date_text = fields.get("pubDate") or fields.get("published") or fields.get("updated") or fields.get("date")
        published = parse_rfc2822(date_text) or parse_iso(date_text)
        items.append(FeedItem(
            title=fields.get("title", ""), link=link or fields.get("guid", ""),
            description_html=fields.get("description") or fields.get("content") or fields.get("summary", ""),
            published=published, guid=fields.get("guid") or fields.get("id") or link,
            author=fields.get("creator") or fields.get("author"), fields=fields))
    return feed_title, items


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _feed_urls(config: Mapping[str, Any], key: str) -> list[str]:
    urls = config.get(key)
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list) or not urls:
        raise ValueError(f"{key} must name at least one feed URL")
    for u in urls:
        parts = urlsplit(str(u))
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("feed URLs must start with http:// or https://")
    return [str(u) for u in urls]


class _FeedConnector(ConnectorBase):
    access = "feed"
    default_rate_limit = FEED_RATE
    permitted_actions = FEED_ACTIONS
    trust_200 = False

    def _to_raw(self, item: FeedItem, feed_title: str, config: Mapping[str, Any]) -> RawJob:
        raise NotImplementedError

    def _feeds(self, config: Mapping[str, Any]) -> list[str]:
        raise NotImplementedError

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        self.warnings = []
        feeds = self._feeds(ctx.source_config)
        found: list[RawJob] = []
        failures = 0
        for url in feeds:
            try:
                status, body = await self.fetcher.get(url)
                if status != 200:
                    raise SourceError(f"HTTP {status}")
                title, items = parse_feed(body)
            except SourceError as exc:
                failures += 1
                self.warnings.append(f"{url}: {exc}")
                continue
            for item in items:
                if item.title and item.link and (since is None or item.published is None or item.published >= since):
                    found.append(self._to_raw(item, title, ctx.source_config))
        if failures == len(feeds):
            raise SourceError("; ".join(self.warnings))
        return found

    async def fetch(self, url: str) -> RawJob:
        return await fetch_page(self.fetcher, url)

    async def check_open(self, url: str) -> Availability:
        return await page_availability(self.fetcher, url, trust_200=self.trust_200)


WWR_DEFAULT_FEED = "https://weworkremotely.com/remote-jobs.rss"


@register_connector
class WeWorkRemotelyConnector(_FeedConnector):
    connector = "weworkremotely"
    trust_200 = True  # server-rendered pages

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(config)
        out["feeds"] = _feed_urls({"feeds": config.get("feeds") or [WWR_DEFAULT_FEED]}, "feeds")
        return out

    def _feeds(self, config: Mapping[str, Any]) -> list[str]:
        return self.validate_config(config)["feeds"]

    def _to_raw(self, item: FeedItem, feed_title: str, config: Mapping[str, Any]) -> RawJob:
        employer, _, title = item.title.partition(": ")
        if not title:
            employer, title = "", item.title
        region = item.fields.get("region", "")
        place = ", ".join(x for x in (item.fields.get("state"), item.fields.get("country")) if x)
        text = html_to_text(item.description_html)
        return RawJob(
            source_url=item.link, title=title.strip(), employer=employer.strip() or "Unknown employer",
            raw_text=join_text(title, text), apply_url=item.link,
            location_raw=place or region or None, posted_at=item.published,
            remote_hint=f"remote; region: {region}" if region else "remote",
            extra={"listing_open": True, "category": item.fields.get("category"), "type": item.fields.get("type"),
                   "region": region or None, "expires_at": item.fields.get("expires_at"), "guid": item.guid})


@register_connector
class RssConnector(_FeedConnector):
    connector = "rss"

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(config)
        out["feed_urls"] = _feed_urls(config, "feed_urls") if config.get("feed_urls") else \
            _feed_urls({"feed_urls": config.get("feed_url")}, "feed_urls")
        if config.get("employer") is not None:
            out["employer"] = str(config["employer"]).strip() or None
        return out

    def _feeds(self, config: Mapping[str, Any]) -> list[str]:
        return self.validate_config(config)["feed_urls"]

    def _to_raw(self, item: FeedItem, feed_title: str, config: Mapping[str, Any]) -> RawJob:
        employer = config.get("employer") or item.author or feed_title or "Unknown employer"
        text = html_to_text(item.description_html)
        return RawJob(
            source_url=item.link, title=item.title.strip(), employer=employer.strip(),
            raw_text=join_text(item.title, text), apply_url=item.link, posted_at=item.published,
            extra={"feed": feed_title, "guid": item.guid or _fingerprint(item.title, item.link)})
