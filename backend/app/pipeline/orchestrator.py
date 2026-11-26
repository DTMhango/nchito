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
from app.llm.ledger import month_bounds
from app.llm.money import effective_cap_micros
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
from app.pipeline import dedupe, dry_run, normalise
from app.pipeline.runs import handler_for, register
from app.schemas.json_types import RateLimit, SourceHealth, SourceRunResult
from app.sources.base import RawJob, SearchContext, SourceConnector
from app.sources.http import HttpxFetcher
from app.sources.registry import build_connector, effective_config

log = logging.getLogger(__name__)

SourceFactory = Callable[[Source], SourceConnector]
LlmFactory = Callable[[AsyncSession, Run | None], Awaitable[LLMClient | None]]
ScoreHook = Callable[[AsyncSession, Run, list[uuid.UUID], LLMClient | None], Awaitable["ScoreOutcome | None"]]

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


@dataclass
class ScoreOutcome:
    """What the scoring stage reports back: its spend, and the budget scope if it parked work."""

    cost_micros: int = 0
    budget_scope: str | None = None


async def _no_scoring(session: AsyncSession, run: Run, job_ids: list[uuid.UUID],
                      llm: LLMClient | None) -> ScoreOutcome | None:
    return None


_score_hook: ScoreHook = _no_scoring


def register_score_hook(hook: ScoreHook) -> None:
    """The scoring stage registers ``(session, run, job_ids, llm) -> ScoreOutcome`` here (see
    ``pipeline/wiring.py``). ``llm`` is the run's client, or ``None`` when the budget is already out.
    Last registration wins."""
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

BUDGET_REASONS = {
    "no_cap": "no monthly AI budget cap is set, so paid stages (extraction, scoring) did not run; "
              "set a cap in Settings > AI",
    "monthly": "the monthly AI budget cap was reached",
    "per_run": "the per-run AI budget cap was reached",
    "call": "one call's estimate is above its own limit",
    "no_client": "no AI client is configured, so scoring did not run",
}


def budget_reason(scope: str) -> str:
    return BUDGET_REASONS.get(scope, f"the AI budget refused a call ({scope})")


@dataclass
class _Paid:
    """The paid stages of one run: the client, and the first budget refusal (after which no more
    paid calls are made in this run; the work is parked and resumes later)."""

    llm: LLMClient | None
    budget_scope: str | None = None
    cost: int = 0

    @property
    def open(self) -> bool:
        return self.llm is not None and self.budget_scope is None


async def _extract_job(session: AsyncSession, job: Job, norm: normalise.NormalisedJob, paid: _Paid,
                       aliases: dict[str, str], counts: Counter[str]) -> None:
    """Extract facets for one job, or leave it pending (budget or no client)."""
    if not paid.open:
        counts["extract_skipped"] += 1
        if normalise.PENDING_TAG not in job.tags:
            job.tags = [*job.tags, normalise.PENDING_TAG]
        return
    assert paid.llm is not None
    extraction = await normalise.extract(session, paid.llm, norm)
    if extraction.out is None:
        counts["extract_skipped"] += 1
        if extraction.skipped == "budget":
            paid.budget_scope = extraction.budget.scope if extraction.budget else "monthly"
        if normalise.PENDING_TAG not in job.tags:
            job.tags = [*job.tags, normalise.PENDING_TAG]
        return
    normalise.apply_extraction(job, extraction.out, aliases)
    if normalise.PENDING_TAG in job.tags:
        job.tags = [t for t in job.tags if t != normalise.PENDING_TAG]
    counts["extract_cached" if extraction.cached else "extracted"] += 1
    if extraction.usage:
        paid.cost += extraction.usage.cost_micros


def _since(campaign: Campaign, source: Source, overlap_days: int) -> datetime | None:
    """Each source keeps its own window: its last successful sweep for this campaign minus the overlap."""
    mark = (campaign.source_checkpoints or {}).get(str(source.id)) or campaign.last_sweep_checkpoint
    return mark - timedelta(days=overlap_days) if mark else None


