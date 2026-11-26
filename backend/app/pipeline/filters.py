"""Campaign criteria and the Matches filter builder over job facets (DESIGN.md 6.1, 7).

One condition engine (``core/conditions.py``) serves saved views, rule tags, campaign rules and
rubric penalties, so a view copied into a campaign as a rule matches exactly the same jobs.

- ``job_record`` turns a ``Job`` into the plain dict the engine and the decision table read.
  Facet values are unwrapped (the evidence quote is kept apart under ``evidence``); skills are
  canonicalised through the alias table, so changing an alias re-evaluates without a re-fetch.
- ``filter_results`` renders the decision table's exclusion and eligibility gates as the
  pass / fail / unknown ``FilterResult`` list stored on an assessment.
- ``query_jobs`` applies the Matches grammar (include / exclude / not stated per facet,
  any / all within a facet, free text, group-by with counts, sort, pagination). It only reads:
  **a view only changes what is shown.**
- ``FACETS`` is the catalogue of everything filterable, for the filter builder.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conditions import (
    NOT_STATED,
    CampaignRule,
    ConditionSet,
    Group,
    TextFilter,
    evaluate,
    explain,
    group_by,
    lookup,
)
from app.kit import work_rights
from app.kit.answers import AnswerRecord
from app.models.bulk import EmployerPolicy
from app.models.search import (
    Assessment,
    Campaign,
    EmployerAlias,
    Job,
    JobSighting,
    PayEstimate,
    SkillAlias,
    Source,
    WatchedEmployer,
)
from app.pipeline.decisions import Decision
from app.schemas.json_types import FilterResult, SavedViewBody

# ----- records ----------------------------------------------------------------------------


def _val(value: Any) -> Any:
    """Enum member or its raw string (unflushed rows still hold the string)."""
    return getattr(value, "value", value)


def _unwrap(value: Any) -> Any:
    if isinstance(value, Mapping) and set(value) <= {"value", "evidence"} and "value" in value:
        return value["value"]
    return value


def _canon_skills(skills: Iterable[str], aliases: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    for skill in skills:
        canonical = aliases.get(skill.strip().casefold(), skill.strip())
        if canonical not in out:
            out.append(canonical)
    return out


def job_record(
    job: Job,
    *,
    now: datetime,
    estimate: PayEstimate | None = None,
    sources: Sequence[str] = (),
    skill_aliases: Mapping[str, str] | None = None,
    employer_aliases: Mapping[str, str] | None = None,
    best_score: int | None = None,
    always_ask_first: bool = False,
    never_apply: str | None = None,
    kit_answers: Sequence[AnswerRecord] | None = None,
) -> dict[str, Any]:
    """The plain-dict view of a job for conditions and the decision table. ``kit_answers`` (matcher
    records of the answer bank) lets the table read the owner's work rights, sponsorship and relocation."""
    aliases = skill_aliases or {}
    dumped = job.facets.model_dump(mode="python")
    facets = {key: _unwrap(value) for key, value in dumped.items()}
    evidence = {key: value.get("evidence") for key, value in dumped.items()
                if isinstance(value, Mapping) and value.get("evidence")}
    for key in ("required_skills", "preferred_skills"):
        facets[key] = _canon_skills(facets.get(key) or [], aliases)
    employer = (employer_aliases or {}).get(job.canonical_employer.strip().casefold(), job.canonical_employer)
    posted_age = (now - job.posted_at).days if job.posted_at else None
    days_left = (job.deadline - now.date()).days if job.deadline else None
    kit_rights = None
    if kit_answers is not None:
        countries = work_rights.job_countries({"facets": facets, "location": job.location.model_dump()})
        kit_rights = work_rights.resolve(kit_answers, countries, today=now.date()).to_record()
    return {
        "id": str(job.id),
        "kit_work_rights": kit_rights,
        "title": job.title,
        "employer": employer,
        "employer_as_posted": job.employer,
        "recruiter": job.recruiter,
        "function": job.function,
        "level": job.level,
        "facets": facets,
        "evidence": evidence,
        "custom": {key: value.value for key, value in job.custom_facets.items()},
        "tags": list(job.tags),
        "location": job.location.model_dump(),
        "pay_state": _val(job.pay_state),
        "pay": {"min_minor": job.pay_min_minor, "max_minor": job.pay_max_minor, "currency": job.pay_currency,
                "period": job.pay_period},
        "pay_estimate": None if estimate is None else {
            "min_minor": estimate.min_minor, "max_minor": estimate.max_minor, "currency": estimate.currency,
            "period": estimate.period, "source": estimate.source, "estimated_on": estimate.estimated_on,
            "assumptions": estimate.assumptions},
        "deadline_state": _val(job.deadline_state),
        "deadline": job.deadline,
        "deadline_days_left": days_left,
        "availability": _val(job.availability),
        "last_checked_at": job.last_checked_at,
        "posted_at": job.posted_at,
        "posted_age_days": posted_age,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "apply_method": job.apply_method,
        "source": list(sources),
        "raw_text": job.raw_text,
        "triage": job.triage,
        "conflict_state": _val(job.conflict_state),
        "best_score": best_score,
        "always_ask_first": always_ask_first,
        "never_apply": never_apply,
        "requisition_id": job.requisition_id,
    }


