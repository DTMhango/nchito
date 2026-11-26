"""Preference learning (F17): the owner's thumbs on matches become reviewable rubric suggestions.

- **Feedback is evidence, never a score change.** ``record_feedback`` stores the thumb, its reason
  chips and note with the score it was given against; nothing here writes an assessment or a rubric.
- **Suggestions are deterministic.** ``generate`` compares what the owner liked and disliked (thumbs
  plus real outcomes: replies and interviews count as liked, roles the owner skipped as disliked)
  criterion by criterion and facet by facet, and proposes concrete changes: reweight two criteria, a
  rubric penalty, a campaign bonus, a tag rule, a saved view or an exclusion. Each carries its
  evidence (which feedback, how many) and a backtest over recent roles through the decision table.
- **Owner-only ground is never touched.** No suggestion relaxes an exclusion or eligibility gate
  (rules are only ever appended, exclusions only added) and none touches pay floors, countries or
  locations, seniority, visa or relocation answers: ``guard`` refuses them at generation and again
  at acceptance, edited or not. Feedback about those areas is reported as an owner-only note.
- **Accepting is explicit and audited.** A rubric change creates a new rubric version (never an edit
  in place); a dismissed suggestion is not raised again for the same evidence.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.conditions import CampaignRule, ConditionSet, Group, RangeFilter, TextFilter, ValueFilter, evaluate
from app.core.settings import service as settings_service
from app.models.applications import Application, Stage
from app.models.base import ReviewState
from app.models.platform import AuditEvent
from app.models.preferences import CHANGE_ADAPTER, PreferenceFeedback, PreferenceSuggestion
from app.models.search import (
    Assessment,
    AssessmentState,
    Campaign,
    CampaignStatus,
    Job,
    Rubric,
    RubricStatus,
    SavedView,
    TagRule,
)
from app.pipeline import scoring
from app.pipeline.decisions import decide
from app.pipeline.filters import campaign_record, load_records
from app.schemas.json_types import (
    BacktestChangeRow,
    BonusChange,
    PenaltyChange,
    ReweightChange,
    RubricBody,
    RubricPenalty,
    SavedViewBody,
    SavedViewChange,
    SuggestionBacktest,
    SuggestionEvidence,
    TagRuleChange,
    TightenChange,
)

# ----- invariants (not settings) --------------------------------------------------------------

# Record paths a suggestion may never condition on: pay, where the role is (countries), seniority,
# work rights / visa and relocation. Those are the owner's own edits in the campaign and the Kit.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "pay", "pay_state", "pay_estimate", "location", "level", "seniority", "preferred_seniority",
    "kit_work_rights", "facets.where_must_live", "facets.remote_regions", "facets.work_rights",
    "facets.visa_sponsorship", "facets.relocation_required", "facets.relocation_assistance",
)
# A rubric criterion whose name mentions one of these is owner-only: its weight is never suggested.
FORBIDDEN_CRITERION_TERMS: tuple[str, ...] = (
    "pay", "salary", "compensation", "seniority", "level", "visa", "sponsor", "relocat", "country", "location",
    "work right",
)
# Reason chips about owner-only ground: reported, never turned into a change.
OWNER_ONLY_REASONS: dict[str, str] = {"too_junior": "seniority", "too_senior": "seniority", "pay": "pay",
                                      "location": "location"}
OWNER_ONLY_WHERE = {"seniority": "the campaign's seniority criteria", "pay": "the campaign's pay floors",
                    "location": "the campaign's locations"}
# Facets the analysis looks at, with the reason chips that point at each.
ANALYSED_FACETS: dict[str, str] = {
    "facets.work_model": "work model", "facets.remote_scope": "remote scope",
    "facets.employment_type": "employment type", "facets.hiring_arrangement": "hiring arrangement",
    "facets.industry": "industry", "facets.required_skills": "required skill", "function": "function",
}
REASON_FACETS: dict[str, tuple[str, ...]] = {
    "wrong_stack": ("facets.required_skills",),
    "employer_type": ("facets.industry", "facets.hiring_arrangement", "facets.employment_type"),
    "commute_remote": ("facets.work_model", "facets.remote_scope"),
}
# Outcomes that count as evidence: a reply or an interview is liked; a role the owner skipped is disliked.
LIKED_STAGES = frozenset({Stage.screening, Stage.interview, Stage.offer, Stage.accepted})
DISLIKED_STAGES = frozenset({Stage.skipped})
PASSING = frozenset({"shortlist", "tailor", "ask_owner", "auto_apply"})
DROPPED = frozenset({"excluded", "below_threshold"})
NOT_STATED = "not_stated"


class FeedbackError(ValueError):
    """Bad feedback input (422)."""


class ForbiddenChange(ValueError):
    """A change a suggestion may not make (422): owner-only ground or a relaxing edit."""


class StaleSuggestion(ValueError):
    """The suggestion no longer applies (409): already decided, or the rubric moved on."""


# ----- feedback ---------------------------------------------------------------------------------


async def record_feedback(session: AsyncSession, job: Job, *, campaign_id: uuid.UUID | None, verdict: str,
                          reasons: Sequence[str], note: str | None, actor: str) -> PreferenceFeedback:
    """Store (or replace) the owner's thumb on one match. Changes no score: evidence only."""
    settings = await settings_service.values(session)
    note = (note or "").strip() or None
    if note and len(note) > int(settings["preferences.note_max_length"]):
        raise FeedbackError(f"the note is longer than {settings['preferences.note_max_length']} characters")
    assessment = await _assessment_for(session, job.id, campaign_id)
    if campaign_id is None and assessment is not None:
        campaign_id = assessment.campaign_id
    elif campaign_id is not None and await session.get(Campaign, campaign_id) is None:
        raise FeedbackError("campaign not found")
    stmt = select(PreferenceFeedback).where(PreferenceFeedback.job_id == job.id).with_for_update()
    stmt = stmt.where(PreferenceFeedback.campaign_id.is_(None) if campaign_id is None
                      else PreferenceFeedback.campaign_id == campaign_id)
    row = await session.scalar(stmt)
    previous = None if row is None else {"verdict": row.verdict, "reasons": list(row.reasons)}
    if row is None:
        row = PreferenceFeedback(job_id=job.id, campaign_id=campaign_id, verdict=verdict, actor=actor)
        session.add(row)
    row.verdict, row.reasons, row.note, row.actor = verdict, sorted(set(reasons)), note, actor
    row.score_at = assessment.score if assessment else None
    row.rubric_version = assessment.rubric_version if assessment else None
    await session.flush()
    await audit.record(session, actor=actor, action="preference.feedback", subject_type="job", subject_id=job.id,
                       detail={"campaign_id": str(campaign_id) if campaign_id else None, "verdict": verdict,
                               "reasons": row.reasons, "note_chars": len(note or ""), "previous": previous})
    return row


