"""Policy preview: what a campaign or Autopilot change would do to recent real roles (DESIGN.md 8.1, 10.3).

Pure with respect to the database: it reads and never writes. Every role goes through exactly
``decisions.decide`` (purpose ``dry_run``), with the counters a dry run uses (``dry_run.propose_actions``:
best score first, each simulated application counted against the caps and the employer's live
limit), so the preview cannot disagree with a real dry run; a test holds the two equal.

What it reports, for the proposed policy and the one in force:

- **The line.** Roles that would have gone automatically over the window: mode ``auto_apply``, verdict
  past the thresholds, and every automation gate passing except the ones settled at send time (caps,
  quiet hours, pause, the fresh open-check), then the daily and weekly caps applied day by day in the
  order the roles were found. Split by channel; runner-ups held by their employer group counted apart.
- **Changed roles** (newly automatic, newly blocked, other changes) with the gates behind each.
- **Unknowns.** Roles whose pay, eligibility, score or employer group is unknown never go
  automatically, and are counted so (unknown is not yes).
- **The score histogram** of the window, and the thresholds in force.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.settings.registry import cross_check, get_def
from app.core.settings.types import SettingValueError
from app.models.search import Assessment, AssessmentState, Campaign, Job, Rubric, RubricStatus
from app.pipeline import conflicts, scoring
from app.pipeline.decisions import TIMING_GATES, Decision, GateDecision, decide
from app.pipeline.dry_run import ACTION_BY_VERDICT, sent_counters
from app.pipeline.filters import campaign_record, load_records
from app.schemas.json_types import AutomationPolicy, CampaignCriteria, RubricThresholds, UnknownDataPolicy

# Settings a preview may try out (the Autopilot limits and the global thresholds). Validated like a save.
PREVIEW_SETTINGS: frozenset[str] = frozenset({
    "automation.daily_cap", "automation.weekly_cap", "automation.quiet_hours_start", "automation.quiet_hours_end",
    "automation.default_mode", "scoring.threshold_shortlist", "scoring.threshold_tailor",
    "scoring.threshold_auto_apply",
})
# Gates about *when* a send happens, settled at send time: they do not decide whether a role qualifies.
SEND_TIME_GATES: frozenset[str] = TIMING_GATES | {"role_open"}
NOT_THROUGH = frozenset({"excluded", "review", "below_threshold"})


class PreviewError(ValueError):
    """The proposed change is not valid (422)."""


@dataclass(frozen=True)
class Proposal:
    """The change being previewed. ``None`` keeps what is in force."""

    automation: AutomationPolicy | None = None
    thresholds: RubricThresholds | None = None
    criteria: CampaignCriteria | None = None
    unknown_data_policy: UnknownDataPolicy | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class RoleOutcome:
    job: Job
    score: int | None
    decision: Decision | None
    action: str
    reason: str
    qualifies: bool = False
    held: bool = False

    @property
    def channel(self) -> str:
        method = (self.job.apply_method or "unknown").casefold()
        return "email" if method == "email" else ("other" if method == "unknown" else "browser")


@dataclass
class Line:
    would_apply: int = 0
    by_channel: dict[str, int] = field(default_factory=lambda: {"email": 0, "browser": 0, "other": 0})
    held: int = 0
    capped: int = 0
    qualifying: int = 0


@dataclass
class Change:
    outcome: RoleOutcome
    before: RoleOutcome
    kind: str  # newly_automatic / newly_blocked / changed
    reasons: list[str]


@dataclass
class Unknown:
    gate: str
    count: int
    message: str


@dataclass
class Caps:
    daily_cap: int
    weekly_cap: int
    sent_today: int
    sent_week: int
    run_now_would_send: int
    quiet_hours: str | None
    quiet_now: bool | None
    needs_open_check: int


@dataclass
class PreviewResult:
    window_days: int
    now: datetime
    jobs: int
    thresholds: dict[str, int]
    baseline_thresholds: dict[str, int]
    bins: list[tuple[int, int, int]]
    unscored: int
    line: Line
    baseline_line: Line
    run_now: dict[str, int]
    changes: list[Change]
    changes_total: int
    unknowns: list[Unknown]
    caps: Caps
    rows: list[RoleOutcome]


# ----- inputs -----------------------------------------------------------------------------------


def _settings_with(settings: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(settings)
    for key, raw in overrides.items():
        if key not in PREVIEW_SETTINGS:
            raise PreviewError(f"'{key}' cannot be previewed here")
        try:
            out[key] = get_def(key).coerce(raw)
        except SettingValueError as exc:
            raise PreviewError(str(exc)) from exc
    try:
        cross_check(out)
    except SettingValueError as exc:
        raise PreviewError(str(exc)) from exc
    return out


def _rubric_with(rubric: Rubric | None, thresholds: RubricThresholds | None) -> Rubric | None:
    if rubric is None or thresholds is None:
        return rubric
    return Rubric(id=rubric.id, family=rubric.family, name=rubric.name, version=rubric.version,
                  body=rubric.body.model_copy(update={"thresholds": thresholds}), status=RubricStatus.draft)


def effective_thresholds(rubric: Rubric | None, settings: Mapping[str, Any]) -> dict[str, int]:
    own = rubric.body.thresholds if rubric else RubricThresholds()
    return {name: int(getattr(own, name) if getattr(own, name) is not None else settings[f"scoring.threshold_{name}"])
            for name in ("shortlist", "tailor", "auto_apply")}


def _crecord_with(campaign: Campaign, proposal: Proposal) -> dict[str, Any]:
    crecord = campaign_record(campaign)
    if proposal.automation is not None:
        crecord["automation"] = proposal.automation.model_dump()
    if proposal.criteria is not None:
        crecord["criteria"] = proposal.criteria
    if proposal.unknown_data_policy is not None:
        crecord["unknown_data_policy"] = proposal.unknown_data_policy.model_dump()
    return crecord


# ----- one pass over the roles (the dry run's own order and counters) ----------------------------


def _blockers(decision: Decision, *, ignore: frozenset[str] = frozenset()) -> list[GateDecision]:
    return [g for g in decision.gates if g.layer == "automation" and g.mandatory and g.outcome != "pass"
            and g.gate not in SEND_TIME_GATES and g.gate not in ignore]


def _classify(outcome: RoleOutcome) -> None:
    d = outcome.decision
    if d is None or d.mode != "auto_apply" or d.verdict in NOT_THROUGH:
        return
    blockers = _blockers(d)
    if not blockers:
        outcome.qualifies = True
    elif [g.gate for g in blockers] == ["conflict_winner"] and outcome.job.conflict_state.value == "held":
        outcome.held = True


async def _pass(session: AsyncSession, campaign: Campaign, records: Sequence[tuple[Job, dict[str, Any]]],
                assessments: Mapping[uuid.UUID, Assessment], *, crecord: Mapping[str, Any], rubric: Rubric | None,
                settings: Mapping[str, Any], versions: Mapping[str, int], sent: Mapping[str, int],
                now: datetime) -> list[RoleOutcome]:
    """Mirrors ``dry_run.propose_actions``: best stored score first, simulated sends counted."""
    simulated: Counter[str] = Counter()
    simulated_live: Counter[str] = Counter()

    def rank(item: tuple[Job, Any]) -> tuple[int, str]:
        found = assessments.get(item[0].id)
        return (-(found.score if found and found.score is not None else -1), str(item[0].id))

    out: list[RoleOutcome] = []
    for job, record in sorted(records, key=rank):
        a = assessments.get(job.id)
        if a is None or a.state in (AssessmentState.parked, AssessmentState.pending):
            out.append(RoleOutcome(job, a.score if a else None, None, "parked",
                                   "Not scored yet: paused for budget or waiting for a rubric."))
            continue
        employer_counts = await conflicts.employer_counters(session, job, now=now)
        counters = {**employer_counts,
                    "employer_live": employer_counts.get("employer_live", 0) + simulated_live[job.canonical_employer],
                    "sent_today": sent["sent_today"] + simulated["today"],
                    "sent_week": sent["sent_week"] + simulated["week"]}
        decision = decide(scoring.decision_input(
            now=now, record=record, crecord=crecord, settings=settings, versions=versions, rubric=rubric,
            base_score=a.base_score, job=job, override=a.override.model_dump() if a.override else None,
            counters=counters, purpose="dry_run"))
        action = ACTION_BY_VERDICT[decision.verdict]
        if action == "apply":
            simulated["today"] += 1
            simulated["week"] += 1
            simulated_live[job.canonical_employer] += 1
            reason = "Every automation gate passes."
        else:
            blocking = [g for g in decision.gates if g.mandatory and g.outcome != "pass"
                        and g.layer in ("exclusion", "eligibility", "automation")]
            reason = blocking[0].reason if blocking else f"Verdict: {decision.verdict.replace('_', ' ')}."
            if job.conflict_state.value == "held":
                reason = job.conflict_note or "Held: outranked by another role at this employer."
        outcome = RoleOutcome(job, decision.effective_score, decision, action, reason)
        _classify(outcome)
        out.append(outcome)
    return out


def _line(rows: Sequence[RoleOutcome], settings: Mapping[str, Any]) -> Line:
    """Qualifying roles, then the caps day by day in the order the roles were found."""
    tz = ZoneInfo(settings["general.timezone"])
    daily, weekly = int(settings["automation.daily_cap"]), int(settings["automation.weekly_cap"])
    line = Line(held=sum(r.held for r in rows))
    qualifying = sorted((r for r in rows if r.qualifies),
                        key=lambda r: (r.job.created_at.astimezone(tz).date(), -(r.score or 0), str(r.job.id)))
    line.qualifying = len(qualifying)
    per_day: Counter[Any] = Counter()
    per_week: Counter[Any] = Counter()
    for r in qualifying:
        day = r.job.created_at.astimezone(tz).date()
        week = day.isocalendar()[:2]
        if per_day[day] >= daily or per_week[week] >= weekly:
            line.capped += 1
            continue
        per_day[day] += 1
        per_week[week] += 1
        line.would_apply += 1
        line.by_channel[r.channel] += 1
    return line


def _gate(decision: Decision | None, name: str) -> GateDecision | None:
    return None if decision is None else next((g for g in decision.gates if g.gate == name), None)


def _unknowns(rows: Sequence[RoleOutcome]) -> list[Unknown]:
    live = [r for r in rows if r.decision is None or r.decision.verdict != "excluded"]
    pay = sum(1 for r in live if (g := _gate(r.decision, "pay_stated")) and g.outcome == "unknown")
    elig = sum(1 for r in live if r.decision is not None and (
        r.decision.verdict == "review" or ((g := _gate(r.decision, "known_data")) and g.outcome == "unknown")))
    unscored = sum(1 for r in live if r.decision is None or r.decision.effective_score is None)
    group = sum(1 for r in live if (g := _gate(r.decision, "conflict_winner")) and g.outcome == "unknown")
    out = []
    for gate, count, what in (("pay_stated", pay, "unknown pay"),
                              ("known_data", elig, "unknown eligibility data (work rights, location, work model "
                                                   "or deadline)"),
                              ("score", unscored, "no score yet"),
                              ("conflict_winner", group, "an employer group not decided yet")):
        if count:
            subject = "1 role has" if count == 1 else f"{count} roles have"
            out.append(Unknown(gate, count, f"{subject} {what}: {'it' if count == 1 else 'they'} will never go "
                                            "automatically."))
    return out


def _changes(before: Sequence[RoleOutcome], after: Sequence[RoleOutcome]) -> list[Change]:
    old = {r.job.id: r for r in before}
    out = []
    for r in after:
        b = old.get(r.job.id)
        if b is None:
            continue
        if r.qualifies and not b.qualifies:
            resolved = [g.reason for g in (_blockers(b.decision) if b.decision else [])]
            if b.decision is not None and b.decision.verdict in NOT_THROUGH:
                resolved.insert(0, f"was {b.decision.verdict.replace('_', ' ')}")
            out.append(Change(r, b, "newly_automatic", resolved or [f"mode now {r.decision.mode}" if r.decision
                                                                     else ""]))
        elif b.qualifies and not r.qualifies:
            reasons = [g.reason for g in (_blockers(r.decision) if r.decision else [])]
            if r.decision is not None and r.decision.verdict in NOT_THROUGH:
                reasons.insert(0, r.reason)
            if r.decision is not None and r.decision.mode != "auto_apply":
                reasons.insert(0, f"effective mode {r.decision.mode}")
            out.append(Change(r, b, "newly_blocked", reasons or [r.reason]))
        elif r.action != b.action:
            out.append(Change(r, b, "changed", [r.reason]))
    order = {"newly_automatic": 0, "newly_blocked": 1, "changed": 2}
    out.sort(key=lambda c: (order[c.kind], -(c.outcome.score or -1), str(c.outcome.job.id)))
    return out


def _bins(rows: Sequence[RoleOutcome], width: int) -> tuple[list[tuple[int, int, int]], int]:
    scores = [r.score for r in rows if r.decision is not None and r.decision.verdict != "excluded"
              and r.score is not None]
    edges = list(range(0, 100, width))
    counts = Counter(min(s // width, len(edges) - 1) for s in scores)
    unscored = sum(1 for r in rows if r.score is None)
    return [(lo, min(lo + width, 100), counts.get(i, 0)) for i, lo in enumerate(edges)], unscored


def _quiet(settings: Mapping[str, Any], now: datetime) -> tuple[str | None, bool | None]:
    start, end, tz = (settings.get("automation.quiet_hours_start"), settings.get("automation.quiet_hours_end"),
                      settings.get("general.timezone"))
    if not start or not end or not tz:
        return None, None
    local = now.astimezone(ZoneInfo(tz)).strftime("%H:%M")
    inside = (start <= local or local < end) if start > end else (start <= local < end)
    return f"{start}-{end}", inside


# ----- entry point ------------------------------------------------------------------------------


async def preview(session: AsyncSession, campaign: Campaign, proposal: Proposal, *, days: int | None = None,
                  now: datetime | None = None, job_ids: Sequence[uuid.UUID] | None = None) -> PreviewResult:
    """Run the decision table twice over the window's roles: as things stand, and with the proposal."""
    now = now or utcnow()
    base_settings, versions = await scoring.setting_versions(session)
    days = int(days if days is not None else base_settings["preferences.preview_days"])
    if not 1 <= days <= get_def("preferences.preview_days").maximum:  # type: ignore[operator]
        raise PreviewError("the window must be between 1 and 365 days")
    settings = _settings_with(base_settings, proposal.settings)
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    new_rubric = _rubric_with(rubric, proposal.thresholds)
    thresholds = effective_thresholds(new_rubric, settings)
    if not thresholds["shortlist"] <= thresholds["tailor"] <= thresholds["auto_apply"]:
        raise PreviewError("thresholds must satisfy shortlist <= tailor <= auto-apply")

    stmt = (select(Assessment.job_id).join(Job, Job.id == Assessment.job_id)
            .where(Assessment.campaign_id == campaign.id, Job.merged_into_id.is_(None)))
    if job_ids is not None:
        stmt = stmt.where(Assessment.job_id.in_(list(job_ids)))
    else:
        stmt = stmt.where(Job.created_at >= now - timedelta(days=days))
    ids = list((await session.scalars(stmt.order_by(Job.created_at.desc())
                                      .limit(int(base_settings["preferences.preview_max_jobs"])))).all())
    records = await load_records(session, now=now, job_ids=ids)
    assessments = {a.job_id: a for a in (await session.scalars(select(Assessment).where(
        Assessment.campaign_id == campaign.id, Assessment.job_id.in_(ids)))).all()}
    sent = await sent_counters(session, now, base_settings["general.timezone"])

    common = {"settings": base_settings, "versions": versions, "sent": sent, "now": now}
    before = await _pass(session, campaign, records, assessments, crecord=campaign_record(campaign), rubric=rubric,
                         **common)
    common["settings"] = settings
    after = await _pass(session, campaign, records, assessments, crecord=_crecord_with(campaign, proposal),
                        rubric=new_rubric, **common)
    width = int(base_settings["preferences.histogram_bin"])
    bins, unscored = _bins(after, width)
    changes = _changes(before, after)
    quiet, quiet_now = _quiet(settings, now)
    caps = Caps(daily_cap=int(settings["automation.daily_cap"]), weekly_cap=int(settings["automation.weekly_cap"]),
                sent_today=sent["sent_today"], sent_week=sent["sent_week"],
                run_now_would_send=sum(r.action == "apply" for r in after), quiet_hours=quiet, quiet_now=quiet_now,
                needs_open_check=sum(1 for r in after if r.qualifies and (g := _gate(r.decision, "role_open"))
                                     and g.outcome != "pass"))
    shown = int(base_settings["preferences.preview_changes_shown"])
    return PreviewResult(
        window_days=days, now=now, jobs=len(after), thresholds=thresholds,
        baseline_thresholds=effective_thresholds(rubric, base_settings), bins=bins, unscored=unscored,
        line=_line(after, settings), baseline_line=_line(before, base_settings),
        run_now=dict(Counter(r.action for r in after)), changes=changes[:shown], changes_total=len(changes),
        unknowns=_unknowns(after), caps=caps, rows=after)
