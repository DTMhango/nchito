"""Connector registry: imports every connector module (which registers it) and builds instances.

``effective_config`` merges the watched-employer list into a board connector's config, so the
sweep is driven by the owner's list as well as by any boards typed into the source itself.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any

from app.models.search import Source, WatchedEmployer
from app.schemas.json_types import RateLimit
from app.sources import (  # noqa: F401  (registration)
    alert_email,
    ats,
    careers_page,
    feeds,
    jobspy,
    page,
    remote,
    web_search,
    workday,
)
from app.sources.base import HttpFetcher, RateLimitSpec, SourceConnector, connector_class, registered_connectors
from app.sources.http import HttpxFetcher, polite
from app.sources.workday import parse_board

BOARD_TYPES = ("greenhouse", "lever", "ashby", "workable", "workday")


def effective_config(source: Source, watched: Sequence[WatchedEmployer]) -> dict[str, Any]:
    config = dict(source.config or {})
    if source.connector not in BOARD_TYPES:
        return config
    boards = list(config.get("boards") or [])
    known = {_slug_of(b) for b in boards}
    for w in sorted(watched, key=lambda w: -w.priority):
        if w.board_type == source.connector and w.board_slug not in known:
            boards.append(parse_board(w.board_slug) | {"name": w.name} if w.board_type == "workday"
                          else {"slug": w.board_slug, "name": w.name})
            known.add(w.board_slug)
    config["boards"] = boards
    return config


def _slug_of(board: Any) -> str:
    if isinstance(board, str):
        return board
    if "slug" in board:
        return str(board["slug"])
    return f"{board.get('host')}/{board.get('tenant')}/{board.get('site')}"


def spec_of(rate: RateLimit) -> RateLimitSpec:
    return RateLimitSpec(requests_per_minute=rate.requests_per_minute, burst=rate.burst)


def build_connector(source: Source, transport: HttpFetcher | None = None, *,
                    extras: Mapping[str, Any] | None = None) -> SourceConnector:
    """A connector for ``source`` whose requests honour the source's own rate limit. ``extras`` holds what some
    connectors take besides the fetcher (``api_key``, ``llm``, live ``settings``); each connector is given only
    the ones its constructor accepts."""
    cls = connector_class(source.connector)
    inner = transport or HttpxFetcher()
    accepted = inspect.signature(cls.__init__).parameters
    kwargs = {k: v for k, v in (extras or {}).items() if k in accepted and v is not None}
    return cls(polite(inner, spec_of(source.rate_limit)), **kwargs)  # type: ignore[call-arg]


def known_connectors() -> list[str]:
    return registered_connectors()