async def withdraw_feedback(session: AsyncSession, job_id: uuid.UUID, campaign_id: uuid.UUID | None, *,
                            actor: str) -> bool:
    stmt = select(PreferenceFeedback).where(PreferenceFeedback.job_id == job_id)
    stmt = stmt.where(PreferenceFeedback.campaign_id.is_(None) if campaign_id is None
                      else PreferenceFeedback.campaign_id == campaign_id)
    row = await session.scalar(stmt)
    if row is None:
        return False
    await session.delete(row)
    await audit.record(session, actor=actor, action="preference.feedback_withdrawn", subject_type="job",
                       subject_id=job_id, detail={"campaign_id": str(campaign_id) if campaign_id else None,
                                                  "verdict": row.verdict})
    return True


async def _assessment_for(session: AsyncSession, job_id: uuid.UUID, campaign_id: uuid.UUID | None
                          ) -> Assessment | None:
    stmt = select(Assessment).where(Assessment.job_id == job_id)
    if campaign_id is not None:
        stmt = stmt.where(Assessment.campaign_id == campaign_id)
    return await session.scalar(stmt.order_by(Assessment.score.desc().nulls_last()).limit(1))


# ----- signals ----------------------------------------------------------------------------------


@dataclass
class Signal:
    """One piece of evidence: a liked or disliked role, with what the rubric said about it."""

    job_id: uuid.UUID
    record: Mapping[str, Any]
    liked: bool
    ratings: dict[str, int]
    score: int | None
    reasons: list[str] = field(default_factory=list)
    note: str | None = None
    feedback_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None

    @property
    def ref(self) -> tuple[str, str]:
        return ("f", str(self.feedback_id)) if self.feedback_id else ("a", str(self.application_id))