def campaign_record(campaign: Campaign, *, work_rights: Sequence[str] | None = None) -> dict[str, Any]:
    """Campaign snapshot for the decision table. ``work_rights``: where the owner may already work
    (Kit data; ``None`` = not known, which is never treated as yes)."""
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "status": _val(campaign.status),
        "review_state": _val(campaign.review_state),
        "confirmed": campaign.confirmed_at is not None and not campaign.unconfirmed_items,
        "priority": campaign.priority,
        "criteria": campaign.criteria,
        "unknown_data_policy": campaign.unknown_data_policy.model_dump(),
        "automation": campaign.automation.model_dump(),
        "preferred_seniority": campaign.preferred_seniority,
        "work_rights": list(work_rights) if work_rights is not None else None,
        "version": campaign.updated_at.isoformat() if campaign.updated_at else None,
    }


@dataclass
class Lookups:
    skill_aliases: dict[str, str]
    employer_aliases: dict[str, str]
    always_ask: set[str]
    never_apply: dict[str, str] = field(default_factory=dict)


async def load_lookups(session: AsyncSession) -> Lookups:
    skills = {a.alias.strip().casefold(): a.canonical for a in (await session.scalars(select(SkillAlias))).all()}
    employers = {a.alias.strip().casefold(): a.canonical
                 for a in (await session.scalars(select(EmployerAlias))).all()}
    ask = {w.name.strip().casefold() for w in (await session.scalars(
        select(WatchedEmployer).where(WatchedEmployer.always_ask_first.is_(True)))).all()}
    never: dict[str, str] = {}
    for pol in (await session.scalars(select(EmployerPolicy))).all():  # per-employer overrides (7.1, 8.1)
        if pol.always_ask_first:
            ask.add(pol.employer_key)
        if pol.never_apply:
            never[pol.employer_key] = pol.never_reason or ""
    return Lookups(skills, employers, ask, never)


def _ekey(job: Job, lk: Lookups) -> str:
    """The alias-resolved, casefolded employer, the key of watched employers and employer policies."""
    name = job.canonical_employer.strip().casefold()
    return (lk.employer_aliases.get(name) or name).strip().casefold()


async def load_records(session: AsyncSession, *, now: datetime, job_ids: Sequence[uuid.UUID] | None = None,
                       include_merged: bool = False) -> list[tuple[Job, dict[str, Any]]]:
    """Jobs with their records (best score, latest estimate, source names, aliases applied)."""
    stmt = select(Job)
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(list(job_ids)))
    if not include_merged:
        stmt = stmt.where(Job.merged_into_id.is_(None))
    jobs = list((await session.scalars(stmt)).all())
    if not jobs:
        return []
    ids = [j.id for j in jobs]
    best = dict((await session.execute(
        select(Assessment.job_id, func.max(Assessment.score)).where(Assessment.job_id.in_(ids))
        .group_by(Assessment.job_id))).all())
    estimates: dict[uuid.UUID, PayEstimate] = {}
    for est in (await session.scalars(select(PayEstimate).where(PayEstimate.job_id.in_(ids))
                                      .order_by(PayEstimate.estimated_on))).all():
        estimates[est.job_id] = est  # latest wins
    sources: dict[uuid.UUID, list[str]] = {}
    for job_id, name in (await session.execute(
            select(JobSighting.job_id, Source.name).join(Source, Source.id == JobSighting.source_id)
            .where(JobSighting.job_id.in_(ids)).order_by(JobSighting.first_seen_at))).all():
        sources.setdefault(job_id, []).append(name)
    lk = await load_lookups(session)
    kit_answers = await work_rights.load_answers(session)
    out = []
    for job in jobs:
        record = job_record(job, now=now, estimate=estimates.get(job.id), sources=sources.get(job.id, ()),
                            skill_aliases=lk.skill_aliases, employer_aliases=lk.employer_aliases,
                            best_score=best.get(job.id),
                            always_ask_first=_ekey(job, lk) in lk.always_ask,
                            never_apply=lk.never_apply.get(_ekey(job, lk)),
                            kit_answers=kit_answers)
        out.append((job, record))
    return out


