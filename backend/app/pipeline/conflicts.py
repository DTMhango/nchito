"""One role per employer (DESIGN.md 7.1).

- **Conflict group:** roles at one canonical employer (aliases merged) within the scope setting
  ``matching.roles_per_employer_scope``: ``same_department`` (unknown function counts as the same,
  so it links departments), ``whole_employer`` or ``off``. Groups span campaigns: the contest is
  between job-campaign assessments.
- **Winner:** ``matching.conflict_winner``: highest score, or campaign priority first then
  score. Ties: the campaign's preferred seniority, then the later deadline, then the newer
  posting. Others are **held** with the outranking reason.
- **Promotion:** a winner that closes, is skipped or fails a recheck leaves the contest; the next
  role is promoted on the next resolution (``on_job_changed``).
- **Prepared work is not displaced silently:** when a new top role would displace a winner whose
  application the owner has edited or approved, the winner stays and a ``conflict_choice``
  pending action carries both.
- **After applying:** an application is *live* from ``applying`` until an end state; the group
  is locked while one is live or within the cooldown (from the end state, or from the applied
  date when there has been no reply). A better role then raises a pending action; it is never
  applied to automatically. ``matching.max_live_per_employer`` caps live applications.
- **Enforcement:** ``check_conflict_at_submit`` runs under a per-employer advisory lock, so two
  runners cannot both pass.
- Recruiter postings with an undisclosed employer are grouped by recruiter and title similarity
  and flagged when they look like a direct posting's vacancy.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import (
    END_STAGES,
    LIVE_STAGES,
    Application,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.search import (
    Assessment,
    AssessmentState,
    Availability,
    Campaign,
    ConflictState,
    EmployerAlias,
    Job,
    Rubric,
    WatchedEmployer,
)
from app.pipeline.decisions import GateDecision, RuleRef

PREPARED_STAGES = frozenset({Stage.tailoring, Stage.ready})
NO_REPLY_STAGES = frozenset({Stage.submitted_unconfirmed, Stage.submitted})
OUT_OF_CONTEST_TRIAGE = ("skipped", "archived")
RECRUITER_FLAG_TAG = "possible-same-vacancy"


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


async def employer_aliases(session: AsyncSession) -> dict[str, str]:
    return {_norm(a.alias): a.canonical for a in (await session.scalars(select(EmployerAlias))).all()}


def undisclosed(job: Job) -> bool:
    """A recruiter posting whose employer is not named (normalise sets employer to the recruiter)."""
    return bool(job.recruiter) and _norm(job.canonical_employer) in ("", _norm(job.recruiter))


def employer_key(job: Job, aliases: Mapping[str, str]) -> str:
    if undisclosed(job):
        return f"recruiter:{_norm(job.recruiter)}"
    return _norm(aliases.get(_norm(job.canonical_employer), job.canonical_employer))


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ----- grouping ---------------------------------------------------------------------------


class _Union:
    def __init__(self, items: Iterable[uuid.UUID]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: uuid.UUID) -> uuid.UUID:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, a: uuid.UUID, b: uuid.UUID) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def groups(self) -> list[list[uuid.UUID]]:
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        for item in self.parent:
            out.setdefault(self.find(item), []).append(item)
        return list(out.values())


def conflict_groups(jobs: Sequence[Job], scope: str, *, recruiter_similarity: float) -> list[list[Job]]:
    """Partition one employer's jobs into conflict groups (``scope`` ``off``: every job alone)."""
    by_id = {j.id: j for j in jobs}
    union = _Union(by_id)
    if scope != "off":
        items = list(jobs)
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if undisclosed(a) or undisclosed(b):
                    if similarity(a.title, b.title) >= recruiter_similarity:
                        union.join(a.id, b.id)
                elif scope == "whole_employer" or a.function is None or b.function is None \
                        or _norm(a.function) == _norm(b.function):
                    union.join(a.id, b.id)
    return [[by_id[i] for i in sorted(group, key=str)] for group in union.groups()]


# ----- employer state: live applications and cooldown ------------------------------------


@dataclass
class EmployerState:
    live: list[Application]
    cooldown_until: date | None
    cooldown_from: Application | None

    def counters(self, today: date) -> dict[str, int]:
        left = (self.cooldown_until - today).days if self.cooldown_until and self.cooldown_until > today else 0
        return {"employer_live": len(self.live), "employer_cooldown_days_left": left}