async def signals(session: AsyncSession, campaign: Campaign, *, now: datetime) -> list[Signal]:
    """Feedback on this campaign's matches plus real outcomes of its applications. Feedback wins when
    both exist for one role (the owner said so directly)."""
    feedback = list((await session.scalars(select(PreferenceFeedback).where(
        PreferenceFeedback.campaign_id == campaign.id))).all())
    apps = list((await session.scalars(select(Application).where(
        Application.campaign_id == campaign.id,
        Application.stage.in_(list(LIKED_STAGES | DISLIKED_STAGES))))).all())
    said = {f.job_id for f in feedback}
    apps = [a for a in apps if a.job_id not in said]
    ids = list(said | {a.job_id for a in apps})
    if not ids:
        return []
    records = {job.id: record for job, record in await load_records(session, now=now, job_ids=ids,
                                                                      include_merged=True)}
    assessments = {a.job_id: a for a in (await session.scalars(select(Assessment).where(
        Assessment.campaign_id == campaign.id, Assessment.job_id.in_(ids)))).all()}

    def rated(job_id: uuid.UUID) -> tuple[dict[str, int], int | None]:
        a = assessments.get(job_id)
        if a is None or a.state != AssessmentState.scored:
            return {}, None
        return {r.criterion: r.rating for r in a.ratings}, a.score

    out: list[Signal] = []
    for f in feedback:
        if f.job_id not in records:
            continue
        ratings, score = rated(f.job_id)
        out.append(Signal(f.job_id, records[f.job_id], f.verdict == "up", ratings, score, list(f.reasons), f.note,
                          feedback_id=f.id))
    for a in apps:
        if a.job_id not in records:
            continue
        ratings, score = rated(a.job_id)
        out.append(Signal(a.job_id, records[a.job_id], a.stage in LIKED_STAGES, ratings, score,
                          application_id=a.id))
    return out


# ----- guard ------------------------------------------------------------------------------------


def _forbidden_path(path: str) -> bool:
    return any(path == p or path.startswith(p + ".") for p in FORBIDDEN_PATHS)


def forbidden_criterion(name: str) -> bool:
    low = name.casefold()
    return any(term in low for term in FORBIDDEN_CRITERION_TERMS)


def _walk(conditions: Iterable[Any]) -> Iterable[Any]:
    for cond in conditions:
        if isinstance(cond, Group):
            yield from _walk(cond.conditions)
        else:
            yield cond


def guard_conditions(conditions: ConditionSet) -> None:
    """Suggestions condition only on value and range filters over permitted facets."""
    leaves = list(_walk(conditions.root.conditions))
    if not leaves:
        raise ForbiddenChange("a suggested rule needs at least one condition")
    for cond in leaves:
        if isinstance(cond, TextFilter):
            raise ForbiddenChange("text-search rules are owner-only edits; add them in the campaign editor")
        if isinstance(cond, ValueFilter | RangeFilter) and _forbidden_path(cond.facet):
            raise ForbiddenChange(f"'{cond.facet}' is owner-only ground (pay, countries, seniority, visa, "
                                  "relocation); change it in the campaign editor or the Kit")


def guard(change: Any, rubric: Rubric | None) -> None:
    """Refuse anything a suggestion may not do. Called at generation and again at acceptance."""
    if isinstance(change, ReweightChange):
        if rubric is None:
            raise ForbiddenChange("the campaign has no rubric")
        current = {c.name: c.weight for c in rubric.body.criteria}
        if set(change.weights) != set(current):
            raise ForbiddenChange("a reweight keeps the rubric's criteria; add or remove criteria in the editor")
        if any(w < 0 for w in change.weights.values()) or sum(change.weights.values()) != 100:
            raise ForbiddenChange("weights must be non-negative and sum to 100")
        touched = [n for n, w in change.weights.items() if w != current[n] and forbidden_criterion(n)]
        if touched:
            raise ForbiddenChange(f"criterion '{touched[0]}' is owner-only ground; change it in the rubric editor")
        return
    if isinstance(change, PenaltyChange | BonusChange | TagRuleChange | SavedViewChange | TightenChange):
        guard_conditions(change.conditions)
        if isinstance(change, PenaltyChange) and rubric is None:
            raise ForbiddenChange("the campaign has no rubric")
        return
    raise ForbiddenChange("unknown change")


# ----- analysis ---------------------------------------------------------------------------------


@dataclass
class Candidate:
    kind: str
    target: str
    title: str
    change: Any
    evidence: SuggestionEvidence
    refs: list[tuple[str, str]]


@dataclass
class OwnerOnlyNote:
    area: str
    down: int
    feedback_ids: list[str]
    message: str


@dataclass
class Analysis:
    candidates: list[Candidate]
    owner_only: list[OwnerOnlyNote]
    up: int
    down: int


def _norm(value: Any) -> str:
    return str(value).strip().casefold()


