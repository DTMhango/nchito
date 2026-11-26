"""Employers: per-employer overrides and the cooldown read model (DESIGN 7.1, 8.1, 10.3).

The cooldown rule is fixed (7.1): it runs from the end state, or from the applied date when there has
been no reply. Its length is the owner's per-employer override, else the watched employer's own, else
``matching.employer_cooldown_days``. Ending a cooldown early records who, when and why; applications
that ended or went out before that moment stop counting.

``employer_key`` everywhere is the alias-resolved, casefolded canonical employer
(``conflicts.employer_key``), so subsidiaries and brands share one policy.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import END_STAGES, LIVE_STAGES, Application, Stage
from app.models.bulk import EmployerPolicy
from app.models.search import Assessment, ConflictState, EmployerAlias, Job, WatchedEmployer
from app.pipeline import conflicts
from app.schemas.json_types import CooldownKind, EmployerStateName

NO_REPLY_STAGES = frozenset({Stage.submitted_unconfirmed, Stage.submitted})


class EmployerError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = "employer_error") -> None:
        super().__init__(message)
        self.status, self.code = status, code


def norm(name: str | None) -> str:
    return (name or "").strip().casefold()


# ----- the cooldown rule ------------------------------------------------------------------------------


@dataclass(frozen=True)
class CooldownRule:
    """Which rule applies to the application that sets the cooldown, and when it ends."""

    kind: CooldownKind
    application_id: uuid.UUID
    anchor: datetime
    days: int
    until: date
    text: str


def anchor_for(app: Application) -> tuple[CooldownKind, datetime] | None:
    """The cooldown starts at the end state, or at the applied date when there has been no reply."""
    if app.applied_at is None:
        return None  # never applied (skipped before applying)
    if app.stage in END_STAGES:
        return "end_state", app.ended_at or app.applied_at
    if app.stage in NO_REPLY_STAGES:
        return "applied_date", app.applied_at
    return None  # live with a reply (screening, interview, offer): in progress, not cooling


def cooldown_rule(apps: Sequence[Application], days: int, *, released_at: datetime | None = None,
                  exclude: uuid.UUID | None = None, days_source: str = "") -> CooldownRule | None:
    """The latest-ending cooldown across the employer's applications, with the rule that produced it."""
    best: CooldownRule | None = None
    for app in apps:
        if app.id == exclude:
            continue
        found = anchor_for(app)
        if found is None:
            continue
        kind, anchor = found
        if released_at is not None and anchor <= released_at:
            continue
        until = (anchor + timedelta(days=days)).date()
        if best is not None and until <= best.until:
            continue
        if kind == "end_state":
            why = f"it ended ({app.stage.value}) on {anchor.date()}"
        else:
            why = f"it was applied to on {anchor.date()} and there has been no reply"
        src = f" ({days_source})" if days_source else ""
        best = CooldownRule(kind, app.id, anchor, days, until,
                            f"{days} days{src} from {anchor.date()}: {why}; ends {until}")
    return best


# ----- policy -----------------------------------------------------------------------------------------


async def policy_for(session: AsyncSession, key: str) -> EmployerPolicy | None:
    return await session.scalar(select(EmployerPolicy).where(EmployerPolicy.employer_key == key))


async def policies(session: AsyncSession) -> dict[str, EmployerPolicy]:
    return {p.employer_key: p for p in (await session.scalars(select(EmployerPolicy))).all()}


async def watched_by_name(session: AsyncSession) -> dict[str, WatchedEmployer]:
    return {norm(w.name): w for w in (await session.scalars(select(WatchedEmployer))).all()}


async def effective_days(session: AsyncSession, key: str, settings: Mapping[str, Any]) -> tuple[int, str]:
    """(days, where they come from): the owner's override, a watched employer's own, the setting."""
    pol = await policy_for(session, key)
    if pol is not None and pol.cooldown_days is not None:
        return pol.cooldown_days, "this employer's override"
    watched = await session.scalar(select(WatchedEmployer).where(func.lower(WatchedEmployer.name) == key))
    if watched is not None and watched.cooldown_days is not None:
        return watched.cooldown_days, "the watched employer's own"
    return int(settings["matching.employer_cooldown_days"]), "the default setting"


async def never_apply_reason(session: AsyncSession, job: Job) -> str | None:
    """Why the owner never applies to this job's employer, or None. Reads the alias-resolved key."""
    aliases = await conflicts.employer_aliases(session)
    pol = await policy_for(session, conflicts.employer_key(job, aliases))
    if pol is not None and pol.never_apply:
        return f"you never apply to {pol.display_name}" + (f": {pol.never_reason}" if pol.never_reason else "")
    return None


# ----- overview and detail ----------------------------------------------------------------------------


