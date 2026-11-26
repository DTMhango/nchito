"""Job-alert emails as a source (DESIGN.md 6: LinkedIn, Indeed and Glassdoor alerts from the mailbox).

The connector reads the connected mailbox (through the same narrow label/query as everything else),
keeps only messages from the configured senders and turns each job card into a ``RawJob``. Links are
data: they are never opened here, only recorded (``source_url`` / ``apply_url``), with tracking
parameters removed. Only what the card states is filled in; the rest stays unknown. The email text
never reaches a model from here: ``raw_text`` is the card (title, employer, place) and goes onward
as untrusted data like any other posting.

Config: ``{"connection_id": "<mail connection uuid>", "senders": ["jobalerts@example.com", "example.org"]}``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.connect import mail_connections
from app.connect.mail_common import sender_matches
from app.connect.mailbox import Mailbox, MailError, MailMessage
from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.platform import Connection
from app.sources.base import (
    Availability,
    HttpFetcher,
    RateLimitSpec,
    RawJob,
    SearchContext,
    SourceError,
    register_connector,
)
from app.sources.common import ConnectorBase
from app.sources.page import fetch_page

UNKNOWN_EMPLOYER = "Unknown employer"
JOB_PATH_HINTS = ("/jobs/view", "/comm/jobs/view", "/viewjob", "/rc/clk", "/pagead/clk", "/job-listing",
                  "/partner/jobview", "/job/", "/jobs/")
GENERIC_LABELS = frozenset({"apply", "apply now", "view job", "view", "see more", "see more jobs", "view all",
                            "unsubscribe", "view jobs", "easy apply", "manage alerts", "edit alert"})
DROP_PARAMS = re.compile(r"^(utm_.*|trk.*|tracking.*|ref|refid|eid|midtoken|midsig|trkemail|lipi|ct|cb)$", re.I)
SEPARATORS = (" · ", " - ", " | ", " – ", " — ")  # noqa: RUF001
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
MAX_CARDS_PER_MESSAGE = 100


@dataclass(frozen=True)
class MailAccess:
    mailbox: Mailbox
    lookback_days: int
    limit: int


MailAccessResolver = Callable[[uuid.UUID], Awaitable[MailAccess]]


async def default_access(connection_id: uuid.UUID) -> MailAccess:
    async with get_sessionmaker()() as s:
        conn = await s.get(Connection, connection_id)
        if conn is None or not conn.enabled or not mail_connections.is_mail(conn.provider.value):
            raise SourceError("the mailbox connection for this alert source is missing or disabled")
        values = await settings_service.values(s)
        try:
            mailbox = mail_connections.build_mailbox(conn)
        except MailError as exc:
            raise SourceError(str(exc)) from exc
    return MailAccess(mailbox, int(values["mail.initial_lookback_days"]), int(values["mail.max_messages_per_check"]))


def clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not DROP_PARAMS.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def is_job_link(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    path = parts.path.lower()
    return any(path.startswith(h) or h in path for h in JOB_PATH_HINTS) and path.rstrip("/") not in ("/jobs", "/job")


@dataclass
class Card:
    url: str
    title: str
    employer: str
    location: str | None


class _Tokens(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str, str]] = []  # ("a", href, text) or ("t", "", text)
        self._href: str | None = None
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._buf = []
        elif tag in ("br", "p", "div", "td", "tr", "li", "h1", "h2", "h3") and self._href is None:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href is not None:
            self.tokens.append(("a", self._href, " ".join("".join(self._buf).split())))
            self._href, self._buf = None, []
        elif tag in ("p", "div", "td", "tr", "li") and self._href is None:
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def _flush_text(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.tokens.append(("t", "", text))
        self._buf = []

    def close(self) -> None:
        super().close()
        if self._href is None:
            self._flush_text()


def _split_place(line: str) -> tuple[str, str | None]:
    for sep in SEPARATORS:
        if sep in line:
            left, right = line.split(sep, 1)
            return left.strip(), right.strip() or None
    return line.strip(), None


def cards_from_html(html: str) -> list[Card]:
    parser = _Tokens()
    parser.feed(html)
    parser.close()
    tokens = parser.tokens
    cards: list[Card] = []
    seen: set[str] = set()
    for i, (kind, href, text) in enumerate(tokens):
        if kind != "a" or not is_job_link(href) or len(text) < 3 or text.lower() in GENERIC_LABELS:
            continue
        url = clean_url(href)
        if url in seen:
            continue
        seen.add(url)
        following: list[str] = []
        for k2, h2, t2 in tokens[i + 1:]:
            if k2 == "a" and is_job_link(h2):
                break
            if k2 == "t" and t2.lower() not in GENERIC_LABELS:
                following.append(t2)
            if len(following) == 2:
                break
        employer, place = _split_place(following[0]) if following else ("", None)
        if place is None and len(following) > 1:
            place = following[1]
        cards.append(Card(url, text, employer or UNKNOWN_EMPLOYER, place))
        if len(cards) >= MAX_CARDS_PER_MESSAGE:
            break
    return cards


def cards_from_text(text: str) -> list[Card]:
    lines = [ln.strip() for ln in text.splitlines()]
    cards: list[Card] = []
    seen: set[str] = set()
    for idx, line in enumerate(lines):
        m = URL_RE.search(line) if line.startswith(("http", "<http")) else None
        if m is None:
            continue
        raw = m.group(0)
        if not is_job_link(raw):
            continue
        url = clean_url(raw)
        if url in seen:
            continue
        seen.add(url)
        prev: list[str] = []
        for earlier in reversed(lines[:idx]):  # the card is the lines right above its link, up to a blank line
            if not earlier or URL_RE.search(earlier) or len(prev) == 2:
                break
            prev.append(earlier)
        if not prev:
            continue
        if len(prev) == 2:
            title = prev[1]
            employer, place = _split_place(prev[0])
        else:
            title, employer, place = prev[0], "", None
        cards.append(Card(url, title, employer or UNKNOWN_EMPLOYER, place))
        if len(cards) >= MAX_CARDS_PER_MESSAGE:
            break
    return cards


def jobs_from_message(msg: MailMessage) -> list[RawJob]:
    cards = cards_from_html(msg.body_html) if msg.body_html else []
    if not cards:
        cards = cards_from_text(msg.body_text)
    return [RawJob(
        source_url=c.url, title=c.title, employer=c.employer,
        raw_text="\n".join(x for x in (c.title, "" if c.employer == UNKNOWN_EMPLOYER else c.employer,
                                       c.location or "") if x),
        apply_url=c.url, location_raw=c.location, posted_at=msg.received_at,
        extra={"alert_sender": msg.sender, "alert_message_id": msg.provider_message_id, "link_is_tracking": True})
        for c in cards]


@register_connector
class AlertEmailConnector(ConnectorBase):
    connector = "alert_email"
    access = "email"
    default_rate_limit = RateLimitSpec(requests_per_minute=6, burst=1)
    permitted_actions = frozenset({"search"})

    def __init__(self, fetcher: HttpFetcher, resolver: MailAccessResolver = default_access) -> None:
        super().__init__(fetcher)
        self._resolver = resolver

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(config)
        try:
            out["connection_id"] = str(uuid.UUID(str(config.get("connection_id"))))
        except ValueError as exc:
            raise ValueError("connection_id must be the id of a connected mailbox") from exc
        senders = config.get("senders")
        if isinstance(senders, str):
            senders = [senders]
        if not isinstance(senders, list) or not [s for s in senders if str(s).strip()]:
            raise ValueError("senders must list at least one alert sender address or domain")
        out["senders"] = [str(s).strip().lower() for s in senders if str(s).strip()]
        return out

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        self.warnings = []
        config = self.validate_config(ctx.source_config)
        access = await self._resolver(uuid.UUID(config["connection_id"]))
        start = since or utcnow() - timedelta(days=access.lookback_days)
        try:
            messages = await access.mailbox.list_messages(start, limit=access.limit)
        except MailError as exc:
            raise SourceError(f"mailbox: {exc}") from exc
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for msg in sorted(messages, key=lambda m: m.received_at, reverse=True):
            if not sender_matches(msg.sender, config["senders"]):
                continue
            for job in jobs_from_message(msg):
                if job.source_url not in seen:
                    seen.add(job.source_url)
                    jobs.append(job)
        return jobs

    async def fetch(self, url: str) -> RawJob:
        return await fetch_page(self.fetcher, url)

    async def check_open(self, url: str) -> Availability:
        return "unknown"  # alert links are tracking redirects; doubt is unknown