def facet_values(record: Mapping[str, Any], path: str) -> list[str]:
    cur: Any = record
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, Mapping) else None
    if isinstance(cur, Mapping) and "value" in cur:
        cur = cur["value"]
    items = cur if isinstance(cur, list) else [cur]
    return sorted({_norm(v) for v in items if v not in (None, "", NOT_STATED)})


def _evidence(group: Sequence[Signal], settings: Mapping[str, Any], summary: str) -> SuggestionEvidence:
    reasons: dict[str, int] = {}
    for s in group:
        for r in s.reasons:
            reasons[r] = reasons.get(r, 0) + 1
    shown = int(settings["preferences.evidence_notes_shown"])
    return SuggestionEvidence(
        up=sum(s.liked for s in group), down=sum(not s.liked for s in group),
        feedback_ids=sorted(str(s.feedback_id) for s in group if s.feedback_id),
        application_ids=sorted(str(s.application_id) for s in group if s.application_id),
        reasons=reasons, notes=[s.note for s in group if s.note][:shown], summary=summary)


def _about(signal: Signal, path: str) -> bool:
    """A dislike counts against a facet when it gave no reason, or a reason that points at the facet."""
    if signal.liked or not signal.reasons:
        return True
    return any(path in REASON_FACETS.get(r, ()) for r in signal.reasons)


def _cond(path: str, value: str) -> ConditionSet:
    return ConditionSet(root=Group(conditions=[ValueFilter(facet=path, include=[value])]))


def _slug(value: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in value.casefold()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:50] or "pattern"


def owner_only_notes(group: Sequence[Signal]) -> list[OwnerOnlyNote]:
    notes = []
    for area in sorted(set(OWNER_ONLY_REASONS.values())):
        hits = [s for s in group if not s.liked and any(OWNER_ONLY_REASONS.get(r) == area for r in s.reasons)]
        if hits:
            chips = sorted({r for s in hits for r in s.reasons if OWNER_ONLY_REASONS.get(r) == area})
            notes.append(OwnerOnlyNote(
                area, len(hits), sorted(str(s.feedback_id) for s in hits if s.feedback_id),
                f"{len(hits)} thumbs down gave {', '.join(c.replace('_', ' ') for c in chips)} as the reason. "
                f"Suggestions never change {area}: edit {OWNER_ONLY_WHERE[area]} yourself if you agree."))
    return notes


def _reweight(group: Sequence[Signal], rubric: Rubric, settings: Mapping[str, Any]) -> Candidate | None:
    need, gap_min = int(settings["preferences.min_evidence"]), float(settings["preferences.min_rating_gap"])
    rated = [s for s in group if s.ratings]
    liked, disliked = [s for s in rated if s.liked], [s for s in rated if not s.liked]
    if len(liked) < need or len(disliked) < need:
        return None
    gaps: dict[str, tuple[float, float, float]] = {}
    for c in rubric.body.criteria:
        if forbidden_criterion(c.name):
            continue
        up = mean(s.ratings.get(c.name, 0) for s in liked)
        down = mean(s.ratings.get(c.name, 0) for s in disliked)
        gaps[c.name] = (round(up - down, 2), round(up, 1), round(down, 1))
    if len(gaps) < 2:
        return None
    order = sorted(gaps, key=lambda n: (-gaps[n][0], n))
    best, weights = order[0], {c.name: c.weight for c in rubric.body.criteria}
    lower = [n for n in reversed(order) if n != best and weights[n] > 0]
    if not lower:
        return None
    worst = lower[0]
    if gaps[best][0] < gap_min or gaps[best][0] - gaps[worst][0] < gap_min:
        return None
    step = min(int(settings["preferences.reweight_step"]), weights[worst])
    new = {**weights, best: weights[best] + step, worst: weights[worst] - step}
    b, w = gaps[best], gaps[worst]
    summary = (f"Roles you liked rate {b[1]} on '{best}' against {b[2]} for roles you disliked; '{worst}' "
               f"separates them less ({w[1]} vs {w[2]}). Moving {step} weight points from '{worst}' to '{best}'.")
    return Candidate("reweight_criterion", f"{best}>{worst}",
                     f"Weigh '{best}' more ({weights[best]} to {new[best]}) and '{worst}' less "
                     f"({weights[worst]} to {new[worst]})",
                     ReweightChange(weights=new), _evidence(rated, settings, summary), [s.ref for s in rated])


