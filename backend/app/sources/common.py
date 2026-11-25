"""Helpers shared by connector implementations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.sources.base import Availability, HttpFetcher, SearchContext, SourceError
from app.sources.http import parse_json
from app.sources.text import html_to_text

MAX_QUERIES = 5
CLOSED_PHRASES = (
    "no longer accepting applications",
    "no longer available",
    "this job has expired",
    "this position has been filled",
    "position is no longer open",
    "job is no longer open",
    "this job is closed",
    "posting has expired",
)


class ConnectorBase:
    """Common plumbing: injected fetcher, per-call warnings, JSON helper."""

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher
        self.warnings: list[str] = []

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        return dict(config)

    async def get_json(self, url: str, what: str) -> Any:
        status, body = await self.fetcher.get(url)
        return parse_json(status, body, what)

    async def exists_status(self, url: str) -> Availability:
        """200 open, 404/410 closed, anything else (blocked, 5xx, timeout) unknown."""
        try:
            status, _ = await self.fetcher.get(url)
        except SourceError:
            return "unknown"
        return status_to_availability(status)


def status_to_availability(status: int) -> Availability:
    if status == 200:
        return "open"
    if status in (404, 410):
        return "closed"
    return "unknown"


def normalise_boards(config: Mapping[str, Any], *, keys: Sequence[str] = ("slug",)) -> list[dict[str, str]]:
    """``boards`` may hold bare slugs or ``{slug, name}`` objects. Returns ``[{slug, name?}]``.

    Raises ``ValueError`` when there are none: a board connector without boards searches nothing.
    """
    raw = config.get("boards")
    if not isinstance(raw, list) or not raw:
        raise ValueError("boards must be a non-empty list of board slugs")
    boards: list[dict[str, str]] = []
    for item in raw:
        entry = {"slug": item.strip()} if isinstance(item, str) else {k: str(v).strip() for k, v in dict(item).items()}
        if any(not entry.get(k) for k in keys):
            raise ValueError(f"every board needs {', '.join(keys)}")
        boards.append(entry)
    return boards


def board_name(entry: Mapping[str, str]) -> str:
    return entry.get("name") or entry["slug"].replace("-", " ").replace("_", " ").title()


def queries_for(ctx: SearchContext, config: Mapping[str, Any]) -> list[str]:
    """Search phrases for keyword APIs: explicit config, else campaign titles then keywords."""
    explicit = config.get("queries")
    if isinstance(explicit, list) and explicit:
        return [str(q) for q in explicit][:MAX_QUERIES]
    seen: list[str] = []
    for phrase in [*ctx.titles, *ctx.keywords]:
        phrase = phrase.strip()
        if phrase and phrase.lower() not in {s.lower() for s in seen}:
            seen.append(phrase)
    return seen[:MAX_QUERIES]


def join_text(*parts: str | None) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def closed_by_page(text_html: str) -> bool:
    lowered = re.sub(r"\s+", " ", html_to_text(text_html)).lower()
    return any(phrase in lowered for phrase in CLOSED_PHRASES)


async def page_availability(fetcher: HttpFetcher, url: str, *, trust_200: bool) -> Availability:
    """Availability of a server-rendered posting page.

    404/410 closed; a 200 page saying the role is gone closed; a plain 200 is ``open`` only for
    sources whose pages are known to be server-rendered (``trust_200``), else unknown.
    """
    try:
        status, body = await fetcher.get(url)
    except SourceError:
        return "unknown"
    if status in (404, 410):
        return "closed"
    if status != 200:
        return "unknown"
    if closed_by_page(body):
        return "closed"
    return "open" if trust_200 else "unknown"
