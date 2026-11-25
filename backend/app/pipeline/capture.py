"""Manual capture (DESIGN.md 6): persist a pasted link or posting text as a Job stub.

The stub is untrusted data: nothing is fetched or parsed here. Wave 1 (sources stream)
normalises captured stubs through the same pipeline as any source (fetch the URL, extract,
dedupe, filter, score). Until then the stub carries the raw input, the tag ``captured`` and
``availability=unknown``.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.search import Availability, Job, JobSighting

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
