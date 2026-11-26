"""Corrections the owner makes by hand (DESIGN.md 18.4, wave 1).

- "I applied myself": a job (existing, or created on the spot) becomes an application the
  system counts at once for duplicates, employer limits and follow-ups. No evidence is made up:
  the application is marked owner-attested.
- Merge duplicate jobs: sightings, tags, contacts and application history move to the kept job.
- Split a wrongly merged sighting into its own job (or revive the job it was merged away from).
- Fix a wrong employer match: updates the alias table, then asks the conflict engine to
  re-evaluate the groups involved through a registered hook (no-op until that stream registers).

Every correction writes an audit event; merge records enough to be undone by a split.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.models.applications import Application, Contact, Stage
from app.models.platform import AuditEvent
from app.models.search import DeadlineState, EmployerAlias, Job, JobSighting


class CorrectionError(Exception):
    """A refused correction. ``status`` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ----- conflict re-evaluation hook ------------------------------------------------------------------

ConflictReevaluator = Callable[[AsyncSession, set[str]], Awaitable[None]]


async def _noop_reevaluator(session: AsyncSession, canonical_employers: set[str]) -> None:
    return None


_reevaluator: ConflictReevaluator = _noop_reevaluator


def set_conflict_reevaluator(hook: ConflictReevaluator | None) -> None:
    """The conflicts stream registers its re-evaluation here; ``None`` restores the no-op."""
    global _reevaluator
    _reevaluator = hook or _noop_reevaluator


async def reevaluate_conflicts(session: AsyncSession, canonical_employers: set[str]) -> None:
    if canonical_employers:
        await _reevaluator(session, canonical_employers)


# ----- helpers --------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


async def canonical_employer(session: AsyncSession, name: str) -> str:
    name = " ".join(name.split())
    alias = await session.scalar(select(EmployerAlias).where(func.lower(EmployerAlias.alias) == name.lower()))
    return alias.canonical if alias else name


def content_hash(*parts: str | None) -> str:
    return hashlib.sha256("\x1f".join(_norm(p or "") for p in parts).encode()).hexdigest()


def noon_utc(day: date) -> datetime:
    return datetime.combine(day, time(12, 0), tzinfo=UTC)


async def find_existing_job(session: AsyncSession, *, url: str | None, title: str, employer: str) -> Job | None:
    """Reuse a job already known by link, or by employer and title, instead of creating a twin."""
    if url:
        job = await session.scalar(
            select(Job).join(JobSighting, JobSighting.job_id == Job.id)
            .where(JobSighting.url == url, Job.merged_into_id.is_(None)).limit(1))
        if job:
            return job
    canonical = await canonical_employer(session, employer)
    return await session.scalar(
        select(Job).where(func.lower(Job.canonical_employer) == canonical.lower(),
                          func.lower(Job.title) == title.strip().lower(), Job.merged_into_id.is_(None))
        .order_by(Job.created_at).limit(1))


async def create_job(session: AsyncSession, *, title: str, employer: str, origin: str, url: str | None = None,
                     location_raw: str | None = None, deadline: date | None = None, triage: str = "shortlisted",
                     seen_at: datetime | None = None) -> Job:
    from app.schemas.json_types import StructuredLocation

    job = Job(
        title=title.strip(), employer=" ".join(employer.split()),
        canonical_employer=await canonical_employer(session, employer),
        content_hash=content_hash(title, employer, url), origin=origin, triage=triage, apply_url=url,
        location=StructuredLocation(raw=location_raw) if location_raw else StructuredLocation(),
        deadline=deadline, deadline_state=DeadlineState.dated if deadline else DeadlineState.not_stated)
    session.add(job)
    await session.flush()
    if url:
        seen = seen_at or utcnow()
        session.add(JobSighting(job_id=job.id, source_id=None, url=url, first_seen_at=seen, last_seen_at=seen))
        await session.flush()
    return job


# ----- I applied myself -----------------------------------------------------------------------------


@dataclass
class AppliedMyself:
    applied_on: date | None = None
    channel: str = "manual"
    reference: str | None = None
    note: str | None = None
    files: list[str] = field(default_factory=list)
    campaign_id: uuid.UUID | None = None


