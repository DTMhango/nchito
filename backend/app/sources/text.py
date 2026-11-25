"""Small text helpers shared by connectors: HTML to plain text, dates, URL parts."""

from __future__ import annotations

import html
import re
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}
_SKIP = {"script", "style", "noscript", "head", "svg"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    """Plain text from HTML (also from HTML that was entity-escaped once, as Greenhouse sends it)."""
    if not value:
        return ""
    if "&lt;" in value and "<" not in value:
        value = html.unescape(value)
    parser = _Text()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_rfc2822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def from_epoch(value: object, *, millis: bool = False) -> datetime | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number / 1000 if millis else number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def parse_date(value: str | None) -> date | None:
    parsed = parse_iso(value)
    return parsed.date() if parsed else None


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def path_parts(url: str) -> list[str]:
    return [p for p in urlsplit(url).path.split("/") if p]
