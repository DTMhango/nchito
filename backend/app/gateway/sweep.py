"""``report_jobs``: postings a runner found on a sweep task, fed to intake as untrusted raw jobs (DESIGN.md
6, 8.3). Invariants: the text is data (bounded, never followed); a posting whose visited URL is off the
task's site is dropped and audited; each posting goes through the normal parse and dedupe with the task's
source, and new jobs wait for model extraction like any other (``normalise.PENDING_TAG``)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import packets
from app.core import audit
from app.gateway.common import GatewayError, clip, own_task, require_active, require_scope, same_site, setting
from app.gateway.tasks import give_back, is_dry_run
from app.gateway.tools import ReportJobsIn, ReportJobsOut
from app.models.applications import AgentTaskType
from app.models.platform import ApiToken
from app.pipeline import dedupe, normalise
from app.sources.base import RawJob

MAX_JOBS = 200


async def report_jobs(session: AsyncSession, token: ApiToken, body: ReportJobsIn, *, at: datetime) -> ReportJobsOut:
    require_active(token)
    require_scope(token, "gateway:sweep")
    task = await own_task(session, token, body.task_id, at=at, types=(AgentTaskType.sweep_site,))
    if is_dry_run(task):
        await give_back(session, task, reason="dry run finished", actor=f"runner:{token.name}", at=at)
        return ReportJobsOut(accepted=0, duplicates=0)
    raw_source = task.payload.get("source_id")
    if not raw_source:
        raise GatewayError("no_source", "this sweep task names no source")
    source_id = uuid.UUID(str(raw_source))
    site = str(task.payload.get("domain") or "")
    threshold = float(await setting(session, "matching.dedupe_similarity"))
    accepted = duplicates = 0
    dropped: list[str] = []
    for item in body.jobs[:MAX_JOBS]:
        url = clip(item.url_visited, 2000) or ""
        if not same_site(packets.domain_of(url), site):
            dropped.append(url[:200])
            continue
        raw = RawJob(source_url=url, title=clip(item.title, 300) or "", employer=clip(item.employer, 200) or "",
                     raw_text=clip(item.snippet, 20_000) or "", apply_url=url, location_raw=clip(item.location, 200),
                     extra={"reported_by": token.name, "agent_task_id": str(task.id)})
        if not raw.title.strip() or not raw.employer.strip():
            dropped.append(url[:200])
            continue
        norm = await normalise.parse_with_aliases(session, raw)
        result = await dedupe.register(session, norm, source_id=source_id, now=at, threshold=threshold)
        if result.outcome == dedupe.Outcome.new:
            accepted += 1
            if normalise.PENDING_TAG not in result.job.tags:
                result.job.tags = [*result.job.tags, normalise.PENDING_TAG]
        else:
            duplicates += 1
    task.result = {"outcome": "reported", "accepted": accepted, "duplicates": duplicates, "dropped": len(dropped)}
    await audit.record(session, actor=f"runner:{token.name}", action="gateway.jobs_reported", subject_type="agent_task",
                       subject_id=task.id, detail={**task.result, "dropped_urls": dropped[:20]})
    return ReportJobsOut(accepted=accepted, duplicates=duplicates)