async def log_applied_myself(session: AsyncSession, job: Job, body: AppliedMyself, *, actor: str,
                             now: datetime | None = None) -> Application:
    """Record that the owner applied outside the platform. Counts at once for duplicate checks,
    employer limits and follow-up reminders; creates no evidence (the row is owner-attested)."""
    from app.models.applications import Channel

    now = now or utcnow()
    if job.merged_into_id is not None:
        raise CorrectionError("this job was merged into another; log the application there")
    if body.applied_on is not None and body.applied_on > now.date():
        raise CorrectionError("the application date cannot be in the future", 422)
    existing = await stages.blocking_application(session, job.id)
    if existing is not None and existing.stage not in stages.APPLIED_MYSELF_FROM:
        raise CorrectionError(f"already applied: this job has an application in {existing.stage.value}")
    if existing is None:
        app = Application(job_id=job.id, campaign_id=body.campaign_id, stage=Stage.shortlisted, origin="owner")
        session.add(app)
        await session.flush()
        await stages.add_event(session, app.id, "created", actor, {"origin": "applied_myself"})
    else:
        app = existing
    at = noon_utc(body.applied_on) if body.applied_on else now
    app.applied_at = at
    app.channel = Channel(body.channel)
    if body.reference:
        app.reference = body.reference
    await stages.transition(
        session, app, Stage.submitted, actor=actor, via="applied_myself", now=at,
        why=body.note or "Owner applied outside Nchito",
        detail={"reference": body.reference, "channel": body.channel, "files": body.files, "owner_attested": True})
    app.applied_at = at
    await audit.record(session, actor=actor, action="application.applied_myself", subject_type="application",
                       subject_id=app.id, detail={"job_id": str(job.id), "applied_on": at.date().isoformat(),
                                                  "reference": body.reference, "files": body.files})
    live = await stages.live_applications_at_employer(session, job.canonical_employer)
    await stages.add_event(session, app.id, "employer_count", "system",
                           {"employer": job.canonical_employer, "live_applications": live})
    await reevaluate_conflicts(session, {job.canonical_employer})
    return app


# ----- merge ----------------------------------------------------------------------------------------


@dataclass
class MergeResult:
    winner: Job
    merged: list[uuid.UUID]


async def _load_job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise CorrectionError("job not found", 404)
    return job


async def merge_jobs(session: AsyncSession, winner_id: uuid.UUID, duplicate_ids: list[uuid.UUID], *,
                     actor: str) -> MergeResult:
    winner = await _load_job(session, winner_id)
    if winner.merged_into_id is not None:
        raise CorrectionError("the job to keep was itself merged into another job")
    if winner_id in duplicate_ids:
        raise CorrectionError("a job cannot be merged into itself", 422)
    merged: list[uuid.UUID] = []
    employers = {winner.canonical_employer}
    for dup_id in dict.fromkeys(duplicate_ids):
        dup = await _load_job(session, dup_id)
        if dup.merged_into_id is not None:
            raise CorrectionError(f"{dup.title} was already merged into another job")
        employers.add(dup.canonical_employer)
        await _merge_one(session, winner, dup, actor)
        merged.append(dup.id)
    await session.flush()
    await reevaluate_conflicts(session, employers)
    return MergeResult(winner, merged)


