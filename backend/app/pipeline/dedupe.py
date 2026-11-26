"""De-duplication (DESIGN.md 6, "Pipeline rules").

One ``Job``, many ``JobSighting`` rows. A posting matches an existing job by, in order:

1. a sighting of the same URL from the same source;
2. requisition id for the same canonical employer;
3. canonical employer (through ``EmployerAlias``) + normalised title + compatible location +
   content similarity at or above ``matching.dedupe_similarity``.

A job the owner applied to, skipped or archived never re-enters as new (``suppressed``). A
matched job whose text changed materially (similarity below the threshold) is flagged with the
``reposted`` tag for review; it is not duplicated.
"""

from __future__ import annotations

import enum
import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.search import EmployerAlias, Job, JobSighting
from app.schemas.json_types import StructuredLocation

if TYPE_CHECKING:
    from app.pipeline.normalise import NormalisedJob

REPOSTED_TAG = "reposted"
SUPPRESSED_TRIAGE = ("skipped", "archived")
_LEGAL_SUFFIX = re.compile(
    r"[\s,]+(inc|incorporated|llc|ltd|limited|plc|corp|corporation|gmbh|co|company|sa|pty|bv|ag)\.?$",
                           re.I)
_NOISE_IN_TITLE = re.compile(r"\((?:[^)]*)\)|\[(?:[^\]]*)\]|\b(?:m/f/d|f/m/d|m/w/d|remote|hybrid|urgent)\b", re.I)
_SHINGLE = 3
MIN_WORDS_FOR_TEXT_MATCH = 3
EXCERPT_RATIO = 0.5  # new text shorter than this share of the old is an excerpt, not a rewrite


class Outcome(enum.StrEnum):
    new = "new"
    seen = "seen"  # known job, seen again
    suppressed = "suppressed"  # applied to, skipped or archived: never re-enters as new
    reposted = "reposted"  # known job whose text changed materially


@dataclass
class Dedupe:
    job: Job
    outcome: Outcome
    flagged_repost: bool = False


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def clean_employer(name: str) -> str:
    """Display form: collapsed whitespace, trailing legal suffix removed."""
    out = re.sub(r"\s+", " ", name or "").strip()
    stripped = _LEGAL_SUFFIX.sub("", out).strip(" ,")
    return stripped or out


def employer_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _ascii(clean_employer(name)).lower()).strip()


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _ascii(_NOISE_IN_TITLE.sub(" ", title)).lower()).strip()


def content_hash(employer: str, title: str, text: str) -> str:
    body = re.sub(r"\s+", " ", text or "").strip().lower()
    return hashlib.sha256(f"{employer_key(employer)}|{title_key(title)}|{body}".encode()).hexdigest()


def shingles(text: str | None) -> set[int]:
    words = re.sub(r"[^a-z0-9]+", " ", _ascii(text or "").lower()).split()
    if len(words) < _SHINGLE:
        return {hash(" ".join(words))} if words else set()
    return {hash(" ".join(words[i:i + _SHINGLE])) for i in range(len(words) - _SHINGLE + 1)}


def similarity(a: str | None, b: str | None) -> float:
    """Best of Jaccard and containment, so an excerpt of a posting matches the full posting."""
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 1.0 if not (sa or sb) else 0.0
    inter = len(sa & sb)
    return max(inter / len(sa | sb), inter / min(len(sa), len(sb)))


def _loc_tokens(loc: StructuredLocation) -> set[str]:
    return {t for t in (employer_key(x) for x in (loc.city, loc.country, loc.region) if x) if t}


def locations_compatible(a: StructuredLocation, b: StructuredLocation) -> bool:
    """Unknown on either side is compatible; two known places must share a token."""
    ta, tb = _loc_tokens(a), _loc_tokens(b)
    if not ta or not tb:
        ra, rb = employer_key(a.raw or ""), employer_key(b.raw or "")
        return not ra or not rb or ra == rb or ra in rb or rb in ra
    return bool(ta & tb)