@dataclass
class EmployerRow:
    key: str
    name: str
    state: EmployerStateName
    state_text: str
    applications: int
    live: int
    last_applied_at: datetime | None
    roles_seen: int
    held_roles: int
    cooldown_until: date | None
    always_ask_first: bool
    never_apply: bool
    never_reason: str | None
    watched: bool
    priority: int
    cooldown_days: int | None


@dataclass
class EmployerRoleRow:
    job_id: uuid.UUID
    title: str
    triage: str
    conflict_state: str
    conflict_note: str | None
    score: int | None
    application_id: uuid.UUID | None
    stage: str | None
    posted_at: datetime | None


@dataclass
class EmployerDetail:
    row: EmployerRow
    cooldown: CooldownRule | None
    days: int
    days_source: str
    released_at: datetime | None
    released_reason: str | None
    released_by: str | None
    roles: list[EmployerRoleRow] = field(default_factory=list)
    groups: list[list[EmployerRoleRow]] = field(default_factory=list)
    applications: list[Application] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    notes: str | None = None
    contacts: list[Any] = field(default_factory=list)


def _state(live: int, cooldown_until: date | None, today: date, ask: bool, never: bool, never_reason: str | None
           ) -> tuple[EmployerStateName, str]:
    if never:
        return "blocked", "never apply" + (f": {never_reason}" if never_reason else "")
    if live:
        return "role_in_progress", f"{live} role{'s' if live != 1 else ''} in progress"
    if cooldown_until is not None and cooldown_until > today:
        return "cooling_down", f"cooling down until {cooldown_until}"
    if ask:
        return "always_ask_first", "always ask first"
    return "free", "free to apply"


async def _load(session: AsyncSession) -> tuple[list[Job], dict[str, str], dict[uuid.UUID, list[Application]]]:
    aliases = await conflicts.employer_aliases(session)
    jobs = list((await session.scalars(select(Job).where(Job.merged_into_id.is_(None)))).all())
    by_job: dict[uuid.UUID, list[Application]] = {}
    for app in (await session.scalars(select(Application))).all():
        by_job.setdefault(app.job_id, []).append(app)
    return jobs, aliases, by_job


def _rows(jobs: Sequence[Job], aliases: Mapping[str, str], by_job: Mapping[uuid.UUID, list[Application]],
          pols: Mapping[str, EmployerPolicy], watched: Mapping[str, WatchedEmployer], settings: Mapping[str, Any],
          today: date) -> tuple[list[EmployerRow], dict[str, list[Job]], dict[str, list[Application]]]:
    groups: dict[str, list[Job]] = {}
    for job in jobs:
        groups.setdefault(conflicts.employer_key(job, aliases), []).append(job)
    rows: list[EmployerRow] = []
    app_map: dict[str, list[Application]] = {}
    default_days = int(settings["matching.employer_cooldown_days"])
    for key, members in groups.items():
        apps = [a for j in members for a in by_job.get(j.id, [])]
        app_map[key] = apps
        pol, w = pols.get(key), watched.get(key)
        days = pol.cooldown_days if pol and pol.cooldown_days is not None else (
            w.cooldown_days if w and w.cooldown_days is not None else default_days)
        counted = [a for a in apps if stages.counts_as_application(a)]
        rule = cooldown_rule(counted, days, released_at=pol.cooldown_released_at if pol else None)
        live = sum(1 for a in apps if a.stage in LIVE_STAGES)
        ask = bool((pol and pol.always_ask_first) or (w and w.always_ask_first))
        never = bool(pol and pol.never_apply)
        until = rule.until if rule and rule.until > today else None
        state, text = _state(live, until, today, ask, never, pol.never_reason if pol else None)
        applied = [a.applied_at for a in apps if a.applied_at is not None]
        if pol:
            name = pol.display_name
        elif key.startswith("recruiter:"):
            name = f"{members[0].recruiter} (recruiter)"
        else:
            name = members[0].canonical_employer
        rows.append(EmployerRow(
            key=key, name=name, state=state, state_text=text, applications=len(counted), live=live,
            last_applied_at=max(applied) if applied else None, roles_seen=len(members),
            held_roles=sum(1 for j in members if j.conflict_state == ConflictState.held), cooldown_until=until,
            always_ask_first=ask, never_apply=never, never_reason=pol.never_reason if pol else None,
            watched=bool((pol and pol.watched) or w), priority=pol.priority if pol else (w.priority if w else 0),
            cooldown_days=pol.cooldown_days if pol else None))
    for key, pol in pols.items():  # a policy set before any role was seen still shows
        if key in groups:
            continue
        state, text = _state(0, None, today, pol.always_ask_first, pol.never_apply, pol.never_reason)
        rows.append(EmployerRow(key=key, name=pol.display_name, state=state, state_text=text, applications=0, live=0,
                                last_applied_at=None, roles_seen=0, held_roles=0, cooldown_until=None,
                                always_ask_first=pol.always_ask_first, never_apply=pol.never_apply,
                                never_reason=pol.never_reason, watched=pol.watched, priority=pol.priority,
                                cooldown_days=pol.cooldown_days))
        app_map[key] = []
    rows.sort(key=lambda r: (-r.priority, r.name.casefold()))
    return rows, groups, app_map


