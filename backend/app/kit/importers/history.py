"""Application-history CSV importer (DESIGN.md 13 step 3). Deterministic: no model is involved.

Flow: ``parse_csv`` -> ``plan`` (the preview, a diff against what is stored) -> ``commit``
(one transaction). Repeatable: every row has a stable key (``history:<id>``), so importing the
same file again changes nothing and an edited file updates the rows it changed. Everything
imported is marked ``origin = import``; applied rows are owner-attested (no evidence exists).

Columns: id, company, role, location, track, fit_1to5, link, source, date_found, closes, status,
date_tailored, date_applied, claimed_by, next_step, next_step_due, last_update, notes.
The 1-5 fit is kept as ``legacy_fit``; it is never turned into a rubric score.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.models.applications import END_STAGES, Application, Channel, Stage
from app.models.search import Job, JobSighting
from app.pipeline import corrections

IMPORT_ACTOR = "import"
KEY_PREFIX = "history:"

COLUMNS = ("id", "company", "role", "location", "track", "fit_1to5", "link", "source", "date_found", "closes",
           "status", "date_tailored", "date_applied", "claimed_by", "next_step", "next_step_due", "last_update",
           "notes")
REQUIRED = ("id", "company", "role", "status")

STATUS_TO_STAGE: dict[str, Stage] = {
    "shortlisted": Stage.shortlisted, "tailored": Stage.ready, "applied": Stage.submitted,
    "screening": Stage.screening, "interview": Stage.interview, "offer": Stage.offer,
    "accepted": Stage.accepted, "rejected": Stage.rejected, "withdrawn": Stage.withdrawn,
    "closed": Stage.closed, "skipped": Stage.skipped,
}
APPLIED_STAGES = stages.POST_SUBMIT | {Stage.rejected, Stage.withdrawn}
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%d-%m-%Y")

Action = Literal["create", "update", "unchanged", "skip", "error"]


class HistoryFormatError(ValueError):
    """The file cannot be read as a history CSV at all."""


@dataclass
class HistoryRow:
    line: int
    id: str
    company: str
    role: str
    status: str
    stage: Stage
    location: str | None = None
    track: str | None = None
    fit: int | None = None
    link: str | None = None
    source: str | None = None
    date_found: date | None = None
    closes: date | None = None
    date_tailored: date | None = None
    date_applied: date | None = None
    claimed_by: str | None = None
    next_step: str | None = None
    next_step_due: date | None = None
    last_update: date | None = None
    notes: str | None = None

    @property
    def key(self) -> str:
        return f"{KEY_PREFIX}{self.id}"

    def digest(self) -> str:
        parts = [str(getattr(self, f)) for f in sorted(self.__dataclass_fields__) if f != "line"]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


@dataclass
class RowError:
    line: int
    id: str | None
    message: str


@dataclass
class ParsedCsv:
    content_hash: str
    rows: list[HistoryRow]
    errors: list[RowError]


@dataclass
class FieldChange:
    field: str
    before: Any
    after: Any


@dataclass
class RowPlan:
    line: int
    key: str
    company: str
    role: str
    stage: Stage
    action: Action
    job: Literal["new", "existing"] | None = None
    changes: list[FieldChange] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    row: HistoryRow | None = None
    job_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None


@dataclass
class ImportPlan:
    content_hash: str
    rows: list[RowPlan]
    errors: list[RowError]

    def count(self, action: Action) -> int:
        return sum(1 for r in self.rows if r.action == action)


@dataclass
class ImportResult:
    created: int
    updated: int
    unchanged: int
    skipped: int
    errors: int
    application_ids: list[uuid.UUID]


# ----- parsing --------------------------------------------------------------------------------------


def _parse_date(raw: str | None, name: str) -> date | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{name}: '{text}' is not a date (use YYYY-MM-DD)")


def _clean(raw: str | None) -> str | None:
    text = (raw or "").strip()
    return text or None


def parse_csv(data: bytes | str) -> ParsedCsv:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HistoryFormatError("the file is empty")
    header = [h.strip().lower() for h in reader.fieldnames]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise HistoryFormatError(f"missing columns: {', '.join(missing)}")
    rows: list[HistoryRow] = []
    errors: list[RowError] = []
    seen: set[str] = set()
    for line, record in enumerate(reader, start=2):
        rec = {(k or "").strip().lower(): v for k, v in record.items()}
        if not any((v or "").strip() for v in rec.values() if isinstance(v, str)):
            continue
        row_id = _clean(rec.get("id"))
        try:
            rows.append(_row(line, rec, seen))
            seen.add(rows[-1].id)
        except ValueError as exc:
            errors.append(RowError(line, row_id, str(exc)))
    return ParsedCsv(hashlib.sha256(raw).hexdigest(), rows, errors)


def _row(line: int, rec: dict[str, str | None], seen: set[str]) -> HistoryRow:
    row_id, company, role = _clean(rec.get("id")), _clean(rec.get("company")), _clean(rec.get("role"))
    if not row_id:
        raise ValueError("id is empty")
    if row_id in seen:
        raise ValueError(f"id {row_id} appears more than once in the file")
    if not company or not role:
        raise ValueError("company and role are required")
    status = (_clean(rec.get("status")) or "").lower()
    if status not in STATUS_TO_STAGE:
        raise ValueError(f"status '{status}' is not one of {', '.join(STATUS_TO_STAGE)}")
    fit: int | None = None
    if _clean(rec.get("fit_1to5")):
        try:
            fit = int(float(str(rec["fit_1to5"]).strip()))
        except ValueError as exc:
            raise ValueError(f"fit_1to5: '{rec['fit_1to5']}' is not a number") from exc
        if not 1 <= fit <= 5:
            raise ValueError("fit_1to5 must be between 1 and 5")
    return HistoryRow(
        line=line, id=row_id, company=company, role=role, status=status, stage=STATUS_TO_STAGE[status],
        location=_clean(rec.get("location")), track=_clean(rec.get("track")), fit=fit,
        link=_clean(rec.get("link")), source=_clean(rec.get("source")),
        date_found=_parse_date(rec.get("date_found"), "date_found"), closes=_parse_date(rec.get("closes"), "closes"),
        date_tailored=_parse_date(rec.get("date_tailored"), "date_tailored"),
        date_applied=_parse_date(rec.get("date_applied"), "date_applied"),
        claimed_by=_clean(rec.get("claimed_by")), next_step=_clean(rec.get("next_step")),
        next_step_due=_parse_date(rec.get("next_step_due"), "next_step_due"),
        last_update=_parse_date(rec.get("last_update"), "last_update"), notes=_clean(rec.get("notes")))


# ----- planning (the preview) -----------------------------------------------------------------------


def _target_values(row: HistoryRow) -> dict[str, Any]:
    applied = row.stage in APPLIED_STAGES
    applied_day = row.date_applied or (row.last_update if applied else None)
    ended = row.stage in END_STAGES
    return {
        "stage": row.stage.value,
        "applied_at": corrections.noon_utc(applied_day) if applied and applied_day else None,
        "ended_at": corrections.noon_utc(row.last_update or row.date_applied or row.date_found)
        if ended and (row.last_update or row.date_applied or row.date_found) else None,
        "next_step": row.next_step,
        "next_due": row.next_step_due,
        "notes": row.notes,
        "legacy_fit": row.fit,
        "channel": Channel.manual if applied else None,
        "owner_attested": applied,
        "applied_outside": applied,
    }


def _meta(row: HistoryRow) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "legacy_id": row.id, "track": row.track, "source": row.source, "claimed_by": row.claimed_by,
        "location": row.location, "date_found": row.date_found, "closes": row.closes,
        "date_tailored": row.date_tailored, "last_update": row.last_update, "row_hash": row.digest()}
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in meta.items() if v is not None}


def _same(a: Any, b: Any) -> bool:
    if hasattr(a, "value"):
        a = a.value
    if hasattr(b, "value"):
        b = b.value
    return a == b


async def _find_job(session: AsyncSession, row: HistoryRow) -> Job | None:
    return await corrections.find_existing_job(session, url=row.link, title=row.role, employer=row.company)


async def plan(session: AsyncSession, parsed: ParsedCsv) -> ImportPlan:
    plans: list[RowPlan] = []
    claimed_jobs: dict[uuid.UUID, str] = {}
    for row in parsed.rows:
        existing = await session.scalar(select(Application).where(Application.import_key == row.key))
        if existing is not None:
            plans.append(_plan_update(row, existing))
            claimed_jobs[existing.job_id] = row.key
            continue
        job = await _find_job(session, row)
        if job is not None:
            other = await stages.blocking_application(session, job.id)
            if other is not None or job.id in claimed_jobs:
                plans.append(RowPlan(row.line, row.key, row.company, row.role, row.stage, "skip", job="existing",
                                     row=row, job_id=job.id, application_id=other.id if other else None,
                                     messages=["this job already has an application; left alone"]))
                continue
            claimed_jobs[job.id] = row.key
        rp = RowPlan(row.line, row.key, row.company, row.role, row.stage, "create",
                     job="existing" if job else "new", row=row, job_id=job.id if job else None)
        for name, value in _target_values(row).items():
            if value is not None and value is not False:
                rp.changes.append(FieldChange(name, None, _show(value)))
        if row.stage in APPLIED_STAGES and not (row.date_applied or row.last_update):
            rp.messages.append("applied with no date; follow-up reminders cannot count from it")
        plans.append(rp)
    return ImportPlan(parsed.content_hash, plans, parsed.errors)


def _show(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value.value if hasattr(value, "value") else value


def _plan_update(row: HistoryRow, app: Application) -> RowPlan:
    rp = RowPlan(row.line, row.key, row.company, row.role, row.stage, "unchanged", job="existing", row=row,
                 job_id=app.job_id, application_id=app.id)
    if app.import_meta.get("row_hash") == row.digest():
        return rp
    for name, after in _target_values(row).items():
        before = getattr(app, name)
        if not _same(before, after):
            rp.changes.append(FieldChange(name, _show(before), _show(after)))
    rp.action = "update" if rp.changes else "unchanged"
    if not rp.changes and _meta(row) != {**app.import_meta}:
        rp.action = "update"  # only the imported extras changed
        rp.messages.append("only imported details (track, source, dates) changed")
    return rp


# ----- commit ---------------------------------------------------------------------------------------


async def commit(session: AsyncSession, parsed: ParsedCsv, *, actor: str) -> ImportResult:
    """Apply the import in the caller's transaction (all rows or none). Re-plans against the
    current database, so a preview that is out of date cannot apply stale decisions."""
    import_plan = await plan(session, parsed)
    ids: list[uuid.UUID] = []
    now = utcnow()
    for rp in import_plan.rows:
        if rp.action in ("unchanged", "skip") or rp.row is None:
            continue
        if rp.action == "create":
            app = await _create(session, rp.row, rp.job_id)
            await stages.add_event(session, app.id, "imported", IMPORT_ACTOR,
                                   {"source": "history_csv", "legacy_id": rp.row.id, "status": rp.row.status,
                                    "line": rp.row.line, "by": actor})
        else:
            app = await session.get(Application, rp.application_id)
            assert app is not None
            _apply_values(app, rp.row)
            await stages.add_event(session, app.id, "import_update", IMPORT_ACTOR, {
                "source": "history_csv", "legacy_id": rp.row.id, "by": actor,
                "changes": [{"field": c.field, "before": c.before, "after": c.after} for c in rp.changes]})
        ids.append(app.id)
    result = ImportResult(created=import_plan.count("create"), updated=import_plan.count("update"),
                          unchanged=import_plan.count("unchanged"), skipped=import_plan.count("skip"),
                          errors=len(import_plan.errors), application_ids=ids)
    await audit.record(session, actor=actor, action="history.imported", subject_type="application_history",
                       subject_id=import_plan.content_hash[:16],
                       detail={"created": result.created, "updated": result.updated,
                               "unchanged": result.unchanged, "skipped": result.skipped, "errors": result.errors,
                               "at": now.isoformat()})
    return result


def _apply_values(app: Application, row: HistoryRow) -> None:
    values = _target_values(row)
    app.stage = Stage(values["stage"])
    for name in ("applied_at", "ended_at", "next_step", "next_due", "notes", "legacy_fit", "channel",
                 "owner_attested", "applied_outside"):
        setattr(app, name, values[name])
    app.import_meta = _meta(row)
    if app.stage not in END_STAGES:
        app.ended_at = None


async def _create(session: AsyncSession, row: HistoryRow, job_id: uuid.UUID | None) -> Application:
    job = await session.get(Job, job_id) if job_id else None
    if job is None:
        job = await corrections.create_job(
            session, title=row.role, employer=row.company, origin="import", url=row.link, location_raw=row.location,
            deadline=row.closes, triage=_triage(row.stage),
            seen_at=corrections.noon_utc(row.date_found) if row.date_found else None)
    elif row.link:
        has = await session.scalar(select(JobSighting).where(JobSighting.job_id == job.id,
                                                              JobSighting.url == row.link))
        if has is None:
            seen = corrections.noon_utc(row.date_found) if row.date_found else utcnow()
            session.add(JobSighting(job_id=job.id, source_id=None, url=row.link, first_seen_at=seen,
                                    last_seen_at=seen))
    app = Application(job_id=job.id, origin="import", import_key=row.key)
    session.add(app)
    _apply_values(app, row)
    await session.flush()
    return app


def _triage(stage: Stage) -> str:
    if stage == Stage.skipped:
        return "skipped"
    if stage in END_STAGES:
        return "archived"
    return "shortlisted"