# ----- campaign criteria ------------------------------------------------------------------


def filter_results(decision: Decision) -> list[FilterResult]:
    """Exclusion and eligibility gates as stored pass / fail / unknown results, each with a reason."""
    return [FilterResult(name=g.gate, result=g.outcome, reason=g.reason, mandatory=g.mandatory)
            for g in decision.gates if g.layer in ("exclusion", "eligibility")]


def hard_failed(decision: Decision) -> bool:
    """True when an exclusion or eligibility gate failed: such a role is never scored (cost order)."""
    return any(g.outcome == "fail" and g.mandatory for g in decision.gates if g.layer in ("exclusion", "eligibility"))


def view_to_rule(view: SavedViewBody, effect: Literal["exclude", "include", "penalty", "bonus"], *,
                 points: int | None = None, reason: str | None = None) -> CampaignRule:
    """"Use as campaign rule": the same ``ConditionSet``, made binding."""
    return CampaignRule(effect=effect, conditions=view.conditions.model_copy(deep=True), points=points, reason=reason)


@dataclass
class Preview:
    matched: int
    total: int
    sample_ids: list[str]


def preview(conditions: ConditionSet, records: Sequence[Mapping[str, Any]], limit: int) -> Preview:
    """What a rule would match among saved jobs."""
    hits = [r for r in records if evaluate(conditions, r)]
    return Preview(matched=len(hits), total=len(records), sample_ids=[str(r["id"]) for r in hits[:limit]])


# ----- the Matches query ------------------------------------------------------------------

SORTABLE = ("best_score", "posted_at", "deadline", "title", "employer", "created_at", "updated_at",
            "posted_age_days")


class QueryError(ValueError):
    pass


def combine(*sets: ConditionSet | None, text: str | None = None) -> ConditionSet:
    """AND together condition sets (and an optional free-text search)."""
    conditions: list[Any] = [s.root for s in sets if s is not None and s.root.conditions]
    if text and text.strip():
        conditions.append(TextFilter(query=text.strip()))
    if len(conditions) == 1 and isinstance(conditions[0], Group) and not conditions[0].negate:
        return ConditionSet(root=conditions[0])
    return ConditionSet(root=Group(op="and", conditions=conditions))


def _sort_key(field: str, record: Mapping[str, Any]) -> tuple[int, Any]:
    value = lookup(record, field)
    if value is None:
        return (1, 0)
    if isinstance(value, datetime):
        return (0, value.timestamp())
    if isinstance(value, date):
        return (0, value.toordinal())
    if isinstance(value, str):
        return (0, value.casefold())
    return (0, value)


def sort_records(records: list[Mapping[str, Any]], sort: str | None) -> list[Mapping[str, Any]]:
    """``field`` ascending or ``-field`` descending; missing values always sort last."""
    if not sort:
        sort = "-best_score"
    desc = sort.startswith("-")
    name = sort.lstrip("-+")
    if name not in SORTABLE:
        raise QueryError(f"cannot sort by {name!r}; choose one of {', '.join(SORTABLE)}")
    present = [r for r in records if lookup(r, name) is not None]
    missing = [r for r in records if lookup(r, name) is None]
    present.sort(key=lambda r: (_sort_key(name, r), str(r.get("id"))), reverse=desc)
    return present + missing


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        if not raw.startswith("o:"):
            raise ValueError(raw)
        return max(0, int(raw[2:]))
    except (ValueError, UnicodeDecodeError) as exc:
        raise QueryError("invalid cursor") from exc


@dataclass
class QueryResult:
    items: list[Mapping[str, Any]]
    total: int
    next_cursor: str | None
    groups: list[tuple[str, int]] | None


def query_jobs(records: Sequence[Mapping[str, Any]], conditions: ConditionSet, *, group: str | None = None,
               sort: str | None = None, cursor: str | None = None, limit: int = 50) -> QueryResult:
    hits = [r for r in records if evaluate(conditions, r)]
    groups = None
    if group:
        grouped = group_by(hits, group)
        groups = sorted(((value, len(rows)) for value, rows in grouped.items()), key=lambda g: (-g[1], g[0]))
    ordered = sort_records(hits, sort)
    offset = decode_cursor(cursor)
    page = ordered[offset:offset + limit]
    next_cursor = encode_cursor(offset + limit) if offset + limit < len(ordered) else None
    return QueryResult(items=page, total=len(ordered), next_cursor=next_cursor, groups=groups)


def explain_rules(conditions: ConditionSet, record: Mapping[str, Any]) -> Any:
    return explain(conditions, record)