def _patterns(group: Sequence[Signal], rubric: Rubric | None, settings: Mapping[str, Any]) -> list[Candidate]:
    need = int(settings["preferences.min_evidence"])
    need_exclude = int(settings["preferences.exclude_min_evidence"])
    out: list[Candidate] = []
    for path, label in ANALYSED_FACETS.items():
        values = sorted({v for s in group for v in facet_values(s.record, path)})
        for value in values:
            with_value = [s for s in group if value in facet_values(s.record, path)]
            liked = [s for s in with_value if s.liked]
            disliked = [s for s in with_value if not s.liked and _about(s, path)]
            target, cond = f"{path}={value}", _cond(path, value)
            if len(disliked) >= need and not liked:
                ev = _evidence(disliked, settings, f"You disliked {len(disliked)} role(s) with {label} '{value}' "
                                                   "and liked none.")
                refs = [s.ref for s in disliked]
                if rubric is not None:
                    points = int(settings["preferences.penalty_points"])
                    out.append(Candidate("add_penalty", target, f"Penalise {label} '{value}' by {points} points",
                                         PenaltyChange(name=f"Disliked {label}: {value}", points=points,
                                                       conditions=cond), ev, refs))
                if len(disliked) >= need_exclude:
                    out.append(Candidate("tighten_filter", target, f"Exclude roles with {label} '{value}'",
                                         TightenChange(reason=f"Disliked {label}: {value}", conditions=cond),
                                         ev, refs))
            elif len(liked) >= need and not [s for s in with_value if not s.liked]:
                ev = _evidence(liked, settings, f"You liked {len(liked)} role(s) with {label} '{value}' and "
                                                "disliked none.")
                refs = [s.ref for s in liked]
                points = int(settings["preferences.bonus_points"])
                out.append(Candidate("add_bonus", target, f"Add {points} points for {label} '{value}'",
                                     BonusChange(reason=f"Liked {label}: {value}", points=points, conditions=cond),
                                     ev, refs))
                out.append(Candidate("add_tag_rule", target, f"Tag roles with {label} '{value}' as liked",
                                     TagRuleChange(tag=f"liked-{_slug(value)}", conditions=cond), ev, refs))
                if any("more_like_this" in s.reasons for s in liked):
                    out.append(Candidate("add_saved_view", target, f"Save a view: more like {label} '{value}'",
                                         SavedViewChange(name=f"More like this: {value}"[:120], conditions=cond),
                                         ev, refs))
    return out


def analyse(group: Sequence[Signal], rubric: Rubric | None, settings: Mapping[str, Any]) -> Analysis:
    """Pure: the candidates the evidence supports. Every candidate passes ``guard``."""
    candidates: list[Candidate] = []
    if rubric is not None and (c := _reweight(group, rubric, settings)) is not None:
        candidates.append(c)
    candidates += _patterns(group, rubric, settings)
    safe = []
    for c in candidates:
        try:
            guard(c.change, rubric)
        except ForbiddenChange:
            continue
        safe.append(c)
    return Analysis(safe, owner_only_notes(group), sum(s.liked for s in group), sum(not s.liked for s in group))


def evidence_key(campaign_id: uuid.UUID, kind: str, target: str, refs: Iterable[tuple[str, str]]) -> str:
    raw = json.dumps([str(campaign_id), kind, target, sorted(set(refs))])
    return hashlib.sha256(raw.encode()).hexdigest()


# ----- already in place? --------------------------------------------------------------------------


async def _already_in_place(session: AsyncSession, campaign: Campaign, rubric: Rubric | None, change: Any) -> bool:
    if isinstance(change, BonusChange | TightenChange):
        effect = "bonus" if isinstance(change, BonusChange) else "exclude"
        return any(r.effect == effect and r.conditions == change.conditions for r in campaign.criteria.rules)
    if isinstance(change, PenaltyChange):
        return rubric is not None and any(p.conditions == change.conditions for p in rubric.body.penalties)
    if isinstance(change, TagRuleChange):
        return await session.scalar(select(TagRule.id).where(TagRule.tag == change.tag).limit(1)) is not None
    if isinstance(change, SavedViewChange):
        return await session.scalar(select(SavedView.id).where(SavedView.name == change.name).limit(1)) is not None
    return False


# ----- backtest ---------------------------------------------------------------------------------