async def overview(session: AsyncSession, *, now: datetime | None = None) -> list[EmployerRow]:
    now = now or utcnow()
    jobs, aliases, by_job = await _load(session)
    settings = await settings_service.values(session)
    rows, _, _ = _rows(jobs, aliases, by_job, await policies(session), await watched_by_name(session), settings,
                       now.date())
    return rows


async def states_for_jobs(session: AsyncSession, job_ids: Sequence[uuid.UUID], *, now: datetime | None = None
                          ) -> dict[uuid.UUID, tuple[EmployerStateName, str]]:
    """The employer chip (state and text) for each job, for Matches and Applications."""
    now = now or utcnow()
    jobs, aliases, by_job = await _load(session)
    settings = await settings_service.values(session)
    rows, groups, _ = _rows(jobs, aliases, by_job, await policies(session), await watched_by_name(session),
                            settings, now.date())
    by_key = {r.key: r for r in rows}
    wanted = set(job_ids)
    out: dict[uuid.UUID, tuple[EmployerStateName, str]] = {}
    for key, members in groups.items():
        for job in members:
            if job.id in wanted:
                out[job.id] = (by_key[key].state, by_key[key].state_text)
    return out


async def detail(session: AsyncSession, key: str, *, now: datetime | None = None) -> EmployerDetail:
    from app.models.applications import Contact

    now = now or utcnow()
    jobs, aliases, by_job = await _load(session)
    settings = await settings_service.values(session)
    pols = await policies(session)
    rows, groups, app_map = _rows(jobs, aliases, by_job, pols, await watched_by_name(session), settings, now.date())
    row = next((r for r in rows if r.key == key), None)
    if row is None:
        raise EmployerError("employer not found", 404, "not_found")
    members = groups.get(key, [])
    apps = sorted(app_map.get(key, []), key=lambda a: a.created_at)
    days, source = await effective_days(session, key, settings)
    pol = pols.get(key)
    rule = cooldown_rule([a for a in apps if stages.counts_as_application(a)], days,
                         released_at=pol.cooldown_released_at if pol else None, days_source=source)
    ids = [j.id for j in members]
    scores = dict((await session.execute(
        select(Assessment.job_id, func.max(Assessment.score)).where(Assessment.job_id.in_(ids))
        .group_by(Assessment.job_id))).all()) if ids else {}
    app_by_job = {a.job_id: a for a in apps}

    def role(j: Job) -> EmployerRoleRow:
        a = app_by_job.get(j.id)
        return EmployerRoleRow(j.id, j.title, j.triage, j.conflict_state.value, j.conflict_note, scores.get(j.id),
                               a.id if a else None, a.stage.value if a else None, j.posted_at)

    roles = sorted((role(j) for j in members), key=lambda r: (r.score is None, -(r.score or 0), r.title))
    by_id = {r.job_id: r for r in roles}
    grouped = conflicts.conflict_groups(members, str(settings["matching.roles_per_employer_scope"]),
                                        recruiter_similarity=_recruiter_similarity(settings))
    contacts = list((await session.scalars(select(Contact).where(Contact.job_id.in_(ids))
                                           .order_by(Contact.created_at))).all()) if ids else []
    alias_names = [a.alias for a in (await session.scalars(select(EmployerAlias).where(
        func.lower(EmployerAlias.canonical) == key))).all()]
    return EmployerDetail(
        row=row, cooldown=rule, days=days, days_source=source,
        released_at=pol.cooldown_released_at if pol else None,
        released_reason=pol.cooldown_released_reason if pol else None,
        released_by=pol.cooldown_released_by if pol else None, roles=roles,
        groups=[[by_id[j.id] for j in g] for g in grouped if len(g) > 1], applications=apps, aliases=alias_names,
        notes=pol.notes if pol else None, contacts=contacts)


def _recruiter_similarity(settings: Mapping[str, Any]) -> float:
    for key in ("matching.recruiter_similarity", "matching.recruiter_title_similarity"):
        if key in settings:
            return float(settings[key])
    return 0.8


# ----- edits ------------------------------------------------------------------------------------------