async def _hand_off(session: AsyncSession, run: Run, job_ids: list[uuid.UUID], paid: _Paid) -> None:
    """Scoring stage. A failing scorer never fails intake (the Matches screen can re-run it)."""
    if not job_ids:
        return
    try:
        outcome = await _score_hook(session, run, list(dict.fromkeys(job_ids)), paid.llm if paid.open else None)
    except Exception as exc:
        log.exception("score_jobs hook failed for run %s", run.id)
        await session.rollback()
        await session.refresh(run)
        run.error = ((run.error + "; ") if run.error else "") + f"scoring hand-off failed: {exc}"[:500]
        return
    if outcome is not None:
        paid.cost += outcome.cost_micros
        if outcome.budget_scope and paid.budget_scope is None:
            paid.budget_scope = outcome.budget_scope


async def _finish_paid(session: AsyncSession, run: Run, campaign: Campaign, job_ids: list[uuid.UUID],
                       paid: _Paid, status: RunStatus, now: datetime) -> RunStatus:
    """Cost, dry-run proposals, and the budget pause. Shared by a sweep and its resumption."""
    run.cost_micros = (run.cost_micros or 0) + paid.cost
    run.config_versions = {**run.config_versions, "job_ids": [str(i) for i in dict.fromkeys(job_ids)]}
    if run.dry_run:
        proposals = await dry_run.propose_actions(session, campaign, job_ids, now=now, limit=MAX_PROPOSED)
        run.config_versions = {**run.config_versions, "proposed_actions": proposals}
    if paid.budget_scope is not None and status in (RunStatus.succeeded, RunStatus.partial):
        values = await settings_service.values(session)
        tz = values["general.timezone"]
        run.config_versions = {**run.config_versions, "paused": {
            "scope": paid.budget_scope, "cap_micros": effective_cap_micros(values, "monthly"),
            "per_run_cap_micros": effective_cap_micros(values, "per_run"), "month": month_bounds(now, tz)[2]}}
        note = f"Paused for budget: {budget_reason(paid.budget_scope)}. Parked work resumes when the cap allows."
        run.error = ((run.error + "; ") if run.error else "") + note
        status = RunStatus.paused
    await publish(session, "run.progress", {"run_id": str(run.id), "stage": "done", "counts": dict(run.counts)})
    await session.commit()
    return status


