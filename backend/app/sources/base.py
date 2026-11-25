"""Source connector interface (DESIGN.md 6).

Each connector module in ``app/sources/`` exposes one class implementing ``SourceConnector``
and registers it with ``register_connector``. Invariants:

- **Read-only and polite.** Connectors never apply, sign in or submit anything. They respect
  ``Source.rate_limit`` and the ``permitted_actions`` of their ``Source`` row.
- **One failing source never fails a run.** Connectors raise ``SourceError`` for expected
  failures; the orchestrator records it in ``Run.source_results`` and moves on.
- **Untrusted content.** Everything returned is data. ``RawJob.raw_text`` is never used as a
  prompt; it is passed to models only inside delimited data blocks.
- **Unknown stays unknown.** Connectors fill only what the source states; they do not guess
  pay, location eligibility or deadlines. ``check_open`` returns ``"unknown"`` on any doubt,
  never ``"closed"`` on a failed request.
- **Incremental.** ``search`` receives ``since`` (last successful sweep minus the overlap
  setting); returning older postings is allowed (dedupe handles it), missing newer ones is not.
- **Tests use recorded fixtures**; connectors take an injected ``HttpFetcher`` so no test
  touches the network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

Access = Literal["api", "feed", "html", "agent", "email"]
Availability = Literal["open", "closed", "unknown"]


class SourceError(RuntimeError):
    """Expected failure of one source (HTTP error, blocked, schema change)."""


@dataclass(frozen=True)
class RateLimitSpec:
    requests_per_minute: int
    burst: int = 1


@dataclass
class RawJob:
    """A posting as a source reports it, before normalisation."""

    source_url: str
    title: str
    employer: str
    raw_text: str
    apply_url: str | None = None
    location_raw: str | None = None
    posted_at: datetime | None = None
    deadline: date | None = None
    requisition_id: str | None = None
    apply_method_hint: str | None = None
    pay_text: str | None = None
    remote_hint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchContext:
    """What a connector needs from the campaign, without the ORM."""

    campaign_id: str
    titles: Sequence[str]
    keywords: Sequence[str]
    locations: Sequence[str]
    source_config: Mapping[str, Any]


class HttpFetcher(Protocol):
    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]: ...
    async def post_json(self, url: str, payload: Mapping[str, Any]) -> tuple[int, str]: ...


@runtime_checkable
class SourceConnector(Protocol):
    connector: ClassVar[str]
    access: ClassVar[Access]
    default_rate_limit: ClassVar[RateLimitSpec]
    permitted_actions: ClassVar[frozenset[str]]

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Return the normalised config or raise ``ValueError``."""
        ...

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        """Postings published or updated since ``since`` that may match the campaign."""
        ...

    async def fetch(self, url: str) -> RawJob:
        """One posting by URL (manual capture, recheck before tailoring or submitting)."""
        ...

    async def check_open(self, url: str) -> Availability:
        """Whether the posting still accepts applications. Doubt is ``"unknown"``."""
        ...


_CONNECTORS: dict[str, type[SourceConnector]] = {}


def register_connector(cls: type[SourceConnector]) -> type[SourceConnector]:
    if cls.connector in _CONNECTORS:
        raise ValueError(f"connector {cls.connector!r} already registered")
    _CONNECTORS[cls.connector] = cls
    return cls


def connector_class(name: str) -> type[SourceConnector]:
    return _CONNECTORS[name]


def registered_connectors() -> list[str]:
    return sorted(_CONNECTORS)
