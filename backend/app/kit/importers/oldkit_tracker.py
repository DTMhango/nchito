"""Old tracker spreadsheets: arbitrary column names, mixed date formats, one canonical CSV out.

The history importer (``history.py``) reads fixed columns. A hand-made tracker never has them, so this
module maps its headings to the canonical columns with a synonym map (the ``data.old_kit_tracker_headers``
setting), reads dates written in several ways, and writes one CSV the history importer accepts. Headings
that match nothing are kept in the notes column; a tracker without a company, a role and a status column is
not imported (unknown is not yes: a status is never invented). Row dates that cannot be read are left empty
and counted in the notices.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.kit.importers.history import COLUMNS, STATUS_TO_STAGE

DATE_COLUMNS = ("date_found", "closes", "date_tailored", "date_applied", "next_step_due", "last_update")
DAY_FIRST = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y")
UNAMBIGUOUS = ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y",
               "%d-%b-%Y", "%d-%b-%y", "%d %b %y")
# Words a tracker uses for a state the history importer names differently (parser vocabulary).
STATUS_WORDS = {"submitted": "applied", "sent": "applied", "interviewing": "interview", "interviewed": "interview",
                "declined": "rejected", "unsuccessful": "rejected", "not selected": "rejected",
                "offered": "offer", "hired": "accepted", "pulled out": "withdrawn", "found": "shortlisted"}
REQUIRED = ("company", "role", "status")


@dataclass
class TrackerRows:
    rows: list[dict[str, str]] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    why_not: str | None = None  # set when the file cannot be used as a tracker


def _norm(heading: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", heading.casefold()).split())


def synonym_map(entries: Sequence[str]) -> dict[str, str]:
    """``{normalised heading: canonical column}`` from 'column: heading, heading' entries."""
    out: dict[str, str] = {_norm(c): c for c in COLUMNS}
    for entry in entries:
        name, _, words = entry.partition(":")
        column = name.strip()
        if column not in COLUMNS:
            continue
        for word in words.split(","):
            if _norm(word):
                out.setdefault(_norm(word), column)
    return out


def read_dates(value: str) -> tuple[date | None, bool]:
    """``(date, was_ambiguous)``. A day-first reading is used for 03/04/2026 (and flagged); an Excel serial
    number is read as a date. ``(None, False)`` when it is not a date."""
    text = value.strip()
    if not text:
        return None, False
    if re.fullmatch(r"\d{5}(\.\d+)?", text) and 20000 < float(text) < 80000:
        return date(1899, 12, 30) + timedelta(days=int(float(text))), False
    for fmt in UNAMBIGUOUS:
        try:
            return datetime.strptime(text, fmt).date(), False
        except ValueError:
            continue
    for fmt in DAY_FIRST:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        first, second = re.split(r"[/.-]", text)[:2]
        return parsed, int(first) <= 12 and int(second) <= 12 and first != second
    return None, False


def _status(value: str) -> str:
    low = " ".join(value.casefold().split())
    return STATUS_WORDS.get(low, low if low in STATUS_TO_STAGE else value.strip())


def read_tracker(csv_text: str, file: str, synonyms: Sequence[str]) -> TrackerRows:
    result = TrackerRows()
    mapping = synonym_map(synonyms)
    rows = [r for r in csv.reader(io.StringIO(csv_text)) if any(c.strip() for c in r)]
    if not rows:
        result.why_not = "it is empty"
        return result
    header = rows[0]
    columns: dict[int, str] = {}
    extras: dict[int, str] = {}
    for i, heading in enumerate(header):
        canon = mapping.get(_norm(heading))
        if canon and canon not in columns.values():
            columns[i] = canon
        elif heading.strip():
            extras[i] = heading.strip()
    missing = [c for c in REQUIRED if c not in columns.values()]
    if missing:
        result.why_not = (f"no {', '.join(missing)} column was recognised (headings: "
                          f"{', '.join(h.strip() for h in header if h.strip())[:160]}). Add the wording to "
                          "the old tracker column names setting and import again")
        return result
    ambiguous = unreadable = duplicates = 0
    seen: set[str] = set()
    for raw in rows[1:]:
        cells = {columns[i]: raw[i].strip() for i in columns if i < len(raw)}
        if not cells.get("company") or not cells.get("role"):
            continue
        for col in DATE_COLUMNS:
            if cells.get(col):
                parsed, amb = read_dates(cells[col])
                if parsed is None:
                    unreadable += 1
                    cells[col] = ""
                else:
                    cells[col] = parsed.isoformat()
                    ambiguous += amb
        cells["status"] = _status(cells.get("status", ""))
        key = cells.get("id") or "t" + hashlib.sha256(
            f"{cells['company']}|{cells['role']}|{cells.get('link', '')}".casefold().encode()).hexdigest()[:10]
        same_row = f"{cells['company']}|{cells['role']}|{cells.get('date_applied', '')}".casefold()
        if key in seen or same_row in seen:  # the same id, or the same application typed twice
            duplicates += 1
            continue
        seen.update({key, same_row})
        cells["id"] = key
        spill = [f"{extras[i]}: {raw[i].strip()}" for i in extras if i < len(raw) and raw[i].strip()]
        if spill:
            cells["notes"] = "; ".join(filter(None, [cells.get("notes", ""), *spill]))
        result.rows.append(cells)
    if ambiguous:
        result.notices.append(f"{file}: {ambiguous} date(s) such as 03/04/2026 were read day first; check them.")
    if duplicates:
        result.notices.append(f"{file}: {duplicates} repeated row(s) were left out.")
    if unreadable:
        result.notices.append(f"{file}: {unreadable} date(s) could not be read and were left empty.")
    if not result.rows:
        result.why_not = "no row had both a company and a role"
    return result


def to_csv(rows: Sequence[dict[str, str]]) -> bytes:
    """One CSV in the history importer's columns (the first file wins when two trackers repeat a row)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    seen: set[str] = set()
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        writer.writerow([row.get(c, "") for c in COLUMNS])
    return out.getvalue().encode()


def looks_like_tracker(csv_text: str, synonyms: Sequence[str]) -> bool:
    """A spreadsheet nobody named as a tracker: it is one when its headings include a company and a role."""
    mapping = synonym_map(synonyms)
    first = next((r for r in csv.reader(io.StringIO(csv_text)) if any(c.strip() for c in r)), [])
    found = {mapping.get(_norm(h)) for h in first}
    return {"company", "role"} <= found