async def _merge_one(session: AsyncSession, winner: Job, dup: Job, actor: str) -> None:
    dup_apps = list(await session.scalars(select(Application).where(Application.job_id == dup.id)))
    winner_apps = list(await session.scalars(select(Application).where(Application.job_id == winner.id)))
    if (any(a.stage in _live() for a in dup_apps) and any(a.stage in _live() for a in winner_apps)):
        raise CorrectionError("both jobs have a live application; end one of them before merging")

    kept = {(s.source_id, s.url): s for s in await session.scalars(
        select(JobSighting).where(JobSighting.job_id == winner.id))}
    moved: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for s in list(await session.scalars(select(JobSighting).where(JobSighting.job_id == dup.id))):
        twin = kept.get((s.source_id, s.url))
        if twin is not None:  # same link already on the kept job: fold the dates in, keep one row
            twin.first_seen_at = min(twin.first_seen_at, s.first_seen_at)
            twin.last_seen_at = max(twin.last_seen_at, s.last_seen_at)
            dropped.append({"url": s.url, "source_id": str(s.source_id) if s.source_id else None})
            await session.delete(s)
        else:
            s.job_id = winner.id
            moved.append({"id": str(s.id), "url": s.url})
    await session.flush()

    contacts = list(await session.scalars(select(Contact).where(Contact.job_id == dup.id)))
    for c in contacts:
        c.job_id = winner.id
    for a in dup_apps:
        a.job_id = winner.id
        await stages.add_event(session, a.id, "job_merged", actor,
                               {"from_job_id": str(dup.id), "into_job_id": str(winner.id)})

    tags_added = [t for t in dup.tags if t not in winner.tags]
    notes_before = winner.notes
    winner.tags = [*winner.tags, *tags_added]
    if dup.notes and dup.notes not in (winner.notes or ""):
        winner.notes = f"{winner.notes}\n\n{dup.notes}" if winner.notes else dup.notes
    triage_before = dup.triage
    dup.merged_into_id = winner.id
    dup.triage = "archived"
    await audit.record(
        session, actor=actor, action="job.merge", subject_type="job", subject_id=winner.id,
        detail={"winner": str(winner.id), "loser": str(dup.id), "sightings": moved, "dropped_sightings": dropped,
                "application_ids": [str(a.id) for a in dup_apps], "contact_ids": [str(c.id) for c in contacts],
                "tags_added": tags_added, "loser_triage": triage_before, "winner_notes_before": notes_before,
                "winner_notes_after": winner.notes})


def _live() -> frozenset[Stage]:
    from app.models.applications import LIVE_STAGES

    return LIVE_STAGES


# ----- split ----------------------------------------------------------------------------------------


@dataclass
class SplitResult:
    job: Job
    restored: bool


async def split_job(session: AsyncSession, job_id: uuid.UUID, sighting_urls: list[str], *,
                    actor: str) -> SplitResult:
    job = await _load_job(session, job_id)
    sightings = list(await session.scalars(select(JobSighting).where(JobSighting.job_id == job.id)))
    chosen = [s for s in sightings if s.url in set(sighting_urls)]
    if not chosen:
        raise CorrectionError("none of those sightings belong to this job", 404)
    if len(chosen) == len(sightings):
        raise CorrectionError("a job must keep at least one sighting; split off only some of them", 422)
    chosen_ids = {str(s.id) for s in chosen}

    revived = await _revive_merged(session, job, chosen_ids, actor)
    if revived is not None:
        await reevaluate_conflicts(session, {job.canonical_employer, revived.canonical_employer})
        return SplitResult(revived, True)

    first = min(chosen, key=lambda s: s.first_seen_at)
    new = Job(
        title=job.title, employer=job.employer, canonical_employer=job.canonical_employer,
        recruiter=job.recruiter, requisition_id=job.requisition_id, function=job.function, level=job.level,
        facets=job.facets, custom_facets=dict(job.custom_facets), tags=list(job.tags), location=job.location,
        pay_state=job.pay_state, pay_min_minor=job.pay_min_minor, pay_max_minor=job.pay_max_minor,
        pay_currency=job.pay_currency, pay_period=job.pay_period, posted_at=job.posted_at,
        deadline_state=job.deadline_state, deadline=job.deadline, apply_url=first.url,
        apply_method=job.apply_method, apply_email=job.apply_email, requirements=list(job.requirements),
        raw_text=job.raw_text, content_hash=job.content_hash, availability=job.availability, triage="new",
        origin="owner", notes=None)
    session.add(new)
    await session.flush()
    for s in chosen:
        s.job_id = new.id
    await session.flush()
    await audit.record(session, actor=actor, action="job.split", subject_type="job", subject_id=job.id,
                       detail={"new_job_id": str(new.id), "sightings": sorted(sighting_urls), "restored": False})
    await reevaluate_conflicts(session, {job.canonical_employer})
    return SplitResult(new, False)