def _with_change(rubric: Rubric | None, crecord: Mapping[str, Any], change: Any
                 ) -> tuple[Rubric | None, dict[str, Any]]:
    """The rubric and campaign record as they would be after the change (nothing is saved)."""
    crec = dict(crecord)
    if isinstance(change, ReweightChange | PenaltyChange) and rubric is not None:
        body = rubric.body.model_dump()
        if isinstance(change, ReweightChange):
            body["criteria"] = [{**c, "weight": change.weights[c["name"]]} for c in body["criteria"]]
        else:
            body["penalties"] = [*body["penalties"], RubricPenalty(name=change.name, points=change.points,
                                                                   conditions=change.conditions).model_dump()]
        rubric = Rubric(id=rubric.id, family=rubric.family, name=rubric.name, version=rubric.version + 1,
                        body=RubricBody.model_validate(body), status=RubricStatus.draft)
    elif isinstance(change, BonusChange | TightenChange):
        rule = (CampaignRule(effect="bonus", points=change.points, conditions=change.conditions, reason=change.reason)
                if isinstance(change, BonusChange)
                else CampaignRule(effect="exclude", conditions=change.conditions, reason=change.reason))
        criteria = crecord["criteria"]
        crec["criteria"] = criteria.model_copy(update={"rules": [*criteria.rules, rule]})
    return rubric, crec


async def backtest(session: AsyncSession, campaign: Campaign, change: Any, *, now: datetime | None = None
                   ) -> SuggestionBacktest:
    """Replay recent roles (``preferences.backtest_days``) with and without the change through the
    decision table. Rubric changes re-weigh the stored per-criterion ratings: no model calls."""
    now = now or utcnow()
    settings, versions = await scoring.setting_versions(session)
    days = int(settings["preferences.backtest_days"])
    ids = list((await session.scalars(select(Assessment.job_id).join(Job, Job.id == Assessment.job_id).where(
        Assessment.campaign_id == campaign.id, Job.created_at >= now - timedelta(days=days),
        Job.merged_into_id.is_(None)))).all())
    records = await load_records(session, now=now, job_ids=ids)
    assessments = {a.job_id: a for a in (await session.scalars(select(Assessment).where(
        Assessment.campaign_id == campaign.id, Assessment.job_id.in_(ids)))).all()}
    applied = set((await session.scalars(select(Application.job_id).where(
        Application.job_id.in_(ids), Application.applied_at.is_not(None)))).all())
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    crecord = campaign_record(campaign)
    new_rubric, new_crecord = _with_change(rubric, crecord, change)
    conditions = getattr(change, "conditions", None)
    result = SuggestionBacktest(window_days=days, jobs=len(records))
    for job, record in records:
        a = assessments[job.id]
        if conditions is not None and evaluate(conditions, record):
            result.matched += 1
        scored = a.state == AssessmentState.scored
        override = a.override.model_dump() if a.override else None
        old_base = a.base_score if scored else None
        new_base = old_base
        if scored and new_rubric is not rubric and new_rubric is not None and a.ratings:
            new_base, _ = scoring.apply_penalties(new_rubric.body, scoring.weighted_score(new_rubric.body, a.ratings),
                                                  record)
        old = decide(scoring.decision_input(now=now, record=record, crecord=crecord, settings=settings,
                                            versions=versions, rubric=rubric, base_score=old_base, job=job,
                                            override=override, purpose="dry_run"))
        new = decide(scoring.decision_input(now=now, record=record, crecord=new_crecord, settings=settings,
                                            versions=versions, rubric=new_rubric, base_score=new_base, job=job,
                                            override=override, purpose="dry_run"))
        row = BacktestChangeRow(job_id=str(job.id), title=job.title, employer=job.employer,
                                old_score=old.effective_score, new_score=new.effective_score,
                                old_verdict=old.verdict, new_verdict=new.verdict)
        result.score_changed += int(old.effective_score != new.effective_score)
        if old.verdict not in PASSING and new.verdict in PASSING:
            result.newly_pass.append(row)
        elif old.verdict in PASSING and new.verdict not in PASSING:
            result.newly_drop.append(row)
        if job.id in applied and new.verdict in DROPPED and old.verdict not in DROPPED:
            result.excluded_past_applications.append(row)
    return result


# ----- generate ---------------------------------------------------------------------------------


@dataclass
class GenerateResult:
    created: list[PreferenceSuggestion]
    kept: int
    owner_only: list[OwnerOnlyNote]
    up: int
    down: int


