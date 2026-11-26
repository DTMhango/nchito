"""Manual capture (DESIGN.md 6): persist a pasted link or posting text as a Job stub.

``capture`` persists the stub synchronously and fetches nothing: the stub carries the raw input,
the tag ``captured`` and ``availability=unknown``. ``process_capture`` (run by the worker task
``process_capture``) then reads the link (the right connector for a known board, else the page),
normalises it through the same stages as any source (parse, dedupe, one model call, rule tags)
and either fills the stub in place or, when it is a job already known, merges it into that job.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.models.search import Availability, Job, JobSighting, Source
from app.pipeline import dedupe, normalise
from app.schemas.json_types import RateLimit
from app.sources.base import RawJob, SourceError
from app.sources.detect import detect_from_url

CAPTURED_TAG = "captured"
UNKNOWN_EMPLOYER = "Unknown employer"


class CaptureError(ValueError):
    pass


def _clean_url(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise CaptureError("The link must start with http:// or https://.")
    return url


async def capture(session: AsyncSession, url: str | None, text: str | None) -> Job:
    clean_url = _clean_url(url)
    clean_text = text.strip() if text and text.strip() else None
    if clean_url is None and clean_text is None:
        raise CaptureError("Paste a link or the posting text.")
    first_line = (clean_text or "").splitlines()[0][:300] if clean_text else ""
    title = first_line or (urlsplit(clean_url).netloc if clean_url else "Captured posting")
    digest = hashlib.sha256(f"{clean_url or ''}\n{clean_text or ''}".encode()).hexdigest()
    job = Job(
        title=title,
        employer=UNKNOWN_EMPLOYER,
        canonical_employer=UNKNOWN_EMPLOYER,
        apply_url=clean_url,
        raw_text=clean_text,
        content_hash=digest,
        availability=Availability.unknown,
        tags=[CAPTURED_TAG],
    )
    session.add(job)
    await session.flush()
    if clean_url:
        now = utcnow()
        session.add(JobSighting(job_id=job.id, source_id=None, url=clean_url, first_seen_at=now, last_seen_at=now))
        await session.flush()
    return job


@dataclass
class CaptureResult:
    job: Job
    merged_into: Job | None = None
    fetched: bool = False
    error: str | None = None


def _pasted_raw(job: Job) -> RawJob:
    text = job.raw_text or ""
    return RawJob(source_url=job.apply_url or "", title=job.title, employer=job.employer, raw_text=text,
                  apply_url=job.apply_url)


async def _fetch_link(url: str) -> RawJob:
    """Read a pasted link with the connector for its board type, else as a plain page."""
    from app.pipeline.orchestrator import DEPS

    detected = detect_from_url(url)
    connector = detected.connector if detected.connector in ("greenhouse", "lever", "ashby", "workable",
                                                              "workday") else "manual"
    owner = Source(connector=connector, name=connector, rate_limit=RateLimit())
    conn = DEPS.connector_for(owner)
    try:
        return await conn.fetch(url)
    except SourceError:
        if connector == "manual":
            raise
        page = Source(connector="manual", name="manual", rate_limit=RateLimit())
        return await DEPS.connector_for(page).fetch(url)


async def process_capture(session: AsyncSession, job_id: uuid.UUID) -> CaptureResult | None:
    """Run a captured stub through the pipeline. Safe to call again for the same stub."""
    from app.pipeline.orchestrator import DEPS

    job = await session.get(Job, job_id)
    if job is None or CAPTURED_TAG not in job.tags or job.merged_into_id is not None:
        return None
    error: str | None = None
    fetched = False
    if job.raw_text:
        raw = _pasted_raw(job)
    elif job.apply_url:
        try:
            raw = await _fetch_link(job.apply_url)
            fetched = True
        except Exception as exc:  # the link may be blocked or not a posting
            error = f"{type(exc).__name__}: {exc}"[:300]
            if normalise.PENDING_TAG not in job.tags:
                job.tags = [*job.tags, normalise.PENDING_TAG]
            await session.flush()
            return CaptureResult(job, error=error)
    else:
        return CaptureResult(job, error="nothing to read")

    now = DEPS.clock.now()
    threshold = await settings_service.get_value(session, "matching.dedupe_similarity")
    norm = await normalise.parse_with_aliases(session, raw)
    llm = await DEPS.llm_factory(session, None) if DEPS.llm_factory else None
    extraction = await normalise.extract(session, llm, norm) if llm is not None else None
    if extraction and extraction.out is not None:
        employer, title = normalise.identity_from(extraction.out, norm.raw_text)
        if employer and norm.employer == UNKNOWN_EMPLOYER:
            norm.employer = employer
            norm.canonical_employer = await dedupe.canonical_employer(session, employer)
        if title and norm.title == job.title:
            norm.title = title
        norm.content_hash = dedupe.content_hash(norm.canonical_employer, norm.title, norm.raw_text)

    match = await dedupe.find_match(session, norm, source_id=None, threshold=threshold, exclude=job.id)
    if match is not None:
        await dedupe.register(session, norm, source_id=None, now=now, threshold=threshold)
        job.merged_into_id = match.id
        job.triage = "archived"
        await audit.record(session, actor="system", action="job.capture_merged", subject_type="job",
                           subject_id=job.id, detail={"into": str(match.id)})
        await publish(session, "job.updated", {"job_id": str(match.id)})
        return CaptureResult(match, merged_into=match, fetched=fetched)

    fresh = norm.to_job(now)
    for attr in ("title", "employer", "canonical_employer", "requisition_id", "location", "pay_state",
                 "pay_min_minor", "pay_max_minor", "pay_currency", "pay_period", "posted_at", "deadline_state",
                 "deadline", "apply_url", "apply_method", "apply_email", "raw_text", "content_hash"):
        setattr(job, attr, getattr(fresh, attr))
    if extraction and extraction.out is not None:
        normalise.apply_extraction(job, extraction.out, await normalise.load_skill_aliases(session))
    elif llm is None and normalise.PENDING_TAG not in job.tags:
        job.tags = [*job.tags, normalise.PENDING_TAG]
    normalise.apply_tag_rules(job, await normalise.load_tag_rules(session))
    if norm.source_url:
        await dedupe.touch_sighting(session, job, None, norm.source_url, now)
    await publish(session, "job.updated", {"job_id": str(job.id)})
    await session.flush()
    return CaptureResult(job, fetched=fetched, error=error)


__all__ = ["CAPTURED_TAG", "CaptureError", "CaptureResult", "capture", "process_capture"]