async def _revive_merged(session: AsyncSession, job: Job, chosen_ids: set[str], actor: str) -> Job | None:
    """If these sightings came from a job that was merged away into ``job``, bring that job back."""
    events = await session.scalars(select(AuditEvent).where(
        AuditEvent.action == "job.merge", AuditEvent.subject_id == str(job.id)).order_by(AuditEvent.created_at.desc()))
    for ev in events:
        d = ev.detail
        moved_ids = {s["id"] for s in d.get("sightings", [])}
        if not moved_ids or not chosen_ids >= moved_ids:
            continue
        loser = await session.get(Job, uuid.UUID(d["loser"]))
        if loser is None or loser.merged_into_id != job.id:
            continue
        for s in await session.scalars(select(JobSighting).where(
                JobSighting.id.in_([uuid.UUID(i) for i in moved_ids]))):
            s.job_id = loser.id
        for a in await session.scalars(select(Application).where(
                Application.id.in_([uuid.UUID(i) for i in d.get("application_ids", [])]),
                Application.job_id == job.id)):
            a.job_id = loser.id
            await stages.add_event(session, a.id, "job_split", actor,
                                   {"from_job_id": str(job.id), "back_to_job_id": str(loser.id)})
        for c in await session.scalars(select(Contact).where(
                Contact.id.in_([uuid.UUID(i) for i in d.get("contact_ids", [])]), Contact.job_id == job.id)):
            c.job_id = loser.id
        added = set(d.get("tags_added", []))
        job.tags = [t for t in job.tags if t not in added]
        if job.notes == d.get("winner_notes_after"):
            job.notes = d.get("winner_notes_before")
        loser.merged_into_id = None
        loser.triage = d.get("loser_triage") or "new"
        await session.flush()
        await audit.record(session, actor=actor, action="job.split", subject_type="job", subject_id=job.id,
                           detail={"new_job_id": str(loser.id), "restored": True, "sightings": sorted(moved_ids)})
        return loser
    return None


# ----- fix a wrong employer match -------------------------------------------------------------------


async def fix_employer(session: AsyncSession, job_id: uuid.UUID, canonical: str, *, remember_alias: bool,
                       actor: str) -> list[Job]:
    """Point this job (and every job posted under the same employer name) at ``canonical``."""
    canonical = " ".join(canonical.split())
    if not canonical:
        raise CorrectionError("employer name is required", 422)
    job = await _load_job(session, job_id)
    posted = " ".join(job.employer.split())
    affected = list(await session.scalars(select(Job).where(
        (Job.id == job.id) | (func.lower(Job.employer) == posted.lower()))))
    previous = {j.canonical_employer for j in affected}
    for j in affected:
        j.canonical_employer = canonical
    alias_state = "not remembered"
    if remember_alias and posted.lower() != canonical.lower():
        alias = await session.scalar(select(EmployerAlias).where(func.lower(EmployerAlias.alias) == posted.lower()))
        if alias is None:
            session.add(EmployerAlias(alias=posted, canonical=canonical))
            alias_state = "added"
        else:
            alias.canonical = canonical
            alias_state = "updated"
    await session.flush()
    await audit.record(session, actor=actor, action="job.employer_fixed", subject_type="job", subject_id=job.id,
                       detail={"posted": posted, "from": sorted(previous), "to": canonical, "alias": alias_state,
                               "jobs": [str(j.id) for j in affected]})
    await reevaluate_conflicts(session, {*previous, canonical})
    return affected


async def sightings_of(session: AsyncSession, job_id: uuid.UUID) -> list[JobSighting]:
    return list(await session.scalars(select(JobSighting).where(JobSighting.job_id == job_id)
                                      .order_by(JobSighting.first_seen_at)))


__all__ = [
    "AppliedMyself", "CorrectionError", "MergeResult", "SplitResult", "canonical_employer",
    "create_job", "find_existing_job", "fix_employer", "log_applied_myself", "merge_jobs",
    "set_conflict_reevaluator", "sightings_of", "split_job",
]