def cooldown_anchor(app: Application) -> datetime | None:
    """The cooldown runs from the end state, or from the applied date if there has been no reply."""
    if app.applied_at is None:
        return None  # never applied (e.g. skipped before applying)
    if app.stage in END_STAGES:
        return app.ended_at or app.applied_at
    if app.stage in NO_REPLY_STAGES:
        return app.applied_at
    return None


def employer_state(apps: Sequence[Application], cooldown_days: int, *, exclude: uuid.UUID | None = None
                   ) -> EmployerState:
    live = [a for a in apps if a.stage in LIVE_STAGES and a.id != exclude]
    until, source = None, None
    for app in apps:
        anchor = None if app.id == exclude else cooldown_anchor(app)
        if anchor is None:
            continue
        end = (anchor + timedelta(days=cooldown_days)).date()
        if until is None or end > until:
            until, source = end, app
    return EmployerState(live=live, cooldown_until=until, cooldown_from=source)


async def _cooldown_days(session: AsyncSession, employer: str, settings: Mapping[str, Any]) -> int:
    watched = await session.scalar(select(WatchedEmployer).where(func.lower(WatchedEmployer.name) == employer))
    if watched is not None and watched.cooldown_days is not None:
        return watched.cooldown_days
    return int(settings["matching.employer_cooldown_days"])


async def _employer_jobs(session: AsyncSession, key: str, aliases: Mapping[str, str]) -> list[Job]:
    if key.startswith("recruiter:"):
        stmt = select(Job).where(func.lower(Job.recruiter) == key.removeprefix("recruiter:"))
    else:
        names = {key} | {alias for alias, canonical in aliases.items() if _norm(canonical) == key}
        stmt = select(Job).where(or_(func.lower(Job.canonical_employer).in_(names),
                                     func.lower(Job.recruiter).in_(names)))
    jobs = (await session.scalars(stmt.where(Job.merged_into_id.is_(None)))).all()
    return [j for j in jobs if employer_key(j, aliases) == key]


async def employer_counters(session: AsyncSession, job: Job, *, now: datetime | None = None) -> dict[str, int]:
    """Live and cooldown counters for the decision table."""
    now = now or utcnow()
    settings = await settings_service.values(session)
    aliases = await employer_aliases(session)
    key = employer_key(job, aliases)
    jobs = await _employer_jobs(session, key, aliases)
    apps = (await session.scalars(select(Application).where(Application.job_id.in_([j.id for j in jobs])))).all()
    state = employer_state(apps, await _cooldown_days(session, key, settings))
    return state.counters(now.date())


# ----- the contest ------------------------------------------------------------------------


@dataclass
class Entry:
    assessment: Assessment
    job: Job
    campaign: Campaign
    score: int


def _deadline_key(job: Job) -> int:
    # Later deadline wins a tie; an open-ended role counts as the latest.
    return job.deadline.toordinal() if job.deadline else date.max.toordinal()


def rank_key(entry: Entry, winner_rule: str) -> tuple[Any, ...]:
    seniority = entry.campaign.preferred_seniority
    prefers = 0 if seniority and _norm(entry.job.level) == _norm(seniority) else 1
    posted = entry.job.posted_at.timestamp() if entry.job.posted_at else float("-inf")
    primary = (-entry.campaign.priority, -entry.score) if winner_rule == "campaign_priority_then_score" \
        else (-entry.score,)
    return (*primary, prefers, -_deadline_key(entry.job), -posted, str(entry.job.id), str(entry.campaign.id))


def describe(entry: Entry) -> str:
    return f"{entry.job.title} ({entry.campaign.name})"


async def _eligible_entries(session: AsyncSession, jobs: Sequence[Job], settings: Mapping[str, Any]) -> list[Entry]:
    ids = [j.id for j in jobs]
    by_id = {j.id: j for j in jobs}
    rows = (await session.execute(
        select(Assessment, Campaign).join(Campaign, Campaign.id == Assessment.campaign_id)
        .where(Assessment.job_id.in_(ids), Assessment.state == AssessmentState.scored,
               Assessment.score.is_not(None)))).all()
    rubrics: dict[uuid.UUID, Rubric | None] = {}
    entries = []
    for assessment, campaign in rows:
        job = by_id[assessment.job_id]
        if job.availability == Availability.closed or job.triage in OUT_OF_CONTEST_TRIAGE:
            continue
        if any(f.result == "fail" and f.mandatory for f in assessment.filter_results):
            continue
        if assessment.rubric_id not in rubrics:
            rubrics[assessment.rubric_id] = await session.get(Rubric, assessment.rubric_id) \
                if assessment.rubric_id else None
        rubric = rubrics[assessment.rubric_id]
        own = rubric.body.thresholds.shortlist if rubric else None
        shortlist = own if own is not None else int(settings["scoring.threshold_shortlist"])
        if assessment.score is not None and assessment.score >= shortlist:
            entries.append(Entry(assessment, job, campaign, assessment.score))
    return entries


