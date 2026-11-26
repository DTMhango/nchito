"""Deterministic date and time extraction from invitation wording. DESIGN.md 12.

Reads text only (regular expressions, no evaluation, bounded input). It finds *candidates*: a calendar date, a
clock time and, when the text says so, a time zone. It never guesses a zone and never picks between several
dates; the caller turns what it finds into a proposal the owner settles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

TEXT_LIMIT = 20_000
MAX_CANDIDATES = 6
LOOKAHEAD_CHARS = 60

MONTHS = {name: i for i, names in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
     ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"),
     ("november", "nov"), ("december", "dec")], start=1) for name in names}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+"

# Zone abbreviations that mean one thing. CST, IST, BST-as-Bangladesh and the like are ambiguous: not listed.
ZONE_ABBREVIATIONS: dict[str, str] = {
    "UTC": "UTC", "GMT": "Etc/GMT", "CAT": "Africa/Lusaka", "SAST": "Africa/Johannesburg", "EAT": "Africa/Nairobi",
    "WAT": "Africa/Lagos", "BST": "Europe/London", "CET": "Europe/Paris", "CEST": "Europe/Paris",
    "EET": "Europe/Athens", "EEST": "Europe/Athens", "EST": "America/New_York", "EDT": "America/New_York",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "MST": "America/Denver", "MDT": "America/Denver",
}

_TIME = (r"(?P<h>\d{1,2})(?:[:.h](?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)?")
_TIME_RANGE = re.compile(
    rf"(?:at|from|@|,|-|\s)*{_TIME}(?:\s*(?:to|-|\u2013|until)\s*(?P<h2>\d{{1,2}})(?:[:.h](?P<m2>\d{{2}}))?"
    rf"\s*(?P<ap2>a\.?m\.?|p\.?m\.?)?)?", re.I)
_ZONE = re.compile(
    r"\(?\b(?P<name>[A-Za-z]+/[A-Za-z_]+(?:/[A-Za-z_]+)?|(?:UTC|GMT)\s?[+-]\s?\d{1,2}(?::?00)?|"
    + "|".join(sorted(ZONE_ABBREVIATIONS, key=len, reverse=True)) + r")\b\)?")

_DATE_ISO = re.compile(r"\b(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})\b")
_DATE_DMY = re.compile(
    rf"\b(?:{_WEEKDAY})?(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_RX})\b\.?(?:,?\s+(?P<y>\d{{4}}))?",
    re.I)
_DATE_MDY = re.compile(
    rf"\b(?:{_WEEKDAY})?(?P<mon>{_MONTH_RX})\b\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>\d{{4}}))?",
    re.I)


@dataclass(frozen=True)
class TextCandidate:
    """A wall time as the text gives it. ``zone`` is an IANA name, or ``None`` when the text names none."""

    start: datetime  # naive wall time
    end: datetime | None
    zone: str | None


def _zone_name(raw: str) -> str | None:
    text = raw.strip()
    if "/" in text:
        return text
    upper = text.upper().replace(" ", "")
    if upper in ZONE_ABBREVIATIONS:
        return ZONE_ABBREVIATIONS[upper]
    found = re.fullmatch(r"(UTC|GMT)([+-])(\d{1,2})(?::?00)?", upper)
    if found:
        hours = int(found.group(3))
        if hours > 14:
            return None
        if hours == 0:
            return "UTC"
        # Etc/GMT zones carry the opposite sign: UTC+2 is Etc/GMT-2.
        return f"Etc/GMT{'-' if found.group(2) == '+' else '+'}{hours}"
    return None


def _clock(h: str, m: str | None, ap: str | None, *, need_marker: bool = True) -> time | None:
    hour, minute = int(h), int(m or 0)
    if need_marker and m is None and not ap:
        return None  # a bare number is not a time ("3 December")
    marker = (ap or "").lower().replace(".", "")
    if marker:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if marker == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _dates(text: str, today: date) -> list[tuple[int, int, date]]:
    """(start, end, date) for every date written in ``text``; a missing year is the next occurrence."""
    found: list[tuple[int, int, date]] = []
    taken: list[tuple[int, int]] = []

    def add(match: re.Match[str], year: int | None, month: int, day: int) -> None:
        if any(s < match.end() and match.start() < e for s, e in taken):
            return
        try:
            when = date(year if year else today.year, month, day)
        except ValueError:
            return
        if year is None and when < today - timedelta(days=1):
            try:
                when = date(today.year + 1, month, day)
            except ValueError:
                return
        taken.append((match.start(), match.end()))
        found.append((match.start(), match.end(), when))

    for m in _DATE_ISO.finditer(text):
        add(m, int(m["y"]), int(m["mo"]), int(m["d"]))
    for rx in (_DATE_DMY, _DATE_MDY):
        for m in rx.finditer(text):
            add(m, int(m["y"]) if m["y"] else None, MONTHS[m["mon"].lower()], int(m["d"]))
    return sorted(found)


def extract_candidates(text: str, *, today: date) -> list[TextCandidate]:
    """Dated, timed candidates in ``text`` (at most ``MAX_CANDIDATES``, distinct). A date with no clock time
    nearby is not a candidate: an interview slot needs a time."""
    body = text[:TEXT_LIMIT]
    out: list[TextCandidate] = []
    seen: set[tuple[datetime, str | None]] = set()
    for _, end_pos, when in _dates(body, today):
        window = body[end_pos:end_pos + LOOKAHEAD_CHARS]
        tm = _TIME_RANGE.match(window)
        start_t = _clock(tm["h"], tm["m"], tm["ap"]) if tm else None
        if tm is None or start_t is None:
            continue
        end_dt: datetime | None = None
        if tm["h2"] is not None:
            end_t = _clock(tm["h2"], tm["m2"], tm["ap2"] or tm["ap"], need_marker=False)
            if end_t is not None and end_t > start_t:
                end_dt = datetime.combine(when, end_t)
        zone_match = _ZONE.match(window[tm.end():].lstrip(" ,"))
        zone = _zone_name(zone_match["name"]) if zone_match else None
        start_dt = datetime.combine(when, start_t)
        key = (start_dt, zone)
        if key in seen:
            continue
        seen.add(key)
        out.append(TextCandidate(start=start_dt, end=end_dt, zone=zone))
        if len(out) >= MAX_CANDIDATES:
            break
    return out