async def generate(session: AsyncSession, campaign: Campaign, *, actor: str, now: datetime | None = None
                   ) -> GenerateResult:
    """Turn the campaign's evidence into open suggestions. Idempotent: the same evidence raises nothing
    new, and a dismissed suggestion is never raised again for it. An open suggestion about the same
    thing with older evidence is superseded."""
    now = now or utcnow()
    settings = await settings_service.values(session)
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    analysis = analyse(await signals(session, campaign, now=now), rubric, settings)
    existing = list((await session.scalars(select(PreferenceSuggestion).where(
        PreferenceSuggestion.campaign_id == campaign.id))).all())
    known = {s.evidence_key for s in existing}
    created, kept = [], 0
    for c in analysis.candidates:
        key = evidence_key(campaign.id, c.kind, c.target, c.refs)
        if key in known:
            kept += 1
            continue
        if await _already_in_place(session, campaign, rubric, c.change):
            continue
        for old in existing:
            if old.status == "open" and old.kind == c.kind and old.target == c.target:
                old.status, old.decided_at, old.decided_by = "superseded", now, actor
        row = PreferenceSuggestion(campaign_id=campaign.id, kind=c.kind, target=c.target[:200], title=c.title[:300],
                                   change=c.change.model_dump(mode="json"), evidence=c.evidence, evidence_key=key,
                                   rubric_id=rubric.id if rubric else None, status="open", result={})
        row.backtest = await backtest(session, campaign, c.change, now=now)
        session.add(row)
        created.append(row)
        known.add(key)
    await session.flush()
    await audit.record(session, actor=actor, action="preferences.analysed", subject_type="campaign",
                       subject_id=campaign.id, detail={"up": analysis.up, "down": analysis.down,
                                                       "created": len(created), "kept": kept,
                                                       "owner_only": [n.area for n in analysis.owner_only]})
    return GenerateResult(created, kept, analysis.owner_only, analysis.up, analysis.down)


async def analyse_due(session: AsyncSession, *, now: datetime | None = None) -> list[uuid.UUID]:
    """The periodic pass: every active campaign whose evidence changed since its last analysis, at most
    once per ``preferences.analysis_every_hours`` (0 turns the periodic pass off)."""
    now = now or utcnow()
    hours = int((await settings_service.values(session))["preferences.analysis_every_hours"])
    if hours <= 0:
        return []
    done = []
    for campaign in (await session.scalars(select(Campaign).where(Campaign.status == CampaignStatus.active))).all():
        last = await session.scalar(select(func.max(AuditEvent.created_at)).where(
            AuditEvent.action == "preferences.analysed", AuditEvent.subject_id == str(campaign.id)))
        if last is not None and now - last < timedelta(hours=hours):
            continue
        newest = max(filter(None, [
            await session.scalar(select(func.max(PreferenceFeedback.updated_at)).where(
                PreferenceFeedback.campaign_id == campaign.id)),
            await session.scalar(select(func.max(Application.updated_at)).where(
                Application.campaign_id == campaign.id))]), default=None)
        if newest is None or (last is not None and newest <= last):
            continue
        await generate(session, campaign, actor="system", now=now)
        done.append(campaign.id)
    return done


# ----- accept / dismiss -------------------------------------------------------------------------


def parse_change(raw: Mapping[str, Any]) -> Any:
    return CHANGE_ADAPTER.validate_python(raw)