async def _raise_choice(session: AsyncSession, group_key: str, title: str, detail: dict[str, Any]) -> None:
    exists = await session.scalar(select(PendingAction.id).where(
        PendingAction.group_key == group_key, PendingAction.status == PendingStatus.open).limit(1))
    if exists is None:
        session.add(PendingAction(type=PendingActionType.conflict_choice, group_key=group_key, title=title,
                                  detail=detail))
        await session.flush()


def _summary(entry: Entry) -> dict[str, Any]:
    return {"job_id": str(entry.job.id), "title": entry.job.title, "campaign_id": str(entry.campaign.id),
            "campaign": entry.campaign.name, "assessment_id": str(entry.assessment.id), "score": entry.score}


@dataclass
class GroupOutcome:
    winner: uuid.UUID | None
    held: list[uuid.UUID]
    reason: str | None


async def _resolve_group(session: AsyncSession, key: str, group: list[Job], entries: list[Entry],
                         apps: Sequence[Application], state: EmployerState, settings: Mapping[str, Any],
                         versions: Mapping[str, int], now: datetime) -> GroupOutcome:
    rule = settings["matching.conflict_winner"]
    rule_ref = f"matching.conflict_winner={rule} (v{versions.get('matching.conflict_winner', 0)})"
    group_ids = {j.id for j in group}
    previous_winner = next((j for j in group if j.conflict_state == ConflictState.winner), None)
    mine = [e for e in entries if e.job.id in group_ids and e.job.conflict_state != ConflictState.released]
    for entry in entries:
        if entry.job.id in group_ids:
            entry.assessment.is_conflict_winner = False
    contenders = {e.job.id for e in mine}
    for job in group:
        if job.conflict_state != ConflictState.released and job.id not in contenders:
            job.conflict_state, job.conflict_note, job.conflict_detail = ConflictState.none, None, None
    if not mine:
        return GroupOutcome(None, [], None)
    ordered = sorted(mine, key=lambda e: rank_key(e, rule))
    top = ordered[0]
    group_apps = [a for a in apps if a.job_id in group_ids]
    max_live = int(settings["matching.max_live_per_employer"])

    # After applying: the group is locked while an application is live or in cooldown.
    applied = [a for a in group_apps if a.stage in LIVE_STAGES or cooldown_anchor(a) is not None]
    today = now.date()
    in_cooldown = state.cooldown_until is not None and state.cooldown_until > today
    locked_by = next((a for a in applied if a.stage in LIVE_STAGES), None) or \
        (state.cooldown_from if in_cooldown and state.cooldown_from in group_apps else None)
    if locked_by is not None or len(state.live) >= max_live:
        anchor_app = locked_by or state.live[0]
        anchor_job = await session.get(Job, anchor_app.job_id)
        why = (f"{len(state.live)} live application(s) at this employer (max {max_live})"
               if len(state.live) >= max_live else f"employer cooldown until {state.cooldown_until}")
        locked_score = None
        if anchor_app.assessment_id:
            prior = await session.get(Assessment, anchor_app.assessment_id)
            locked_score = prior.score if prior else None
        for entry in ordered:
            if entry.job.id == anchor_app.job_id:
                continue
            entry.job.conflict_state = ConflictState.held
            entry.job.conflict_detail = {"outranked_by_job_id": str(anchor_app.job_id),
                                         "outranked_by_title": anchor_job.title if anchor_job else None,
                                         "score": entry.score, "outranked_by_score": locked_score,
                                         "reason": "applied"}
            entry.job.conflict_note = f"held: already applied to {anchor_job.title if anchor_job else 'a role'} " \
                                      f"here; {why}"
            if locked_score is not None and entry.score > locked_score:
                await _raise_choice(session, f"conflict:after-apply:{key}:{entry.job.id}",
                                    f"Better role at {entry.job.employer} after applying", {
                                        "kind": "better_role_after_applying", "candidate": _summary(entry),
                                        "application_id": str(anchor_app.id),
                                        "applied_job_id": str(anchor_app.job_id), "applied_score": locked_score})
        return GroupOutcome(None, [e.job.id for e in ordered if e.job.id != anchor_app.job_id], why)

    current = next((e for e in ordered if e.job.conflict_state == ConflictState.winner), None)
    winner = top
    if current is not None and current.job.id != top.job.id:
        prepared = next((a for a in group_apps if a.job_id == current.job.id
                         and (a.stage in PREPARED_STAGES or a.approved_packet_id is not None)), None)
        if prepared is not None:
            winner = current
            await _raise_choice(session, f"conflict:displace:{key}:{current.job.id}:{top.job.id}",
                                f"Choose between two roles at {top.job.employer}", {
                                    "kind": "displace_prepared", "current": _summary(current),
                                    "challenger": _summary(top), "application_id": str(prepared.id),
                                    "rule": rule_ref})
    winner.assessment.is_conflict_winner = True
    others = [e for e in ordered if e.job.id != winner.job.id]
    runner_up = others[0] if others else None
    note = f"won employer group by {rule_ref}"
    if runner_up is not None:
        note += f": {winner.score} vs {runner_up.score} for {describe(runner_up)}"
    if winner is current and winner is not top:
        note += f"; {describe(top)} scores {top.score} but this role has prepared work (your choice pending)"
    if previous_winner is not None and previous_winner.id != winner.job.id and previous_winner.id not in contenders:
        note = f"promoted after {previous_winner.title} left the contest; " + note
    winner.job.conflict_state, winner.job.conflict_note = ConflictState.winner, note
    winner.job.conflict_detail = None
    held = []
    for entry in others:
        if entry.job.id == winner.job.id:
            continue
        entry.job.conflict_state = ConflictState.held
        entry.job.conflict_detail = {"outranked_by_job_id": str(winner.job.id), "outranked_by_title": winner.job.title,
                                     "score": entry.score, "outranked_by_score": winner.score, "reason": "outranked"}
        entry.job.conflict_note = f"outranked by {describe(winner)}, {winner.score} vs {entry.score} ({rule_ref})"
        held.append(entry.job.id)
    if previous_winner is None or previous_winner.id != winner.job.id:
        await audit.record(session, actor="system", action="conflict.decided", subject_type="job",
                           subject_id=winner.job.id, detail={
                               "employer": key, "winner": _summary(winner), "rule": rule_ref,
                               "held": [_summary(e) for e in others],
                               "previous_winner": str(previous_winner.id) if previous_winner else None})
    return GroupOutcome(winner.job.id, sorted(set(held), key=str), note)


