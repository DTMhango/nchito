"""Recheck one job on demand (DESIGN.md 6): re-read it through its source, update availability,
and reassess when the posting itself changed in a material way.

A failed check is ``unknown``, never ``closed``. A failed fetch changes nothing about the content.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import publish
from app.llm.client import LLMClient
from app.models.search import Availability, Job, JobSighting, Source
from app.pipeline import conflicts, normalise, orchestrator
from app.schemas.json_types import RateLimit
from app.sources.base import RawJob

# Fields compared to decide whether the posting changed in a way that can alter the verdict.
MATERIAL_FIELDS = ("title", "raw_text", "deadline", "deadline_state", "pay_state", "pay_min_minor", "pay_max_minor",
                   "pay_currency", "apply_url", "location")


@dataclass
class RecheckResult:
    availability_before: str
    availability_after: str
    content_changed: bool = False
    changed_fields: list[str] = field(default_factory=list)
    reassessed: bool = False
    fetched: bool = False
    note: str | None = None


async def _connector_for(session: AsyncSession, job: Job, deps: orchestrator.IntakeDeps):
    row = (await session.execute(
        select(JobSighting, Source).outerjoin(Source, Source.id == JobSighting.source_id)
        .where(JobSighting.job_id == job.id).order_by(JobSighting.last_seen_at.desc()).limit(1))).first()
    if row is None:
        return None, None
    sighting, source = row
    if source is not None and "fetch" not in (source.permitted_actions or []):
        return sighting.url, None
    owner = source if source is not None else Source(connector="manual", name="manual", rate_limit=RateLimit())
    return sighting.url, deps.connector_for(owner)


async def _fetch(session: AsyncSession, job: Job, deps: orchestrator.IntakeDeps) -> RawJob | None:
    url, conn = await _connector_for(session, job, deps)
    if conn is None or url is None:
        return None
    try:
        return await asyncio.wait_for(conn.fetch(url), timeout=deps.source_timeout_seconds)
    except Exception:
        return None


def _differences(job: Job, fresh: Job) -> list[str]:
    changed = []
    for name in MATERIAL_FIELDS:
        if name == "raw_text":
            # A much shorter text is an excerpt, not a rewrite (same rule as a sweep).
            old_words, new_words = len((job.raw_text or "").split()), len((fresh.raw_text or "").split())
            if new_words and new_words * 2 < old_words:
                continue
        if getattr(job, name) != getattr(fresh, name):
            changed.append(name)
    return changed


async def recheck_job(session: AsyncSession, job: Job, *, actor: str, deps: orchestrator.IntakeDeps | None = None,
                      llm: LLMClient | None = None) -> RecheckResult:
    deps = deps or orchestrator.DEPS
    before = job.availability
    after = await orchestrator.check_job_open(session, job, deps)
    result = RecheckResult(availability_before=before.value, availability_after=after.value)

    if after != Availability.closed:
        raw = await _fetch(session, job, deps)
        if raw is None:
            result.note = "the posting could not be read again; content left as it was"
        else:
            result.fetched = True
            norm = await normalise.parse_with_aliases(session, raw)
            fresh = norm.to_job(deps.clock.now())
            changed = _differences(job, fresh)
            if changed:
                result.content_changed, result.changed_fields = True, changed
                for attr in ("title", "requisition_id", "location", "pay_state", "pay_min_minor", "pay_max_minor",
                             "pay_currency", "pay_period", "posted_at", "deadline_state", "deadline", "apply_url",
                             "apply_method", "apply_email", "raw_text", "content_hash"):
                    setattr(job, attr, getattr(fresh, attr))
                await _reextract_and_reassess(session, job, norm, llm, deps, result)

    if before != job.availability and job.availability == Availability.closed:
        await conflicts.on_job_changed(session, job)
    await audit.record(session, actor=actor, action="job.rechecked", subject_type="job", subject_id=job.id,
                       detail={"availability": [result.availability_before, result.availability_after],
                               "changed_fields": result.changed_fields, "reassessed": result.reassessed})
    await publish(session, "job.updated", {"job_id": str(job.id)})
    await session.flush()
    return result


async def _reextract_and_reassess(session: AsyncSession, job: Job, norm: Any, llm: LLMClient | None,
                                  deps: orchestrator.IntakeDeps, result: RecheckResult) -> None:
    from app.pipeline import scoring

    extraction = await normalise.extract(session, llm, norm) if llm is not None else None
    if extraction is not None and extraction.out is not None:
        normalise.apply_extraction(job, extraction.out, await normalise.load_skill_aliases(session))
    elif normalise.PENDING_TAG not in job.tags:
        job.tags = [*job.tags, normalise.PENDING_TAG]  # extraction owed; a later sweep or rescore finishes it
    normalise.apply_tag_rules(job, await normalise.load_tag_rules(session))
    await session.flush()
    summary = await scoring.score_jobs(session, None, [job.id], client=llm, paid=llm is not None)
    result.reassessed = bool(summary.scored or summary.cached or summary.filtered_out or summary.parked)
