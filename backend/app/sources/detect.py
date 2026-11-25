"""Board detector: a pasted careers URL becomes a board type and slug.

``detect_from_url`` is pure. ``detect`` also reads a custom careers page once, looking for an
embedded Greenhouse, Lever, Ashby, Workable or Workday board, with lower confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.sources.base import HttpFetcher, SourceError
from app.sources.text import host_of, path_parts

_LOCALE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2})?$")
_NOT_SLUG = {"embed", "v1", "boards", "jobs", "j", "api", "careers", "en-us"}


@dataclass(frozen=True)
class Detected:
    connector: str | None
    board_slug: str | None
    employer_name: str | None
    confidence: float


NOT_DETECTED = Detected(None, None, None, 0.0)


def guess_name(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


def _hit(connector: str, slug: str | None, confidence: float = 0.95, name: str | None = None) -> Detected:
    if not slug or slug.lower() in _NOT_SLUG:
        return NOT_DETECTED
    return Detected(connector, slug, name or guess_name(slug), confidence)


def detect_from_url(url: str) -> Detected:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    path = path_parts(url)
    query = parse_qs(parts.query)
    if parts.scheme not in ("http", "https") or not host:
        return NOT_DETECTED

    if host.endswith("greenhouse.io"):
        if host == "boards-api.greenhouse.io" and len(path) >= 3 and path[:2] == ["v1", "boards"]:
            return _hit("greenhouse", path[2])
        if path[:1] == ["embed"]:
            return _hit("greenhouse", (query.get("for") or [None])[0])
        return _hit("greenhouse", path[0] if path else None)
    if host.endswith("lever.co") and host.startswith("jobs"):
        return _hit("lever", path[0] if path else None)
    if host == "jobs.ashbyhq.com":
        return _hit("ashby", path[0] if path else None)
    if host == "apply.workable.com":
        return _hit("workable", path[0] if path else None)
    if host.endswith(".myworkdayjobs.com"):
        site = next((p for p in path if not _LOCALE.match(p)), None)
        if not site or site in ("job", "wday"):
            return NOT_DETECTED
        tenant = host.split(".")[0]
        return Detected("workday", f"{host}/{tenant}/{site}", guess_name(tenant), 0.95)
    if path and re.search(r"\.(rss|xml|atom)$", path[-1]) or "rss" in host:
        return Detected("rss", url.strip(), None, 0.6)
    return NOT_DETECTED


_EMBEDDED = (
    (re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?(?P<s>[\w-]+)", re.I),
     "greenhouse"),
    (re.compile(r"jobs(?:\.eu)?\.lever\.co/(?P<s>[\w-]+)", re.I), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com/(?P<s>[\w.%-]+)", re.I), "ashby"),
    (re.compile(r"apply\.workable\.com/(?P<s>[\w-]+)", re.I), "workable"),
    (re.compile(r"(?P<s>[\w-]+\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[\w-]+)", re.I), "workday"),
)


def detect_in_page(body: str) -> Detected:
    for pattern, connector in _EMBEDDED:
        m = pattern.search(body)
        if not m:
            continue
        slug = m["s"]
        if connector == "workday":
            found = detect_from_url("https://" + slug)
            if found.connector:
                return Detected(found.connector, found.board_slug, found.employer_name, 0.7)
            continue
        hit = _hit(connector, slug, 0.7)
        if hit.connector:
            return hit
    return NOT_DETECTED


async def detect(fetcher: HttpFetcher, url: str) -> Detected:
    found = detect_from_url(url)
    if found.connector:
        return found
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not host_of(url):
        return NOT_DETECTED
    try:
        status, body = await fetcher.get(url)
    except SourceError:
        return NOT_DETECTED
    return detect_in_page(body) if status == 200 else NOT_DETECTED