async def flag_recruiter_postings(session: AsyncSession, jobs: Sequence[Job], threshold: float) -> None:
    """Flag undisclosed-employer recruiter postings that look like a direct posting's vacancy."""
    recruiter_jobs = [j for j in jobs if undisclosed(j)]
    if not recruiter_jobs:
        return
    direct = (await session.scalars(select(Job).where(Job.recruiter.is_(None), Job.merged_into_id.is_(None)))).all()
    for job in recruiter_jobs:
        match = max(direct, key=lambda d: similarity(d.title, job.title), default=None)
        if match is not None and similarity(match.title, job.title) >= threshold:
            if RECRUITER_FLAG_TAG not in job.tags:
                job.tags = [*job.tags, RECRUITER_FLAG_TAG]
            flag = f"may be the same vacancy as {match.title} at {match.employer} (review)"
            if flag not in (job.conflict_note or ""):
                job.conflict_note = f"{job.conflict_note}; {flag}" if job.conflict_note else flag


async def resolve_employers(session: AsyncSession, employers: Iterable[str], *, now: datetime | None = None
                            ) -> dict[str, list[GroupOutcome]]:
    """Recompute the conflict groups of these employers (names as on jobs, or canonical)."""
    now = now or utcnow()
    states = await settings_service.get_all(session)
    settings = {k: s.value for k, s in states.items()}
    versions = {k: s.version for k, s in states.items()}
    aliases = await employer_aliases(session)
    keys = {_norm(aliases.get(_norm(e), e)) for e in employers if e}
    keys |= {f"recruiter:{_norm(e)}" for e in employers if e}
    scope = settings["matching.roles_per_employer_scope"]
    similarity_threshold = float(settings["matching.recruiter_similarity"])
    out: dict[str, list[GroupOutcome]] = {}
    for key in sorted(keys):
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                              {"k": f"nchito:employer:{key}"})
        jobs = await _employer_jobs(session, key, aliases)
        if not jobs:
            continue
        apps = list((await session.scalars(select(Application).where(
            Application.job_id.in_([j.id for j in jobs])))).all())
        state = employer_state(apps, await _cooldown_days(session, key, settings))
        entries = await _eligible_entries(session, jobs, settings)
        if scope == "off":
            for job in jobs:
                if job.conflict_state != ConflictState.released:
                    job.conflict_state, job.conflict_note, job.conflict_detail = ConflictState.none, None, None
            for entry in entries:
                entry.assessment.is_conflict_winner = False
            await flag_recruiter_postings(session, jobs, similarity_threshold)
            continue
        groups = conflict_groups(jobs, scope, recruiter_similarity=similarity_threshold)
        out[key] = [await _resolve_group(session, key, group, entries, apps, state, settings, versions, now)
                    for group in groups]
        await flag_recruiter_postings(session, jobs, similarity_threshold)
    await session.flush()
    return out


