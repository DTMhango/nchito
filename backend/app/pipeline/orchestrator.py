"""Discovery orchestrator: the sweep run, the expiry recheck and the retention run.

A sweep is one run per campaign (DESIGN.md 6, 14):

    sources (parallel, isolated) -> dedupe -> normalise (+ rule tags) -> ``score_jobs`` hook

- **Incremental window:** since the campaign's last successful sweep minus ``schedule.overlap_days``.
  The checkpoint moves only when every source succeeded; a failed or partial sweep leaves it.
- **Isolation:** one source failing (error, timeout, unknown connector) is recorded in
  ``run.source_results`` and never fails the others.
- **Overlap:** a sweep for a campaign that already has a running sweep is ``skipped``; overlapping
  windows are deduplicated by the dedupe stage, so re-reading postings is harmless.
- **Dry run:** reads, matches and counts; writes no jobs, spends nothing, moves no checkpoint.
- **Hand-off:** new and materially changed jobs go to the scoring stream through ``score_jobs``,
  a registered hook (no-op until scoring registers itself).
- Progress is published as ``run.progress`` events (ids and counts only).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import Clock, SystemClock
from app.core.events import publish
from app.core.settings import service as settings_service
from app.llm.client import LLMClient
from app.models.applications import Application
from app.models.search import (
    Availability,
    Campaign,
    CampaignStatus,
    Job,
    JobSighting,
    Run,
    RunKind,
    RunStatus,
    Source,
    WatchedEmployer,
)
from app.pipeline import dedupe, normalise
from app.pipeline.runs import handler_for, register
from app.schemas.json_types import RateLimit, SourceHealth, SourceRunResult
from app.sources.base import RawJob, SearchContext, SourceConnector
from app.sources.http import HttpxFetcher
from app.sources.registry import build_connector, effective_config

log = logging.getLogger(__name__)

SourceFactory = Callable[[Source], SourceConnector]
LlmFactory = Callable[[AsyncSession], Awaitable[LLMClient | None]]
ScoreHook = Callable[[Run, list[uuid.UUID]], Awaitable[None]]

STAGE_KEYS = ("found", "new", "passed_filters", "above_threshold", "tailored", "applied")  # Runs screen
MAX_PROPOSED = 200
FAILING_AFTER = 3  # consecutive failures before a source's health reads "failing"


@dataclass
class IntakeDeps:
    """Everything the intake stages need from outside; replaced in tests."""

    transport: HttpxFetcher | None = None
    source_factory: SourceFactory | None = None
    llm_factory: LlmFactory | None = None
    clock: Clock = field(default_factory=SystemClock)
    source_timeout_seconds: float = 300.0

    def connector_for(self, source: Source) -> SourceConnector:
        if self.source_factory is not None:
            return self.source_factory(source)
        if self.transport is None:
            self.transport = HttpxFetcher()
        return build_connector(source, self.transport)


DEPS = IntakeDeps()


def configure(**overrides: Any) -> None:
    for key, value in overrides.items():
        setattr(DEPS, key, value)


def reset_deps() -> None:
    global DEPS
    DEPS = IntakeDeps()


# ----- scoring hand-off ---------------------------------------------------------------------


async def _no_scoring(run: Run, job_ids: list[uuid.UUID]) -> None:
    return None


_score_hook: ScoreHook = _no_scoring


def register_score_hook(hook: ScoreHook) -> None:
    """The scoring stream registers ``score_jobs(run, job_ids)`` here. Last registration wins."""
    global _score_hook
    _score_hook = hook


def reset_score_hook() -> None:
    register_score_hook(_no_scoring)


# ----- helpers -------------------------------------------------------------------------------


@dataclass
class _Found:
    source: Source
    jobs: list[RawJob] | None
    error: str | None
    warnings: list[str]


async def _cancelled(session: AsyncSession, run: Run) -> bool:
    await session.refresh(run, ["status"])
    return run.status == RunStatus.cancelled


async def _progress(session: AsyncSession, run: Run, stage: str, counts: Counter[str]) -> None:
    run.counts = dict(counts)
    await publish(session, "run.progress", {"run_id": str(run.id), "stage": stage, "counts": dict(counts)})
    await session.commit()


async def _sources_for(session: AsyncSession, campaign: Campaign) -> list[Source]:
    query = select(Source).where(Source.enabled.is_(True)).order_by(Source.created_at)
    if campaign.source_ids:
        query = query.where(Source.id.in_(campaign.source_ids))
    return [s for s in (await session.scalars(query)).all() if "search" in (s.permitted_actions or [])]


def _context(campaign: Campaign, config: dict[str, Any]) -> SearchContext:
    crit = campaign.criteria
    return SearchContext(campaign_id=str(campaign.id), titles=list(crit.titles), keywords=list(crit.keywords),
                         locations=[loc.place for loc in crit.locations if loc.kind != "deny"], source_config=config)


async def _search_one(source: Source, config: dict[str, Any], campaign: Campaign, since: datetime | None,
                      deps: IntakeDeps) -> _Found:
    connector: SourceConnector | None = None
    try:
        connector = deps.connector_for(source)
        config = connector.validate_config(config) if source.connector != "manual" else config
        jobs = await asyncio.wait_for(connector.search(_context(campaign, config), since),
                                      timeout=deps.source_timeout_seconds)
        return _Found(source, jobs, None, list(getattr(connector, "warnings", [])))
    except TimeoutError:
        return _Found(source, None, f"timed out after {deps.source_timeout_seconds:.0f}s", [])
    except Exception as exc:  # isolation: nothing a source does may fail the run
        return _Found(source, None, f"{type(exc).__name__}: {exc}"[:500], list(getattr(connector, "warnings", [])))


def _record_health(source: Source, found: _Found, now: datetime) -> None:
    health = source.health
    if found.error is None:
        source.last_success_at = now
        source.health = SourceHealth(status="degraded" if found.warnings else "ok", consecutive_failures=0,
                                     last_error="; ".join(found.warnings)[:500] or None)
    else:
        failures = health.consecutive_failures + 1
        source.health = SourceHealth(status="failing" if failures >= FAILING_AFTER else "degraded",
                                     consecutive_failures=failures, last_error=found.error)


def _valid(raw: RawJob) -> bool:
    return bool(raw.title and raw.title.strip() and raw.source_url and raw.raw_text is not None)


# ----- the sweep -----------------------------------------------------------------------------


async def run_sweep(session: AsyncSession, run: Run, deps: IntakeDeps | None = None) -> RunStatus:
    deps = deps or DEPS
    started = deps.clock.now()
    campaign = await session.get(Campaign, run.campaign_id) if run.campaign_id else None
    if campaign is None:
        run.error = "a sweep needs a campaign"
        return RunStatus.failed
    if campaign.status != CampaignStatus.active and run.trigger != "manual":
        run.error = f"campaign is {campaign.status.value}"
        return RunStatus.skipped
    await session.refresh(campaign, ["updated_at"])
    running = await session.scalar(select(Run.id).where(
        Run.kind == RunKind.sweep, Run.campaign_id == campaign.id, Run.status == RunStatus.running,
        Run.id != run.id).limit(1))
    if running is not None:
        run.error = "another sweep for this campaign is already running"
        return RunStatus.skipped

    states = await settings_service.get_all(session)
    overlap_days: int = states["schedule.overlap_days"].value
    threshold: float = states["matching.dedupe_similarity"].value
    model: str = states["ai.model_extract"].value
    since = campaign.last_sweep_checkpoint - timedelta(days=overlap_days) if campaign.last_sweep_checkpoint else None
    tag_rules = await normalise.load_tag_rules(session)
    run.config_versions = {
        "settings": {k: states[k].version for k in ("schedule.overlap_days", "matching.dedupe_similarity",
                                                     "ai.model_extract")},
        "prompt_extract": normalise.PROMPT_VERSION, "model_extract": model,
        "since": since.isoformat() if since else None,
        "campaign_updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        "tag_rules": len(tag_rules)}

    sources = await _sources_for(session, campaign)
    if not sources:
        run.error = "no enabled sources allow search for this campaign"
        return RunStatus.failed
    watched = list((await session.scalars(select(WatchedEmployer))).all())
    counts: Counter[str] = Counter({k: 0 for k in STAGE_KEYS})
    proposed: list[dict[str, Any]] = []
    await _progress(session, run, "search", counts)

    found = await asyncio.gather(*[
        _search_one(s, effective_config(s, watched), campaign, since, deps) for s in sources])
    if await _cancelled(session, run):
        return RunStatus.cancelled

    llm = None if run.dry_run or deps.llm_factory is None else await deps.llm_factory(session)
    aliases = await normalise.load_skill_aliases(session)
    handoff: list[uuid.UUID] = []
    results: list[SourceRunResult] = []
    cost = 0
    for item in found:
        source = item.source
        if item.jobs is None:
            results.append(SourceRunResult(source_id=str(source.id), status="failed", error=item.error))
            counts["sources_failed"] += 1
            if not run.dry_run:
                _record_health(source, item, started)
            continue
        new_here = 0
        for raw in item.jobs:
            counts["found"] += 1
            if not _valid(raw):
                counts["invalid"] += 1
                continue
            norm = await normalise.parse_with_aliases(session, raw)
            if run.dry_run:
                match = await dedupe.find_match(session, norm, source_id=source.id, threshold=threshold)
                counts["new" if match is None else "duplicate"] += 1
                new_here += match is None
                if len(proposed) < MAX_PROPOSED:
                    proposed.append({
                        "job_id": str(match.id) if match else None, "title": norm.title, "employer": norm.employer,
                        "action": "add_to_matches" if match is None else "skip",
                        "reason": "New posting: not seen before." if match is None else "Already known."})
                continue
            result = await dedupe.register(session, norm, source_id=source.id, now=started, threshold=threshold)
            counts[result.outcome.value] += 1
            job = result.job
            if result.outcome == dedupe.Outcome.new:
                new_here += 1
            if result.flagged_repost:
                await audit.record(session, actor="system", action="job.reposted_changed", subject_type="job",
                                   subject_id=job.id, detail={"run_id": str(run.id)})
            if result.outcome == dedupe.Outcome.suppressed:
                continue
            needs_model = result.outcome in (dedupe.Outcome.new, dedupe.Outcome.reposted) \
                or normalise.PENDING_TAG in job.tags
            if needs_model:
                if llm is None:
                    counts["extract_skipped"] += 1
                    if normalise.PENDING_TAG not in job.tags:
                        job.tags = [*job.tags, normalise.PENDING_TAG]
                else:
                    extraction = await normalise.extract(session, llm, norm)
                    if extraction.out is None:
                        counts["extract_skipped"] += 1
                        if normalise.PENDING_TAG not in job.tags:
                            job.tags = [*job.tags, normalise.PENDING_TAG]
                    else:
                        normalise.apply_extraction(job, extraction.out, aliases)
                        counts["extract_cached" if extraction.cached else "extracted"] += 1
                        if extraction.usage:
                            cost += extraction.usage.cost_minor
                counts["tagged"] += len(normalise.apply_tag_rules(job, tag_rules))
            if needs_model or result.outcome == dedupe.Outcome.new:
                handoff.append(job.id)
                await publish(session, "job.created" if result.outcome == dedupe.Outcome.new else "job.updated",
                              {"job_id": str(job.id)})
        results.append(SourceRunResult(source_id=str(source.id), status="ok", found=len(item.jobs), new=new_here,
                                       error="; ".join(item.warnings)[:500] or None))
        if not run.dry_run:
            _record_health(source, item, started)
        run.source_results = list(results)
        run.cost_minor = cost
        await _progress(session, run, f"source:{source.name}", counts)
        if await _cancelled(session, run):
            return RunStatus.cancelled

    failed = sum(r.status == "failed" for r in results)
    status = RunStatus.failed if failed == len(results) else RunStatus.partial if failed else RunStatus.succeeded
    run.source_results = results
    run.cost_minor = cost
    counts["handed_to_scoring"] = 0 if run.dry_run else len(handoff)
    run.counts = dict(counts)
    if run.dry_run:
        run.config_versions = {**run.config_versions, "proposed_actions": proposed}
    if failed:
        run.error = "; ".join(f"{r.source_id}: {r.error}" for r in results if r.status == "failed")[:2000]
    if status == RunStatus.succeeded and not run.dry_run:
        campaign.last_sweep_checkpoint = started  # moves only on full success
    await publish(session, "run.progress", {"run_id": str(run.id), "stage": "done", "counts": dict(counts)})
    await session.commit()

    if handoff and not run.dry_run:
        try:
            await _score_hook(run, list(dict.fromkeys(handoff)))
        except Exception as exc:  # intake is saved; scoring can be re-run from the Matches screen
            log.exception("score_jobs hook failed for run %s", run.id)
            run.error = ((run.error + "; ") if run.error else "") + f"scoring hand-off failed: {exc}"[:500]
    return status


# ----- expiry recheck ------------------------------------------------------------------------

CLOSED_OUT_TRIAGE = ("archived", "skipped")


async def check_job_open(session: AsyncSession, job: Job, deps: IntakeDeps | None = None, *,
                         write: bool = True) -> Availability:
    """Ask the job's source whether it is still open. A failed check is ``unknown``, never ``closed``.

    Also used before tailoring and before submitting (DESIGN.md 6). With ``write`` the job's
    availability and ``last_checked_at`` are updated: ``unknown`` never refreshes ``last_checked_at``,
    because nothing was confirmed.
    """
    deps = deps or DEPS
    sighting = (await session.execute(
        select(JobSighting, Source).outerjoin(Source, Source.id == JobSighting.source_id)
        .where(JobSighting.job_id == job.id).order_by(JobSighting.last_seen_at.desc()).limit(1))).first()
    result: Availability = Availability.unknown
    if sighting is not None:
        sight, source = sighting
        try:
            if source is not None and "check_open" not in (source.permitted_actions or []):
                answer = "unknown"
            else:
                owner = source if source is not None else Source(connector="manual", name="manual",
                                                                 rate_limit=RateLimit())
                answer = await asyncio.wait_for(deps.connector_for(owner).check_open(sight.url),
                                                timeout=deps.source_timeout_seconds)
            result = Availability(answer)
        except Exception:
            result = Availability.unknown
    if write:
        job.availability = result
        if result != Availability.unknown:
            job.last_checked_at = deps.clock.now()
    return result


async def run_expiry_check(session: AsyncSession, run: Run, deps: IntakeDeps | None = None) -> RunStatus:
    deps = deps or DEPS
    batch: int = await settings_service.get_value(session, "schedule.expiry_check_batch")
    jobs = (await session.scalars(
        select(Job).where(Job.availability.in_([Availability.open, Availability.unknown]),
                          Job.triage.not_in(CLOSED_OUT_TRIAGE), Job.merged_into_id.is_(None),
                          ~Job.id.in_(select(Application.job_id).where(Application.applied_at.is_not(None))))
        .order_by(Job.last_checked_at.asc().nulls_first(), Job.created_at).limit(batch))).all()
    counts: Counter[str] = Counter()
    for job in jobs:
        if await _cancelled(session, run):
            return RunStatus.cancelled
        answer = await check_job_open(session, job, deps, write=not run.dry_run)
        counts["checked"] += 1
        counts[answer.value] += 1
        if answer == Availability.closed and not run.dry_run:
            await publish(session, "job.updated", {"job_id": str(job.id)})
    run.counts = dict(counts)
    await session.commit()
    return RunStatus.succeeded


# ----- retention -----------------------------------------------------------------------------


async def run_retention(session: AsyncSession, run: Run, deps: IntakeDeps | None = None) -> RunStatus:
    """DESIGN.md 14: below-threshold roles drop full text after N days; unsubmitted and expired
    roles archive. Roles with an application are never touched; no history is deleted."""
    deps = deps or DEPS
    values = await settings_service.values(session)
    now = deps.clock.now()
    text_cutoff = now - timedelta(days=values["retention.below_threshold_text_days"])
    archive_cutoff = now - timedelta(days=values["retention.unsubmitted_archive_days"])
    applied = select(Application.job_id)
    counts: Counter[str] = Counter()

    stale_text = (await session.scalars(select(Job).where(
        Job.triage == "below_threshold", Job.raw_text.is_not(None), Job.updated_at < text_cutoff,
        Job.id.not_in(applied)))).all()
    for job in stale_text:
        counts["text_dropped"] += 1
        if not run.dry_run:
            job.raw_text = None

    to_archive = (await session.scalars(select(Job).where(
        Job.triage.in_(["new", "shortlisted", "below_threshold"]), Job.pinned.is_(False), Job.id.not_in(applied),
        or_(Job.created_at < archive_cutoff, Job.availability == Availability.closed)))).all()
    for job in to_archive:
        counts["archived_closed" if job.availability == Availability.closed else "archived_stale"] += 1
        if not run.dry_run:
            job.triage = "archived"
            await audit.record(session, actor="system", action="job.archived", subject_type="job",
                               subject_id=job.id, detail={"run_id": str(run.id), "reason": "retention"})
    run.counts = dict(counts)
    await session.commit()
    return RunStatus.succeeded


# ----- registration --------------------------------------------------------------------------


async def _sweep_handler(session: AsyncSession, run: Run) -> RunStatus:
    return await run_sweep(session, run)


async def _expiry_handler(session: AsyncSession, run: Run) -> RunStatus:
    return await run_expiry_check(session, run)


async def _retention_handler(session: AsyncSession, run: Run) -> RunStatus:
    return await run_retention(session, run)


def install() -> None:
    """Register the run handlers (idempotent)."""
    for kind, handler in ((RunKind.sweep, _sweep_handler), (RunKind.expiry_check, _expiry_handler),
                          (RunKind.retention, _retention_handler)):
        if handler_for(kind) is None:
            register(kind, handler)