async def accept(session: AsyncSession, suggestion: PreferenceSuggestion, *, actor: str,
                 change: Mapping[str, Any] | None = None, note: str | None = None) -> PreferenceSuggestion:
    """Apply the suggestion (or the owner's edit of it). A rubric change creates a new rubric version.
    Rules are only ever appended. Audited."""
    if suggestion.status != "open":
        raise StaleSuggestion(f"this suggestion is already {suggestion.status}")
    campaign = await session.get(Campaign, suggestion.campaign_id, with_for_update=True)
    assert campaign is not None
    parsed = parse_change(change if change is not None else suggestion.change)
    if parsed.kind != suggestion.kind:
        raise ForbiddenChange("an edit keeps the kind of change")
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    if isinstance(parsed, ReweightChange) and (rubric is None or rubric.id != suggestion.rubric_id):
        raise StaleSuggestion("the rubric changed since this suggestion was made; analyse again")
    guard(parsed, rubric)
    result: dict[str, Any]
    if isinstance(parsed, ReweightChange | PenaltyChange):
        draft, _ = _with_change(rubric, campaign_record(campaign), parsed)
        assert draft is not None and rubric is not None
        new = await scoring.activate(session, Rubric(family=rubric.family, name=rubric.name, body=draft.body,
                                                     status=RubricStatus.draft))
        result = {"rubric_id": str(new.id), "rubric_version": new.version, "from_version": rubric.version}
        await audit.record(session, actor=actor, action="rubric.activated", subject_type="rubric", subject_id=new.id,
                           detail={"from": str(rubric.id), "version": new.version,
                                   "suggestion_id": str(suggestion.id)})
    elif isinstance(parsed, BonusChange | TightenChange):
        rule = (CampaignRule(effect="bonus", points=parsed.points, conditions=parsed.conditions, reason=parsed.reason)
                if isinstance(parsed, BonusChange)
                else CampaignRule(effect="exclude", conditions=parsed.conditions, reason=parsed.reason))
        campaign.criteria = campaign.criteria.model_copy(update={"rules": [*campaign.criteria.rules, rule]})
        # A new rule is confirmed by the owner like any other (principle 2): the mode lock holds until then.
        campaign.unconfirmed_items = sorted(set(campaign.unconfirmed_items) | {"rules"})
        campaign.review_state, campaign.confirmed_at = ReviewState.needs_review, None
        result = {"rule_index": len(campaign.criteria.rules) - 1, "effect": rule.effect}
        await audit.record(session, actor=actor, action="campaign.rule_added", subject_type="campaign",
                           subject_id=campaign.id, detail={"effect": rule.effect, "reason": rule.reason,
                                                           "suggestion_id": str(suggestion.id)})
    elif isinstance(parsed, TagRuleChange):
        tag_rule = TagRule(tag=parsed.tag, conditions=parsed.conditions, enabled=True)
        session.add(tag_rule)
        await session.flush()
        tagged = 0
        for job, record in await load_records(session, now=utcnow()):
            if parsed.tag not in job.tags and evaluate(parsed.conditions, record):
                job.tags = [*job.tags, parsed.tag]
                tagged += 1
        result = {"tag_rule_id": str(tag_rule.id), "tagged": tagged}
    else:
        view = SavedView(name=parsed.name, body=SavedViewBody(conditions=parsed.conditions))
        session.add(view)
        await session.flush()
        result = {"saved_view_id": str(view.id)}
    edited = change is not None and parsed.model_dump(mode="json") != suggestion.change
    suggestion.change = parsed.model_dump(mode="json")
    suggestion.status, suggestion.decided_by, suggestion.decided_at = "accepted", actor, utcnow()
    suggestion.decision_note, suggestion.result = note, result
    await session.flush()
    await audit.record(session, actor=actor, action="preference.suggestion_accepted", subject_type="campaign",
                       subject_id=campaign.id, detail={"suggestion_id": str(suggestion.id), "kind": suggestion.kind,
                                                       "edited": edited, "result": result,
                                                       "evidence": {"up": suggestion.evidence.up,
                                                                    "down": suggestion.evidence.down}})
    return suggestion


async def accepted_exclusion(session: AsyncSession, job_id: uuid.UUID, campaign_ids: Iterable[uuid.UUID]
                             ) -> str | None:
    """The reason of an exclusion the owner accepted from feedback (a ``tighten_filter`` suggestion whose
    rule is still in the campaign) that this job matches, or None. Its stored assessment predates the
    rule, so callers acting on older matches (bulk tailoring and send) check it here."""
    ids = list(dict.fromkeys(campaign_ids))
    if not ids:
        return None
    accepted = (await session.scalars(select(PreferenceSuggestion).where(
        PreferenceSuggestion.campaign_id.in_(ids), PreferenceSuggestion.kind == "tighten_filter",
        PreferenceSuggestion.status == "accepted"))).all()
    if not accepted:
        return None
    records = await load_records(session, now=utcnow(), job_ids=[job_id], include_merged=True)
    if not records:
        return None
    record = records[0][1]
    for suggestion in accepted:
        change = CHANGE_ADAPTER.validate_python(suggestion.change)
        campaign = await session.get(Campaign, suggestion.campaign_id)
        live = campaign is not None and any(
            r.effect == "exclude" and r.conditions == change.conditions for r in campaign.criteria.rules)
        if live and evaluate(change.conditions, record):
            return f"matches the exclusion you accepted from feedback: {change.reason}"
    return None


async def dismiss(session: AsyncSession, suggestion: PreferenceSuggestion, *, actor: str, note: str | None = None
                  ) -> PreferenceSuggestion:
    if suggestion.status != "open":
        raise StaleSuggestion(f"this suggestion is already {suggestion.status}")
    suggestion.status, suggestion.decided_by, suggestion.decided_at = "dismissed", actor, utcnow()
    suggestion.decision_note = note
    await session.flush()
    await audit.record(session, actor=actor, action="preference.suggestion_dismissed", subject_type="campaign",
                       subject_id=suggestion.campaign_id, detail={"suggestion_id": str(suggestion.id),
                                                                  "kind": suggestion.kind})
    return suggestion