async def on_job_changed(session: AsyncSession, job: Job, *, now: datetime | None = None) -> None:
    """Call after a job closes, is skipped or fails a recheck: the next role is promoted."""
    await resolve_employers(session, [job.canonical_employer, job.recruiter or ""], now=now)


async def release_held(session: AsyncSession, job: Job, *, actor: str, reason: str) -> Job:
    """The owner releases one held role from its group, with a reason. Audited."""
    if job.conflict_state != ConflictState.held:
        raise ValueError("only a held role can be released")
    previous = job.conflict_note
    job.conflict_state, job.conflict_detail = ConflictState.released, None
    job.conflict_note = f"released by {actor}: {reason}"
    await audit.record(session, actor=actor, action="conflict.released", subject_type="job", subject_id=job.id,
                       detail={"reason": reason, "was": previous})
    await session.flush()
    return job


# ----- submit-time enforcement ------------------------------------------------------------


async def check_conflict_at_submit(session: AsyncSession, application: Application, *, now: datetime | None = None,
                                   claim: bool = True) -> GateDecision:
    """The conflict gate inside the submit-permit check.

    Takes a per-employer transaction lock, re-reads live applications and cooldown, and, when the
    gate passes and ``claim`` is set, moves the application to ``applying`` in the same
    transaction, so a second runner waiting on the lock sees it as live and fails.
    """
    now = now or utcnow()
    job = await session.get(Job, application.job_id)
    assert job is not None
    aliases = await employer_aliases(session)
    key = employer_key(job, aliases)
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                          {"k": f"nchito:employer:{key}"})
    await session.refresh(job)
    states = await settings_service.get_all(session)
    settings = {k: s.value for k, s in states.items()}
    scope = settings["matching.roles_per_employer_scope"]
    max_live = int(settings["matching.max_live_per_employer"])
    jobs = await _employer_jobs(session, key, aliases)
    apps = list((await session.scalars(select(Application).where(
        Application.job_id.in_([j.id for j in jobs])).execution_options(populate_existing=True))).all())
    state = employer_state(apps, await _cooldown_days(session, key, settings), exclude=application.id)
    refs = (RuleRef("matching.roles_per_employer_scope", scope, "setting",
                    f"v{states['matching.roles_per_employer_scope'].version}"),
            RuleRef("matching.max_live_per_employer", max_live, "setting",
                    f"v{states['matching.max_live_per_employer'].version}"),
            RuleRef("matching.employer_cooldown_days", settings["matching.employer_cooldown_days"], "setting",
                    f"v{states['matching.employer_cooldown_days'].version}"))

    def fail(reason: str) -> GateDecision:
        return GateDecision("employer_conflict", "automation", "fail", reason, refs)

    if scope != "off" and job.conflict_state not in (ConflictState.winner, ConflictState.released):
        return fail(job.conflict_note or f"role is {job.conflict_state.value} in its employer group")
    if len(state.live) >= max_live:
        return fail(f"{len(state.live)} live application(s) at this employer (max {max_live})")
    if state.cooldown_until is not None and state.cooldown_until > now.date():
        return fail(f"employer cooldown until {state.cooldown_until}")
    if claim and application.stage not in LIVE_STAGES:
        application.stage = Stage.applying
        await session.flush()
    return GateDecision("employer_conflict", "automation", "pass",
                        f"{len(state.live)} live at this employer (max {max_live}); no cooldown", refs)
