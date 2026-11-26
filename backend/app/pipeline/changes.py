"""Posting change alerts (DESIGN.md 18.4, 10.3a). Invariants, not settings:

- **A failed fetch is unknown, never closed.** Only a source that says the role is closed produces a ``closed``
  change; an unreadable posting leaves the watch result ``unknown`` and changes nothing else.
- **Field level.** Each change names its kind and field and shows before and after ("Remote worldwide ->
  UK residents only"). Kinds: ``closed``, ``reopened``, ``deadline_moved``, ``pay_changed``,
  ``requirements_changed``, ``apply_method_changed``, ``eligibility_changed``, ``location_changed`` and
  ``wording`` (title or text only).
- **Material changes act, wording does not.** A material change (everything but ``reopened``, ``wording`` and a
  change to preferred requirements only) invalidates a current packet built on an older version of the posting
  (the approval goes with it, outstanding permits are revoked) and opens a pending action for the owner. A closed
  role opens a pending action but leaves the packet (the send gates refuse a closed role anyway). A wording
  change is recorded and nothing else.
- **Compared with what the packet was built on.** The version a packet was built on is stored when the packet is
  built (``capture_version``); when it is not known the change is judged against the previous scan.
- Roles already submitted are never touched: the change goes on their timeline.
- Every change is in ``job_change``, the audit and the application timeline.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import outcomes, packets, stages
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.models.applications import (
    END_STAGES,
    Application,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.changes import JobChange, JobVersion, JobWatch
from app.models.search import Availability, Job

PRE_SUBMIT = frozenset({Stage.shortlisted, Stage.tailoring, Stage.ready})
FACET_FIELDS = ("work_model", "remote_scope", "where_must_live", "work_rights", "visa_sponsorship",
                "relocation_required", "relocation_assistance", "employment_type", "hiring_arrangement")
POSTING_CHANGED = "posting_changed"
POSTING_CLOSED = "posting_closed"

CHANGE_LABELS = {
    "closed": "The role closed", "reopened": "The role reopened", "deadline_moved": "Deadline changed",
    "pay_changed": "Pay changed", "requirements_changed": "Requirements changed",
    "apply_method_changed": "How to apply changed", "eligibility_changed": "Who can apply changed",
    "location_changed": "Location changed", "wording": "Wording changed"}


# ----- snapshots --------------------------------------------------------------------------------


def _facet_value(value: Any) -> Any:
    inner = getattr(value, "value", value)
    return inner.model_dump(mode="json") if hasattr(inner, "model_dump") else inner


def text_digest(text: str | None) -> str:
    """Digest of the posting text ignoring case and spacing, so a reflow is not a change."""
    return hashlib.sha256(re.sub(r"\s+", " ", (text or "").strip().lower()).encode()).hexdigest()


def snapshot_of(job: Job) -> dict[str, Any]:
    """The change-relevant fields of a job as plain JSON (no posting text, only its digest)."""
    facets = {name: _facet_value(getattr(job.facets, name, None)) for name in FACET_FIELDS}
    return {
        "title": job.title,
        "deadline": job.deadline.isoformat() if job.deadline else None,
        "deadline_state": getattr(job.deadline_state, "value", job.deadline_state),
        "pay": {"state": getattr(job.pay_state, "value", job.pay_state), "min": job.pay_min_minor,
                "max": job.pay_max_minor, "currency": job.pay_currency, "period": job.pay_period},
        "apply": {"method": job.apply_method, "url": job.apply_url, "email": job.apply_email_owner or job.apply_email},
        "location": {"country": job.location.country, "region": job.location.region, "city": job.location.city},
        "facets": facets,
        "required_skills": sorted(job.facets.required_skills),
        "requirements": [{"kind": r.kind, "text": r.text} for r in job.requirements],
        "text_digest": text_digest(job.raw_text),
        "content_hash": job.content_hash,
    }


def _digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def capture_version(session: AsyncSession, job: Job, *, now: datetime | None = None) -> None:
    """Remember the job as it is now (the same state twice is stored once)."""
    snapshot = snapshot_of(job)
    stmt = pg_insert(JobVersion).values(
        id=uuid.uuid4(), job_id=job.id, content_hash=job.content_hash, snapshot_digest=_digest(snapshot),
        snapshot=snapshot, captured_at=now or utcnow()).on_conflict_do_nothing(constraint="job_snapshot")
    await session.execute(stmt)


async def version_for(session: AsyncSession, job_id: uuid.UUID, content_hash: str | None, *,
                      at: datetime | None = None) -> dict[str, Any] | None:
    """The snapshot with this content hash last stored at or before ``at`` (a packet's creation time)."""
    if content_hash is None:
        return None
    stmt = select(JobVersion).where(JobVersion.job_id == job_id, JobVersion.content_hash == content_hash)
    if at is not None:
        stmt = stmt.where(JobVersion.created_at <= at)
    row = await session.scalar(stmt.order_by(JobVersion.created_at.desc(), JobVersion.captured_at.desc()).limit(1))
    return row.snapshot if row else None


async def latest_version(session: AsyncSession, job_id: uuid.UUID) -> dict[str, Any] | None:
    row = await session.scalar(select(JobVersion).where(JobVersion.job_id == job_id)
                               .order_by(JobVersion.created_at.desc(), JobVersion.captured_at.desc()).limit(1))
    return row.snapshot if row else None


# ----- diff -------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _show(value: Any) -> str:
    if value is None or value == "" or value == "not_stated":
        return "not stated"
    if isinstance(value, dict):
        if "places" in value or "kind" in value:
            places = ", ".join(value.get("places") or [])
            return places or str(value.get("kind", "not stated")).replace("_", " ")
        return ", ".join(f"{k} {v}" for k, v in value.items() if v is not None) or "not stated"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "none"
    return str(value).replace("_", " ")


def _pay_text(pay: dict[str, Any]) -> str:
    if pay.get("state") == "not_stated" or (pay.get("min") is None and pay.get("max") is None):
        return "not stated"
    low, high = pay.get("min"), pay.get("max")
    amount = f"{low / 100:,.0f}" if high in (None, low) else f"{(low or 0) / 100:,.0f} to {high / 100:,.0f}"
    currency = f" {pay['currency']}" if pay.get("currency") else ""
    return f"{amount}{currency} per {pay.get('period') or '?'} ({pay.get('state')})"


def _change(kind: str, field_name: str, before: Any, after: Any, *, material: bool, text: str | None = None
            ) -> dict[str, Any]:
    return {"kind": kind, "field": field_name, "before": before, "after": after, "material": material,
            "summary": text or f"{CHANGE_LABELS[kind]}: {_show(before)} -> {_show(after)}"}


def _requirement_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    def split(snap: dict[str, Any]) -> tuple[set[str], set[str]]:
        required = {_norm(r["text"]) for r in snap.get("requirements", []) if r.get("kind") == "required"}
        required |= {_norm(s) for s in snap.get("required_skills", [])}
        preferred = {_norm(r["text"]) for r in snap.get("requirements", []) if r.get("kind") != "required"}
        return required, preferred

    (old_req, old_pref), (new_req, new_pref) = split(before), split(after)
    out = []
    if old_req != new_req:
        added, removed = sorted(new_req - old_req), sorted(old_req - new_req)
        out.append(_change("requirements_changed", "requirements", sorted(old_req), sorted(new_req), material=True,
                           text="Requirements changed: " + "; ".join(
                               [f"added {', '.join(added)}" if added else "", f"removed {', '.join(removed)}"
                                if removed else ""]).strip("; ")))
    if old_pref != new_pref:
        out.append(_change("requirements_changed", "preferred_requirements", sorted(old_pref), sorted(new_pref),
                           material=False, text="Preferred requirements changed"))
    return out


def diff(before: dict[str, Any], after: dict[str, Any], *, availability_before: str | None = None,
         availability_after: str | None = None) -> list[dict[str, Any]]:
    """The field-level changes from ``before`` to ``after`` (both from :func:`snapshot_of`). ``unknown``
    availability on either side never produces a change: only a source's own ``closed`` does."""
    out: list[dict[str, Any]] = []
    if availability_after == "closed" and availability_before != "closed":
        out.append(_change("closed", "availability", availability_before, "closed", material=True,
                           text="The role is closed"))
    elif availability_before == "closed" and availability_after == "open":
        out.append(_change("reopened", "availability", "closed", "open", material=False, text="The role reopened"))
    if (before["deadline"], before["deadline_state"]) != (after["deadline"], after["deadline_state"]):
        def when(s: dict[str, Any]) -> str | None:
            return s["deadline"] or (None if s["deadline_state"] == "not_stated" else s["deadline_state"])
        out.append(_change("deadline_moved", "deadline", when(before), when(after), material=True))
    if before["pay"] != after["pay"]:
        out.append(_change("pay_changed", "pay", before["pay"], after["pay"], material=True,
                           text=f"Pay changed: {_pay_text(before['pay'])} -> {_pay_text(after['pay'])}"))
    out.extend(_requirement_changes(before, after))
    if before["apply"] != after["apply"]:
        out.append(_change("apply_method_changed", "apply", before["apply"], after["apply"], material=True,
                           text="How to apply changed: "
                                f"{_show(before['apply'].get('method'))} -> {_show(after['apply'].get('method'))}"
                                + ("; link changed" if before["apply"].get("url") != after["apply"].get("url")
                                   else "") + ("; address changed" if before["apply"].get("email")
                                               != after["apply"].get("email") else "")))
    if before["location"] != after["location"]:
        out.append(_change("location_changed", "location", before["location"], after["location"], material=True))
    for name in FACET_FIELDS:
        if before["facets"].get(name) != after["facets"].get(name):
            out.append(_change("eligibility_changed", name, before["facets"].get(name), after["facets"].get(name),
                               material=True, text=f"{name.replace('_', ' ').capitalize()}: "
                                                   f"{_show(before['facets'].get(name))} -> "
                                                   f"{_show(after['facets'].get(name))}"))
    if not any(c["material"] for c in out) and before["title"] != after["title"]:
        out.append(_change("wording", "title", before["title"], after["title"], material=False))
    if not out and before["text_digest"] != after["text_digest"]:
        out.append(_change("wording", "text", None, None, material=False, text="The posting text was reworded"))
    return out


def is_material(changes: list[dict[str, Any]]) -> bool:
    return any(c["material"] for c in changes)


# ----- reacting ---------------------------------------------------------------------------------


@dataclass
class Effects:
    applications: list[str] = field(default_factory=list)
    invalidated_packets: list[str] = field(default_factory=list)
    pending_actions: list[str] = field(default_factory=list)


async def _open_action(session: AsyncSession, app: Application, kind: str, title: str, detail: dict[str, Any]
                       ) -> PendingAction:
    """One open action per application and kind: a newer change updates it."""
    rows = (await session.scalars(select(PendingAction).where(
        PendingAction.application_id == app.id, PendingAction.status == PendingStatus.open,
        PendingAction.type == PendingActionType.follow_up))).all()
    for action in rows:
        if action.detail.get("kind") == kind:
            action.title, action.detail = title[:300], {**action.detail, **detail}
            await session.flush()
            return action
    action = PendingAction(type=PendingActionType.follow_up, application_id=app.id, title=title[:300],
                           detail={"kind": kind, **detail})
    session.add(action)
    await session.flush()
    return action


def _summaries(changes: list[dict[str, Any]]) -> list[str]:
    return [c["summary"] for c in changes if c["material"]] or [c["summary"] for c in changes]


async def _react(session: AsyncSession, job: Job, row: JobChange, changes: list[dict[str, Any]], *,
                 actor: str, now: datetime) -> Effects:
    effects = Effects()
    material = is_material(changes)
    closed = any(c["kind"] == "closed" for c in changes)
    if not (material or closed):
        return effects
    apps = (await session.scalars(select(Application).where(
        Application.job_id == job.id, Application.stage.not_in(list(END_STAGES))))).all()
    for app in apps:
        effects.applications.append(str(app.id))
        detail = {"job_id": str(job.id), "job_change_id": str(row.id), "changes": _summaries(changes)}
        await stages.add_event(session, app.id, "posting_changed", actor, {**detail, "stage": app.stage.value})
        if app.stage not in PRE_SUBMIT:
            continue  # already sent or in flight: recorded on the timeline, never touched
        locked = await outcomes.lock_application(session, app.id)
        packet = await packets.current(session, locked.id)
        stale_changes = changes
        if packet is not None:
            baseline = await version_for(session, job.id, packet.contents.job_version, at=packet.created_at)
            if baseline is not None:  # judge against what the packet was built on, not the last scan
                stale_changes = diff(baseline, snapshot_of(job))
        packet_material = is_material(stale_changes)
        approved = packet is not None and locked.approved_packet_id == packet.id
        if packet is not None and packet_material:
            why = "posting changed: " + "; ".join(_summaries(stale_changes))
            await packets.invalidate(session, locked, packet, why, actor=actor, now=now)
            effects.invalidated_packets.append(str(packet.id))
        label = f"{job.title} at {job.employer}"
        if closed:
            action = await _open_action(session, locked, POSTING_CLOSED, f"Role closed: {label}",
                                        {**detail, "approved_packet_waiting": approved,
                                         "note": "The posting is closed; nothing will be sent for it."})
            effects.pending_actions.append(str(action.id))
        elif packet_material and (approved or packet is not None or locked.stage == Stage.ready):
            action = await _open_action(
                session, locked, POSTING_CHANGED, f"Posting changed: {label}",
                {**detail, "changes": _summaries(stale_changes), "packet_invalidated": packet is not None,
                 "was_approved": approved,
                 "note": "The approved packet no longer matches the posting; prepare and approve it again."
                 if approved else "Review the change before you apply."})
            effects.pending_actions.append(str(action.id))
    return effects


async def record_changes(session: AsyncSession, job: Job, *, before: dict[str, Any], availability_before: Availability,
                         actor: str, source: str = "recheck", now: datetime | None = None) -> JobChange | None:
    """Compare ``job`` now with the last stored version (or ``before``, the state just before a recheck wrote
    to it when nothing is stored), record a :class:`JobChange` and react. Returns None when nothing changed."""
    now = now or utcnow()
    baseline = await latest_version(session, job.id) or before
    after = snapshot_of(job)
    after_availability = job.availability.value
    changes = diff(baseline, after, availability_before=availability_before.value,
                   availability_after=after_availability)
    await capture_version(session, job, now=now)
    if not changes:
        return None
    row = JobChange(job_id=job.id, from_hash=baseline.get("content_hash"), to_hash=job.content_hash, changes=changes,
                    kinds=list(dict.fromkeys(c["kind"] for c in changes)), material=is_material(changes),
                    source=source, detected_at=now)
    session.add(row)
    await session.flush()
    effects = await _react(session, job, row, changes, actor=actor, now=now)
    row.effects = {"applications": effects.applications, "invalidated_packets": effects.invalidated_packets,
                   "pending_actions": effects.pending_actions}
    await audit.record(session, actor=actor, action="job.changed", subject_type="job", subject_id=job.id,
                       detail={"change_id": str(row.id), "kinds": row.kinds, "material": row.material,
                               "summaries": _summaries(changes), **row.effects})
    await publish(session, "job.changed", {"job_id": str(job.id), "change_id": str(row.id)})
    await session.flush()
    return row


# ----- scheduled scan ---------------------------------------------------------------------------


@dataclass
class ScanReport:
    scanned: int = 0
    changed: list[uuid.UUID] = field(default_factory=list)
    closed: list[uuid.UUID] = field(default_factory=list)
    unknown: list[uuid.UUID] = field(default_factory=list)


async def watched_job_ids(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Jobs due for a recheck, least recently scanned first, at most ``tracking.change_batch_size``."""
    values = await settings_service.values(session)
    if not values["tracking.change_watch_enabled"]:
        return []
    stages_watched = [Stage(s) for s in values["tracking.change_watch_stages"]]
    ids: set[uuid.UUID] = set()
    if stages_watched:
        in_stage = select(Application.job_id).where(Application.stage.in_(stages_watched))
        ids |= set((await session.scalars(in_stage)).all())
    if values["tracking.change_watch_pinned"]:
        ids |= set((await session.scalars(select(Job.id).where(Job.pinned.is_(True)))).all())
    if not ids:
        return []
    due_before = now - timedelta(hours=int(values["tracking.change_check_every_hours"]))
    rows = (await session.execute(
        select(Job.id, JobWatch.last_scanned_at).outerjoin(JobWatch, JobWatch.job_id == Job.id)
        .where(Job.id.in_(ids), Job.merged_into_id.is_(None), Job.availability != Availability.closed))).all()
    due = sorted((r for r in rows if r[1] is None or r[1] <= due_before),
                 key=lambda r: (r[1] is not None, r[1] or now))
    return [r[0] for r in due[:int(values["tracking.change_batch_size"])]]


async def _mark_scanned(session: AsyncSession, job_id: uuid.UUID, result: str, note: str | None, now: datetime) -> None:
    stmt = pg_insert(JobWatch).values(id=uuid.uuid4(), job_id=job_id, last_scanned_at=now, last_result=result,
                                      note=note)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[JobWatch.job_id], set_={"last_scanned_at": now, "last_result": result, "note": note}))


async def scan(session: AsyncSession, *, now: datetime | None = None, deps: Any = None, llm: Any = None,
               actor: str = "system:watch") -> ScanReport:
    """Recheck the watched roles that are due. Commits after each role, so one failure loses nothing. A role
    that cannot be read is recorded ``unknown`` (and rechecked after the interval), never ``closed``."""
    from app.pipeline import recheck

    now = now or utcnow()
    report = ScanReport()
    for job_id in await watched_job_ids(session, now):
        job = await session.get(Job, job_id)
        if job is None:
            continue
        try:
            result = await recheck.recheck_job(session, job, actor=actor, deps=deps, llm=llm)
        except Exception as exc:  # one bad posting must not stop the pass
            await session.rollback()
            await _mark_scanned(session, job_id, "unknown", f"{type(exc).__name__}: {exc}"[:300], now)
            report.unknown.append(job_id)
            await session.commit()
            continue
        report.scanned += 1
        if result.availability_after == "closed" and result.availability_before != "closed":
            outcome, note = "closed", None
            report.closed.append(job_id)
        elif result.content_changed:
            outcome, note = "changed", ", ".join(result.changed_fields)
            report.changed.append(job_id)
        elif result.availability_after == "unknown" or (not result.fetched and result.note):
            outcome, note = "unknown", result.note or "the source could not confirm the role is open"
            report.unknown.append(job_id)
        else:
            outcome, note = "unchanged", None
        await _mark_scanned(session, job_id, outcome, note, now)
        await session.commit()
    return report


async def acknowledge(session: AsyncSession, change: JobChange, *, actor: str, now: datetime | None = None) -> None:
    if change.acknowledged_at is None:
        change.acknowledged_at, change.acknowledged_by = now or utcnow(), actor
        await audit.record(session, actor=actor, action="job.change_acknowledged", subject_type="job_change",
                           subject_id=change.id, detail={"job_id": str(change.job_id), "kinds": change.kinds})
        await session.flush()