async def run_sweep(session: AsyncSession, run: Run, deps: IntakeDeps | None = None) -> RunStatus:
    deps = deps or DEPS
    started = deps.clock.now()
    campaign = await session.get(Campaign, run.campaign_id) if run.campaign_id else None
    if campaign is None:
        run.error = "a sweep needs a campaign"
        return RunStatus.failed
    if (run.config_versions or {}).get("resume"):
        return await resume_sweep(session, run, campaign, deps)
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
    tag_rules = await normalise.load_tag_rules(session)
    sources = await _sources_for(session, campaign)
    windows = {s.id: _since(campaign, s, overlap_days) for s in sources}
    run.config_versions = {
        "settings": {k: states[k].version for k in ("schedule.overlap_days", "matching.dedupe_similarity",
                                                     "ai.model_extract")},
        "prompt_extract": normalise.PROMPT_VERSION, "model_extract": model,
        "since": {str(k): v.isoformat() if v else None for k, v in windows.items()},
        "campaign_updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        "tag_rules": len(tag_rules)}
    if not sources:
        run.error = "no enabled sources allow search for this campaign"
        return RunStatus.failed
    watched = list((await session.scalars(select(WatchedEmployer))).all())
    counts: Counter[str] = Counter({k: 0 for k in STAGE_KEYS})
    await _progress(session, run, "search", counts)

    found = await asyncio.gather(*[
        _search_one(s, effective_config(s, watched), campaign, windows[s.id], deps) for s in sources])
    if await _cancelled(session, run):
        return RunStatus.cancelled

    paid = _Paid(None if deps.llm_factory is None else await deps.llm_factory(session, run))
    aliases = await normalise.load_skill_aliases(session)
    handoff: list[uuid.UUID] = []
    results: list[SourceRunResult] = []
    checkpoints = dict(campaign.source_checkpoints or {})
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
                await _extract_job(session, job, norm, paid, aliases, counts)
                counts["tagged"] += len(normalise.apply_tag_rules(job, tag_rules))
            if needs_model or result.outcome == dedupe.Outcome.new or run.dry_run:
                handoff.append(job.id)
            if needs_model or result.outcome == dedupe.Outcome.new:
                await publish(session, "job.created" if result.outcome == dedupe.Outcome.new else "job.updated",
                              {"job_id": str(job.id)})
        results.append(SourceRunResult(source_id=str(source.id), status="ok", found=len(item.jobs), new=new_here,
                                       error="; ".join(item.warnings)[:500] or None))
        if not run.dry_run:
            _record_health(source, item, started)
            checkpoints[str(source.id)] = started  # this source's window moves on its own success
        run.source_results = list(results)
        await _progress(session, run, f"source:{source.name}", counts)
        if await _cancelled(session, run):
            return RunStatus.cancelled

    failed = sum(r.status == "failed" for r in results)
    status = RunStatus.failed if failed == len(results) else RunStatus.partial if failed else RunStatus.succeeded
    run.source_results = results
    if failed:
        run.error = "; ".join(f"{r.source_id}: {r.error}" for r in results if r.status == "failed")[:2000]
    if not run.dry_run:
        campaign.source_checkpoints = checkpoints
        if status == RunStatus.succeeded:
            campaign.last_sweep_checkpoint = started  # every source succeeded
    counts["handed_to_scoring"] = len(set(handoff))
    run.counts = dict(counts)
    await session.commit()

    await _hand_off(session, run, handoff, paid)
    return await _finish_paid(session, run, campaign, handoff, paid, status, started)


async def resume_sweep(session: AsyncSession, run: Run, campaign: Campaign, deps: IntakeDeps) -> RunStatus:
    """Finish a run paused for budget: extract its pending jobs, score its parked ones. No source is read
    again and no checkpoint moves."""
    now = deps.clock.now()
    job_ids = [uuid.UUID(i) for i in run.config_versions.get("job_ids", [])]
    run.config_versions = {k: v for k, v in run.config_versions.items() if k not in ("resume", "paused")}
    paid = _Paid(None if deps.llm_factory is None else await deps.llm_factory(session, run))
    aliases = await normalise.load_skill_aliases(session)
    tag_rules = await normalise.load_tag_rules(session)
    counts: Counter[str] = Counter(run.counts or {})
    for job in (await session.scalars(select(Job).where(Job.id.in_(job_ids)))).all():
        if normalise.PENDING_TAG in job.tags:
            counts["extract_skipped"] -= 1
            norm = await normalise.parse_with_aliases(session, RawJob(
                source_url=job.apply_url or "", title=job.title, employer=job.employer,
                raw_text=job.raw_text or "", apply_url=job.apply_url))
            await _extract_job(session, job, norm, paid, aliases, counts)
            counts["tagged"] += len(normalise.apply_tag_rules(job, tag_rules))
    run.counts = {k: max(v, 0) for k, v in counts.items()}
    run.error = None
    await session.commit()
    await _hand_off(session, run, job_ids, paid)
    failed = any(r.status == "failed" for r in run.source_results)
    return await _finish_paid(session, run, campaign, job_ids, paid,
                              RunStatus.partial if failed else RunStatus.succeeded, now)


async def resume_paused(session: AsyncSession, enqueue: Callable[[Run], Awaitable[None]],
                        clock: Clock | None = None) -> list[Run]:
    """Re-queue runs paused for budget once the budget allows: a cap is set and it (or the per-run cap)
    changed since the pause, or a new budget month began. Called by the scheduler tick."""
    paused = list((await session.scalars(select(Run).where(Run.status == RunStatus.paused)
                                         .order_by(Run.created_at))).all())
    if not paused:
        return []
    values = await settings_service.values(session)
    if effective_cap_micros(values, "monthly") is None:
        return []
    month = month_bounds((clock or SystemClock()).now(), values["general.timezone"])[2]
    resumed: list[Run] = []
    for run in paused:
        mark = (run.config_versions or {}).get("paused") or {}
        changed = (mark.get("cap_micros") != effective_cap_micros(values, "monthly")
                   or mark.get("per_run_cap_micros") != effective_cap_micros(values, "per_run")
                   or mark.get("month") != month)
        if not changed:
            continue
        run.config_versions = {**run.config_versions, "resume": True}
        run.status = RunStatus.queued
        run.finished_at = None
        await audit.record(session, actor="system", action="run.resumed", subject_type="run", subject_id=run.id,
                           detail={"after": mark.get("scope")})
        resumed.append(run)
    await session.commit()
    for run in resumed:
        await enqueue(run)
    return resumed


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
