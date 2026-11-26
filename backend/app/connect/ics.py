"""iCalendar (RFC 5545) reading and writing for interview events. DESIGN.md 12.

Reading is for attachments of employer mail, which are untrusted data. The parser therefore:
- refuses input over ``MAX_ICS_BYTES`` and stops at ``MAX_LINES`` lines and ``MAX_EVENTS`` events;
- never fetches anything: a URL in the file is text (``meeting_link`` keeps it only as a string, http(s) only);
- never evaluates anything: recurrence rules are noted, not expanded; unknown properties are dropped;
- strips control characters and caps every value;
- resolves a time only when its zone is known (UTC, or a TZID that is an IANA zone or a known Windows name).
  A floating time, or an unknown zone, stays unresolved so the owner decides.

Writing builds feeds and downloads; callers choose what goes in (the detail level), never notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_ICS_BYTES = 256 * 1024
MAX_LINES = 5_000
MAX_EVENTS = 20
MAX_VALUE_CHARS = 4_000
MAX_LINK_CHARS = 2_000

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_LINK = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_UNESCAPE = re.compile(r"\\([nN,;\\])")

# Windows zone names that calendar programs write as TZID, mapped to IANA.
WINDOWS_ZONES: dict[str, str] = {
    "UTC": "UTC", "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Budapest",
    "E. Europe Standard Time": "Europe/Chisinau", "South Africa Standard Time": "Africa/Johannesburg",
    "Central Africa Time": "Africa/Maputo", "E. Africa Standard Time": "Africa/Nairobi",
    "W. Central Africa Standard Time": "Africa/Lagos", "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago", "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles", "India Standard Time": "Asia/Kolkata",
    "Arabian Standard Time": "Asia/Dubai", "Singapore Standard Time": "Asia/Singapore",
    "AUS Eastern Standard Time": "Australia/Sydney", "Greenwich Standard Time": "Atlantic/Reykjavik",
}


class IcsError(ValueError):
    """The file is too big or not a calendar. The message never contains file content."""


@dataclass(frozen=True)
class RawTime:
    """A time as written: ``local`` is naive wall time (or the UTC instant when ``utc``)."""

    local: datetime
    tzid: str | None = None
    utc: bool = False
    all_day: bool = False


@dataclass(frozen=True)
class IcsEvent:
    uid: str
    summary: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    start: RawTime | None = None
    end: RawTime | None = None
    duration: timedelta | None = None
    organizer: str = ""
    attendees: tuple[str, ...] = ()
    status: str = ""
    method: str = ""
    sequence: int = 0
    recurring: bool = False

    @property
    def meeting_link(self) -> str | None:
        for text in (self.url, self.location, self.description):
            found = _LINK.search(text or "")
            if found:
                link = found.group(0).rstrip(".,;")
                if len(link) <= MAX_LINK_CHARS:
                    return link
        return None


# ----- time zones -------------------------------------------------------------------------------


def zone_for(name: str | None) -> ZoneInfo | None:
    """An IANA zone for ``name`` (also a known Windows name or a path ending in an IANA name), else ``None``."""
    if not name:
        return None
    cleaned = name.strip().strip('"')
    cleaned = WINDOWS_ZONES.get(cleaned, cleaned)
    if len(cleaned) > 64 or not re.fullmatch(r"[A-Za-z0-9_+\-/]+", cleaned):
        return None
    candidates = [cleaned]
    parts = cleaned.split("/")
    if len(parts) > 2:
        candidates.append("/".join(parts[-2:]))
    for cand in candidates:
        try:
            return ZoneInfo(cand)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            continue
    return None


def resolve_local(local: datetime, zone: ZoneInfo) -> list[datetime]:
    """UTC instants a wall time can mean in ``zone``: none when it does not exist (spring-forward gap), two
    when it happens twice (autumn fold), otherwise one."""
    naive = local.replace(tzinfo=None)
    out: list[datetime] = []
    for fold in (0, 1):
        utc = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        # A real wall time survives the round trip; a gap time comes back shifted.
        if utc.astimezone(zone).replace(tzinfo=None) != naive:
            continue
        if utc not in out:
            out.append(utc)
    return sorted(out)


def resolve(raw: RawTime | None) -> tuple[datetime | None, str | None]:
    """(UTC instant, zone name) for a parsed time; ``(None, None)`` when the zone is not known. A time that
    happens twice resolves to the earlier instant (callers that care use ``resolve_local``)."""
    if raw is None or raw.all_day:
        return None, None
    if raw.utc:
        return raw.local.replace(tzinfo=UTC), "UTC"
    zone = zone_for(raw.tzid)
    if zone is None:
        return None, None
    instants = resolve_local(raw.local, zone)
    return (instants[0], zone.key) if instants else (None, zone.key)


# ----- reading ----------------------------------------------------------------------------------


def _clean(value: str, limit: int = MAX_VALUE_CHARS) -> str:
    text = _UNESCAPE.sub(lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)
    return _CONTROL.sub("", text)[:limit].strip()


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            if len(lines[-1]) < MAX_VALUE_CHARS * 2:
                lines[-1] += line[1:]
        else:
            lines.append(line)
        if len(lines) > MAX_LINES:
            break
    return lines[:MAX_LINES]


_PARAM_SPLIT = re.compile(r';(?=(?:[^"]*"[^"]*")*[^"]*$)')


def _split(line: str) -> tuple[str, dict[str, str], str] | None:
    """``NAME;P=v;P2="x:y":value`` -> (NAME, params, value); the first colon outside quotes ends the name."""
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return None
    pieces = _PARAM_SPLIT.split(head)
    name = pieces[0].strip().upper()
    if not re.fullmatch(r"[A-Z0-9-]{1,40}", name):
        return None
    params: dict[str, str] = {}
    for piece in pieces[1:]:
        key, _, val = piece.partition("=")
        params[key.strip().upper()] = val.strip().strip('"')[:200]
    return name, params, value


_DT = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?(Z)?$")


def _parse_time(value: str, params: dict[str, str]) -> RawTime | None:
    found = _DT.match(value.strip())
    if not found:
        return None
    y, mo, d, hh, mi, ss, z = found.groups()
    try:
        if hh is None:
            return RawTime(datetime(int(y), int(mo), int(d)), all_day=True)
        local = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0))
    except ValueError:
        return None
    if params.get("VALUE", "").upper() == "DATE":
        return RawTime(local.replace(hour=0, minute=0, second=0), all_day=True)
    return RawTime(local, tzid=params.get("TZID") or None, utc=bool(z))


_DURATION = re.compile(r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def _parse_duration(value: str) -> timedelta | None:
    found = _DURATION.match(value.strip())
    if not found:
        return None
    sign, w, d, h, m, s = found.groups()
    delta = timedelta(weeks=int(w or 0), days=int(d or 0), hours=int(h or 0), minutes=int(m or 0),
                      seconds=int(s or 0))
    return None if sign == "-" or delta <= timedelta(0) or delta > timedelta(days=2) else delta


def parse_ics(data: bytes) -> list[IcsEvent]:
    """Events found in ``data`` (at most ``MAX_EVENTS``). Raises ``IcsError`` for oversize or non-calendar input;
    a malformed event is skipped, never guessed."""
    if len(data) > MAX_ICS_BYTES:
        raise IcsError("calendar file too large")
    text = data.decode("utf-8-sig", errors="replace")
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise IcsError("not a calendar file")
    method = ""
    events: list[IcsEvent] = []
    current: dict[str, object] | None = None
    depth = 0  # nested components inside a VEVENT (alarms) are ignored
    for line in _unfold(text):
        parsed = _split(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "BEGIN":
            kind = value.strip().upper()
            if kind == "VEVENT" and current is None:
                current = {"attendees": []}
            elif current is not None:
                depth += 1
        elif name == "END":
            kind = value.strip().upper()
            if kind == "VEVENT" and current is not None and depth == 0:
                built = _build(current, method)
                if built is not None:
                    events.append(built)
                    if len(events) >= MAX_EVENTS:
                        break
                current = None
            elif current is not None and depth > 0:
                depth -= 1
        elif current is None:
            if name == "METHOD":
                method = _clean(value, 20).upper()
        elif depth == 0:
            _collect(current, name, params, value)
    return events


def _collect(cur: dict[str, object], name: str, params: dict[str, str], value: str) -> None:
    if name in ("UID", "SUMMARY", "LOCATION", "DESCRIPTION", "URL", "STATUS"):
        cur[name.lower()] = _clean(value, 300 if name in ("UID", "SUMMARY", "LOCATION") else MAX_VALUE_CHARS)
    elif name in ("DTSTART", "DTEND"):
        cur[name.lower()] = _parse_time(value, params)
    elif name == "DURATION":
        cur["duration"] = _parse_duration(value)
    elif name == "ORGANIZER":
        cur["organizer"] = _clean(params.get("CN", ""), 120)
    elif name == "ATTENDEE":
        attendees = cur["attendees"]
        assert isinstance(attendees, list)
        who = _clean(params.get("CN", ""), 120)
        if who and len(attendees) < 20:
            attendees.append(who)
    elif name == "SEQUENCE":
        digits = value.strip()
        cur["sequence"] = int(digits) if digits.isdigit() and len(digits) < 6 else 0
    elif name in ("RRULE", "RDATE"):
        cur["recurring"] = True


def _build(cur: dict[str, object], method: str) -> IcsEvent | None:
    start = cur.get("dtstart")
    if not isinstance(start, RawTime) or start.all_day:
        return None  # no clock time: cannot be an interview slot
    end = cur.get("dtend")
    duration = cur.get("duration")
    attendees = cur.get("attendees")
    return IcsEvent(
        uid=str(cur.get("uid") or ""), summary=str(cur.get("summary") or ""),
        location=str(cur.get("location") or ""), description=str(cur.get("description") or ""),
        url=str(cur.get("url") or ""), start=start,
        end=end if isinstance(end, RawTime) and not end.all_day else None,
        duration=duration if isinstance(duration, timedelta) else None,
        organizer=str(cur.get("organizer") or ""),
        attendees=tuple(attendees) if isinstance(attendees, list) else (),
        status=str(cur.get("status") or "").upper(), method=method, sequence=int(str(cur.get("sequence") or 0)),
        recurring=bool(cur.get("recurring")))


# ----- writing ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutEvent:
    uid: str
    summary: str
    starts: datetime
    ends: datetime
    cancelled: bool = False
    location: str = ""
    url: str = ""
    description: str = ""
    sequence: int = 0
    modified: datetime | None = None


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Fold at 75 octets (never inside a multi-byte character); continuation lines start with a space."""
    out: list[str] = []
    current = ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return "\r\n".join(out)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_calendar(events: list[OutEvent], *, name: str, now: datetime) -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nchito//Interviews//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_esc(name)}", "X-PUBLISHED-TTL:PT1H"]
    for ev in events:
        lines += ["BEGIN:VEVENT", f"UID:{ev.uid}", f"DTSTAMP:{_stamp(now)}", f"DTSTART:{_stamp(ev.starts)}",
                  f"DTEND:{_stamp(ev.ends)}", f"SUMMARY:{_esc(ev.summary)}",
                  f"STATUS:{'CANCELLED' if ev.cancelled else 'CONFIRMED'}", f"SEQUENCE:{ev.sequence}",
                  f"LAST-MODIFIED:{_stamp(ev.modified or now)}"]
        if ev.location:
            lines.append(f"LOCATION:{_esc(ev.location)}")
        if ev.url:
            lines.append(f"URL:{_esc(ev.url)}")
        if ev.description:
            lines.append(f"DESCRIPTION:{_esc(ev.description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")