# ----- facet catalogue --------------------------------------------------------------------

YES_NO = ("yes", "no", NOT_STATED)


@dataclass(frozen=True)
class FacetDef:
    facet: str
    label: str
    kind: Literal["values", "range", "text"]
    values: tuple[str, ...] = ()  # fixed choices; empty = counted from the data


FACETS: tuple[FacetDef, ...] = (
    FacetDef("facets.relocation_required", "Relocation required", "values", YES_NO),
    FacetDef("facets.visa_sponsorship", "Visa sponsorship offered", "values", YES_NO),
    FacetDef("facets.relocation_assistance", "Relocation assistance offered", "values", YES_NO),
    FacetDef("facets.needs_account", "Needs an account to apply", "values", YES_NO),
    FacetDef("facets.work_model", "Work model", "values", ("on_site", "hybrid", "remote", NOT_STATED)),
    FacetDef("facets.remote_scope", "Remote scope", "values", ("worldwide", "regions", "country_only", NOT_STATED)),
    FacetDef("facets.remote_regions", "Remote regions", "values"),
    FacetDef("facets.where_must_live.kind", "Where you must live", "values", ("places", "anywhere", NOT_STATED)),
    FacetDef("facets.where_must_live.places", "Must live in", "values"),
    FacetDef("facets.work_rights", "Work rights needed", "values",
             ("existing_right_required", "sponsorship_possible", NOT_STATED)),
    FacetDef("facets.timezone_overlap.hours", "Time-zone overlap (hours)", "range"),
    FacetDef("facets.hiring_arrangement", "Hiring arrangement", "values",
             ("employee", "contractor", "eor", NOT_STATED)),
    FacetDef("facets.employment_type", "Employment type", "values",
             ("permanent", "fixed_term", "contract", "eor", NOT_STATED)),
    FacetDef("facets.required_skills", "Required skills", "values"),
    FacetDef("facets.preferred_skills", "Preferred skills", "values"),
    FacetDef("facets.min_education.level", "Minimum education", "values",
             ("none_stated", "bachelors", "masters", "doctorate", NOT_STATED)),
    FacetDef("facets.min_education.required", "Education required (not preferred)", "values"),
    FacetDef("facets.required_qualifications", "Required qualifications", "values"),
    FacetDef("facets.years_experience", "Years of experience asked", "range"),
    FacetDef("facets.languages", "Languages", "values"),
    FacetDef("facets.travel_percent", "Travel (%)", "range"),
    FacetDef("facets.industry", "Industry", "values"),
    FacetDef("location.country", "Country", "values"),
    FacetDef("location.region", "Region", "values"),
    FacetDef("location.city", "City", "values"),
    FacetDef("pay_state", "Pay", "values", ("stated", "estimated", NOT_STATED)),
    FacetDef("pay.max_minor", "Pay (stated maximum, minor units)", "range"),
    FacetDef("pay.currency", "Pay currency", "values"),
    FacetDef("employer", "Employer", "values"),
    FacetDef("function", "Function", "values"),
    FacetDef("level", "Level", "values"),
    FacetDef("source", "Source", "values"),
    FacetDef("apply_method", "Apply method", "values"),
    FacetDef("posted_age_days", "Posted age (days)", "range"),
    FacetDef("deadline_state", "Deadline", "values", ("dated", "open_until_filled", NOT_STATED)),
    FacetDef("deadline_days_left", "Days to deadline", "range"),
    FacetDef("availability", "Availability", "values", ("open", "closed", "unknown")),
    FacetDef("triage", "Triage", "values", ("new", "shortlisted", "below_threshold", "archived", "skipped")),
    FacetDef("conflict_state", "Employer conflict", "values", ("none", "winner", "held", "released")),
    FacetDef("tags", "Tags", "values"),
    FacetDef("best_score", "Best score", "range"),
    FacetDef("title", "Title, employer and posting text", "text"),
)


def catalogue(records: Sequence[Mapping[str, Any]], custom_keys: Sequence[tuple[str, str]] = ()
              ) -> list[tuple[FacetDef, list[tuple[str, int]]]]:
    """Every filterable facet with value counts over ``records`` (custom facets appended)."""
    defs = list(FACETS) + [FacetDef(f"custom.{key}", question, "values", YES_NO) for key, question in custom_keys]
    out = []
    for definition in defs:
        counts: list[tuple[str, int]] = []
        if definition.kind == "values":
            grouped = {k: len(v) for k, v in group_by(records, definition.facet).items()}
            names = list(definition.values) + sorted(k for k in grouped if k not in definition.values)
            counts = [(name, grouped.get(name, 0)) for name in names]
        out.append((definition, counts))
    return out