async def _ensure_policy(session: AsyncSession, key: str) -> EmployerPolicy:
    pol = await policy_for(session, key)
    if pol is not None:
        return pol
    name = await session.scalar(select(Job.canonical_employer).where(
        func.lower(Job.canonical_employer) == key, Job.merged_into_id.is_(None)).limit(1))
    pol = EmployerPolicy(employer_key=key, display_name=name or key)
    session.add(pol)
    await session.flush()
    return pol


def _plain(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, date | datetime) else v) for k, v in d.items()}


async def update_policy(session: AsyncSession, key: str, changes: Mapping[str, Any], *, actor: str
                        ) -> EmployerPolicy:
    """Set per-employer overrides. ``never_apply`` needs a reason. Priority also updates a watched
    employer of the same name (the board entry)."""
    pol = await _ensure_policy(session, key)
    before = {k: getattr(pol, k) for k in changes}
    if changes.get("never_apply") is True and not str(changes.get("never_reason") or pol.never_reason or "").strip():
        raise EmployerError("a reason is required to never apply to an employer", 422, "reason_required")
    for k, v in changes.items():
        setattr(pol, k, v)
    if changes.get("never_apply") is False:
        pol.never_reason = None
    if "priority" in changes:
        for w in await session.scalars(select(WatchedEmployer).where(func.lower(WatchedEmployer.name) == key)):
            w.priority = int(changes["priority"])
    await session.flush()
    await audit.record(session, actor=actor, action="employer.policy_updated", subject_type="employer",
                       subject_id=pol.id, detail={"employer": pol.display_name, "before": _plain(before),
                                                  "after": _plain({k: getattr(pol, k) for k in changes})})
    return pol


async def end_cooldown(session: AsyncSession, key: str, *, reason: str, actor: str, now: datetime | None = None
                       ) -> EmployerPolicy:
    """End the running cooldown early. Applications that ended or went out before now stop counting."""
    reason = reason.strip()
    if not reason:
        raise EmployerError("a reason is required to end a cooldown early", 422, "reason_required")
    now = now or utcnow()
    info = await detail(session, key, now=now)
    if info.cooldown is None or info.cooldown.until <= now.date():
        raise EmployerError("there is no cooldown running for this employer", 409, "no_cooldown")
    pol = await _ensure_policy(session, key)
    pol.cooldown_released_at, pol.cooldown_released_reason, pol.cooldown_released_by = now, reason, actor
    await session.flush()
    await audit.record(session, actor=actor, action="employer.cooldown_ended", subject_type="employer",
                       subject_id=pol.id, detail={"employer": pol.display_name, "reason": reason,
                                                  "would_have_ended": info.cooldown.until.isoformat(),
                                                  "rule": info.cooldown.kind})
    return pol


async def merge_employers(session: AsyncSession, from_key: str, into: str, *, remember_alias: bool, actor: str
                          ) -> int:
    """Point every job posted under ``from_key`` at ``into`` (the corrections code does the work)."""
    from app.pipeline import corrections

    into = " ".join(into.split())
    if not into:
        raise EmployerError("the employer to merge into is required", 422, "name_required")
    if norm(into) == from_key:
        raise EmployerError("that is the same employer", 409, "same_employer")
    jobs = list((await session.scalars(select(Job).where(
        func.lower(Job.canonical_employer) == from_key, Job.merged_into_id.is_(None)))).all())
    if not jobs:
        raise EmployerError("employer not found", 404, "not_found")
    changed: set[uuid.UUID] = set()
    for job in jobs:
        if job.id in changed:
            continue
        done = await corrections.fix_employer(session, job.id, into, remember_alias=remember_alias, actor=actor)
        changed.update(j.id for j in done)
    return len(changed)


async def split_employer(session: AsyncSession, alias: str, *, actor: str) -> int:
    """Undo a merge: forget the alias and give its jobs their own posted employer name again."""
    from app.pipeline import corrections

    row = await session.scalar(select(EmployerAlias).where(func.lower(EmployerAlias.alias) == norm(alias)))
    if row is None:
        raise EmployerError("that name is not merged into another employer", 404, "not_found")
    canonical, posted = row.canonical, row.alias
    await session.delete(row)
    await session.flush()
    jobs = list((await session.scalars(select(Job).where(func.lower(Job.employer) == norm(posted),
                                                         Job.merged_into_id.is_(None)))).all())
    own = await corrections.canonical_employer(session, posted)
    for job in jobs:
        job.canonical_employer = own
    await session.flush()
    await audit.record(session, actor=actor, action="employer.split", subject_type="employer", subject_id=None,
                       detail={"alias": posted, "was_merged_into": canonical, "jobs": len(jobs)})
    await corrections.reevaluate_conflicts(session, {canonical, own})
    return len(jobs)