async def canonical_employer(session: AsyncSession, name: str) -> str:
    """The canonical employer through ``EmployerAlias`` (case-insensitive), else the cleaned name."""
    cleaned = clean_employer(name) or name
    found = await session.scalar(select(EmployerAlias.canonical).where(
        func.lower(EmployerAlias.alias).in_([name.strip().lower(), cleaned.lower()])).limit(1))
    return found or cleaned


async def _blocked(session: AsyncSession, job: Job) -> bool:
    if job.triage in SUPPRESSED_TRIAGE:
        return True
    return await session.scalar(select(Application.id).where(Application.job_id == job.id).limit(1)) is not None


async def find_match(session: AsyncSession, norm: NormalisedJob, *, source_id: object, threshold: float,
                     exclude: object = None) -> Job | None:
    """The existing job this posting is, or ``None``. Read-only. ``exclude`` skips one job (a captured stub)."""
    skip = [Job.id != exclude] if exclude is not None else []
    sighted = await session.scalar(
        select(Job).join(JobSighting, JobSighting.job_id == Job.id)
        .where(JobSighting.url == norm.source_url, JobSighting.source_id == source_id,
               Job.merged_into_id.is_(None), *skip)
        .limit(1))
    if sighted is not None:
        return sighted
    same_employer = select(Job).where(func.lower(Job.canonical_employer) == norm.canonical_employer.lower(),
                                      Job.merged_into_id.is_(None), *skip)
    if norm.requisition_id:
        by_req = await session.scalar(same_employer.where(Job.requisition_id == norm.requisition_id)
                                      .order_by(Job.created_at).limit(1))
        if by_req is not None:
            return by_req
    wanted = title_key(norm.title)
    if not wanted:
        return None
    candidates: Iterable[Job] = (await session.scalars(same_employer.order_by(Job.created_at))).all()
    for job in candidates:
        if norm.requisition_id and job.requisition_id and norm.requisition_id != job.requisition_id:
            continue  # two known, different requisition ids are two roles
        if title_key(job.title) != wanted or not locations_compatible(job.location, norm.location):
            continue
        words = min(len((job.raw_text or "").split()), len(norm.raw_text.split()))
        if words < MIN_WORDS_FOR_TEXT_MATCH or similarity(job.raw_text, norm.raw_text) >= threshold:
            return job
    return None


async def touch_sighting(session: AsyncSession, job: Job, source_id: object, url: str, now: datetime) -> None:
    sighting = await session.scalar(select(JobSighting).where(
        JobSighting.job_id == job.id, JobSighting.source_id == source_id, JobSighting.url == url))
    if sighting is None:
        session.add(JobSighting(job_id=job.id, source_id=source_id, url=url, first_seen_at=now, last_seen_at=now))
    else:
        sighting.last_seen_at = now
    await session.flush()


async def register(session: AsyncSession, norm: NormalisedJob, *, source_id: object, now: datetime,
                   threshold: float) -> Dedupe:
    """Match ``norm`` to an existing job or create it. Always records a sighting. Writes."""
    job = await find_match(session, norm, source_id=source_id, threshold=threshold)
    if job is None:
        job = norm.to_job(now)
        session.add(job)
        await session.flush()
        await touch_sighting(session, job, source_id, norm.source_url, now)
        return Dedupe(job, Outcome.new)

    await touch_sighting(session, job, source_id, norm.source_url, now)
    old_words = len((job.raw_text or "").split())
    new_words = len(norm.raw_text.split())
    # A much shorter text is an excerpt from another source, not a rewrite.
    comparable = old_words > 0 and new_words >= old_words * EXCERPT_RATIO
    changed = comparable and similarity(job.raw_text, norm.raw_text) < threshold
    if changed and REPOSTED_TAG not in job.tags:
        job.tags = [*job.tags, REPOSTED_TAG]
    if job.raw_text and (changed or (comparable and job.content_hash != norm.content_hash)):
        job.raw_text = norm.raw_text
        job.content_hash = norm.content_hash
    if await _blocked(session, job):
        return Dedupe(job, Outcome.suppressed, flagged_repost=changed)
    return Dedupe(job, Outcome.reposted if changed else Outcome.seen, flagged_repost=changed)
