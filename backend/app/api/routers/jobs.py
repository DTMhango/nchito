"""Jobs (Matches and the job page), manual capture, corrections, saved views, tag rules,
custom facets, skill aliases. Wave 1.

Reading never changes pipeline state: listing, views, counts and the facet catalogue only read.
The Matches grammar is the one condition engine (``core/conditions.py``): include / exclude /
not stated per facet, any / all within a facet, free text, group-by with counts, sort, pages.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Page, Timestamps, not_implemented
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.core.conditions import ConditionResult, ConditionSet, Group, ValueFilter, evaluate, explain
from app.core.events import publish
from app.core.settings import service as settings_service
from app.llm.money import micros_to_minor
from app.models.applications import Application
from app.models.search import (
    Assessment,
    Campaign,
    CustomFacet,
    Job,
    JobSighting,
    Rubric,
    SavedView,
    SkillAlias,
    TagRule,
)
from app.pipeline import conflicts, custom_facets, filters, normalise, scoring
from app.pipeline.capture import CaptureError, capture
from app.pipeline.decisions import decide
from app.schemas.json_types import CustomFacetValue, JobFacets, Requirement, SavedViewBody, StructuredLocation

router = APIRouter(prefix="/api", tags=["jobs"], dependencies=[RequireOwner], responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "jobs"

Triage = Literal["new", "shortlisted", "below_threshold", "archived", "skipped"]


class PayOut(BaseModel):
    state: Literal["stated", "estimated", "not_stated"]
    min_minor: int | None = None
    max_minor: int | None = None
    currency: str | None = None
    period: str | None = None
    estimate_source: str | None = None
    estimate_assumptions: str | None = None
    estimated_on: date | None = None


class DeadlineOut(BaseModel):
    state: Literal["dated", "open_until_filled", "not_stated"]
    on: date | None = None


class SightingOut(BaseModel):
    source_id: uuid.UUID | None
    url: str
    first_seen_at: datetime
    last_seen_at: datetime


class ConflictOut(BaseModel):
    """The role's employer-group state; for a held role, the role that outranks it and both scores."""

    state: Literal["none", "winner", "held", "released"]
    note: str | None = None
    outranked_by_job_id: uuid.UUID | None = None
    outranked_by_title: str | None = None
    score: int | None = None
    outranked_by_score: int | None = None
    reason: Literal["outranked", "applied"] | None = Field(
        default=None, description="outranked: a higher role won; applied: the employer is locked after applying")


class JobSummary(Timestamps):
    title: str
    employer: str
    canonical_employer: str
    location: StructuredLocation
    triage: Triage
    best_score: int | None = None
    conflict_state: Literal["none", "winner", "held", "released"]
    conflict_note: str | None = None
    conflict: ConflictOut | None = None
    pay_state: Literal["stated", "estimated", "not_stated"] = "not_stated"
    pay: PayOut
    deadline: DeadlineOut
    availability: Literal["open", "closed", "unknown"]
    tags: list[str]
    pinned: bool
    posted_at: datetime | None = None
    work_model: Literal["on_site", "hybrid", "remote", "not_stated"] = "not_stated"
    remote_scope: Literal["worldwide", "regions", "country_only", "not_stated"] = "not_stated"
    source: str | None = Field(default=None, description="Name of the first sighting's source")


class JobDetail(JobSummary):
    recruiter: str | None = None
    requisition_id: str | None = None
    function: str | None = None
    level: str | None = None
    facets: JobFacets
    custom_facets: dict[str, CustomFacetValue]
    apply_url: str | None = None
    apply_method: str
    requirements: list[Requirement]
    raw_text: str | None = None
    sightings: list[SightingOut]
    notes: str | None = None
    last_checked_at: datetime | None = None
    repost_of_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None


class JobQuery(BaseModel):
    """Filter for Matches. ``view_id`` applies a saved view; ``conditions`` is JSON-encoded ConditionSet."""

    triage: Triage | None = None
    view_id: uuid.UUID | None = None
    conditions: str | None = Field(default=None, description="JSON ConditionSet")
    q: str | None = None
    group_by: str | None = None
    sort: str | None = Field(default=None, description="field or -field")
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class JobGroup(BaseModel):
    value: str
    count: int


class JobListOut(Page[JobSummary]):
    groups: list[JobGroup] | None = None


class JobPatch(BaseModel):
    triage: Triage | None = None
    pinned: bool | None = None
    snoozed_until: datetime | None = None
    notes: str | None = None
    tags: list[str] | None = None


class CaptureIn(BaseModel):
    """Paste a link, the posting text, or both. At least one is required."""

    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=200_000)


class CaptureOut(BaseModel):
    id: uuid.UUID = Field(description="The new job's id")
    status: Literal["queued"] = Field(description="Queued for the pipeline (normalise, dedupe, score: wave 1)")


class BulkActionIn(BaseModel):
    job_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["skip", "archive", "shortlist", "tag", "untag", "pin", "unpin", "snooze"]
    tag: str | None = None
    until: datetime | None = None
    preview: bool = True


class BulkActionOut(BaseModel):
    affected: int
    preview: bool
    detail: list[str]


class AppliedMyselfIn(BaseModel):
    """"I applied myself": counts at once for duplicates, employer limits and follow-ups."""

    applied_on: date
    channel: Literal["email", "browser", "manual"] = "manual"
    reference: str | None = None
    note: str | None = None


class MergeIn(BaseModel):
    duplicate_ids: list[uuid.UUID] = Field(min_length=1)


class SplitIn(BaseModel):
    sighting_urls: list[str] = Field(min_length=1, description="Sightings to move to a new job")


class EmployerFixIn(BaseModel):
    canonical_employer: str
    remember_alias: bool = True


class ReleaseHeldIn(BaseModel):
    reason: str = Field(min_length=3)


class WhyRule(BaseModel):
    rule: str
    effective_value: str
    source: str = Field(description="setting, campaign, rubric, guardrail, answer, ...")
    version: str | None = None
    outcome: Literal["pass", "fail", "unknown", "info"]
    reason: str
    would_change_if: str | None = None


class WhyOut(BaseModel):
    """The "Why?" panel (18.4)."""

    decision: str
    rules: list[WhyRule]
    conditions: list[ConditionResult] = Field(default_factory=list)


class CompareOut(BaseModel):
    job_ids: list[uuid.UUID]
    rows: list[dict[str, str | int | None]]
    winner_id: uuid.UUID | None
    winner_reason: str | None


class SavedViewIn(ApiModel):
    name: str
    body: SavedViewBody
    pinned: bool = False
    sort_order: int = 0


class SavedViewOut(SavedViewIn, Timestamps):
    count: int | None = Field(default=None, description="Live count")


class TagRuleIn(ApiModel):
    tag: str
    conditions: ConditionSet
    enabled: bool = True


class TagRuleOut(TagRuleIn, Timestamps):
    pass


class CustomFacetIn(ApiModel):
    key: str = Field(pattern=r"^[a-z0-9_]{1,60}$")
    question: str
    enabled: bool = True


class CustomFacetOut(CustomFacetIn, Timestamps):
    pass


class BackfillEstimate(BaseModel):
    """Without ``confirm``: jobs to answer and the estimate. With it: jobs answered and the spend."""

    jobs: int
    estimated_cost_minor: int
    estimated_cost_micros: int = 0
    currency: str
    remaining: int = 0
    paused_for_budget: str | None = Field(default=None, description="Budget scope that stopped the backfill")


class SkillAliasIn(ApiModel):
    alias: str
    canonical: str


class SkillAliasOut(SkillAliasIn, Timestamps):
    pass


class FacetValueCount(BaseModel):
    value: str
    count: int


class FacetCatalogEntry(BaseModel):
    facet: str
    label: str
    kind: Literal["values", "range", "text"]
    values: list[FacetValueCount] = Field(default_factory=list)


# ----- helpers ----------------------------------------------------------------------------


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(422, detail=str(exc))


def _pay(record: dict[str, Any]) -> PayOut:
    state = record["pay_state"]
    if state == "estimated" and record.get("pay_estimate"):
        est = record["pay_estimate"]
        return PayOut(state="estimated", min_minor=est["min_minor"], max_minor=est["max_minor"],
                      currency=est["currency"], period=est["period"], estimate_source=est["source"],
                      estimate_assumptions=est["assumptions"], estimated_on=est["estimated_on"])
    if state == "stated":
        return PayOut(state="stated", **record["pay"])
    return PayOut(state=state)


def _summary_data(job: Job, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.id, "created_at": job.created_at, "updated_at": job.updated_at, "title": job.title,
        "employer": job.employer, "canonical_employer": job.canonical_employer, "location": job.location,
        "triage": job.triage, "best_score": record.get("best_score"), "conflict_state": record["conflict_state"],
        "conflict_note": job.conflict_note, "pay": _pay(record), "pay_state": record["pay_state"],
        "conflict": ConflictOut(state=record["conflict_state"], note=job.conflict_note, **(job.conflict_detail or {})),
        "work_model": record["facets"].get("work_model") or "not_stated",
        "remote_scope": record["facets"].get("remote_scope") or "not_stated",
        "source": record["source"][0] if record["source"] else None,
        "deadline": DeadlineOut(state=record["deadline_state"], on=job.deadline),
        "availability": record["availability"], "tags": list(job.tags), "pinned": bool(job.pinned),
        "posted_at": job.posted_at,
    }


async def _records(session: SessionDep, job_ids: list[uuid.UUID] | None = None) -> list[tuple[Job, dict[str, Any]]]:
    return await filters.load_records(session, now=utcnow(), job_ids=job_ids)


def _parse_conditions(raw: str | None) -> ConditionSet | None:
    if not raw:
        return None
    try:
        return ConditionSet.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors(include_url=False)) from exc


async def _job(session: SessionDep, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    return job


async def job_detail(session: SessionDep, job: Job) -> JobDetail:
    await session.flush()
    await session.refresh(job)
    record = (await filters.load_records(session, now=utcnow(), job_ids=[job.id], include_merged=True))[0][1]
    sightings = (await session.scalars(select(JobSighting).where(JobSighting.job_id == job.id)
                                       .order_by(JobSighting.first_seen_at))).all()
    app_id = await session.scalar(select(Application.id).where(Application.job_id == job.id)
                                  .order_by(Application.created_at.desc()).limit(1))
    return JobDetail.model_validate({
        **_summary_data(job, record), "recruiter": job.recruiter, "requisition_id": job.requisition_id,
        "function": job.function, "level": job.level, "facets": job.facets, "custom_facets": job.custom_facets,
        "apply_url": job.apply_url, "apply_method": job.apply_method, "requirements": job.requirements,
        "raw_text": job.raw_text, "notes": job.notes, "last_checked_at": job.last_checked_at,
        "repost_of_id": job.repost_of_id, "application_id": app_id,
        "sightings": [SightingOut(source_id=s.source_id, url=s.url, first_seen_at=s.first_seen_at,
                                  last_seen_at=s.last_seen_at) for s in sightings],
    })


# ----- jobs -------------------------------------------------------------------------------


@router.get("/jobs", response_model=JobListOut, name="jobs_list")
async def list_jobs(q: Annotated[JobQuery, Query()], session: SessionDep) -> JobListOut:
    """Matches. ``conditions`` (JSON ``ConditionSet``) carries the facet grammar; ``view_id`` adds a
    saved view's conditions (and its group and sort unless given); ``q`` is free text."""
    view_body = None
    if q.view_id:
        view = await session.get(SavedView, q.view_id)
        if view is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="view not found")
        view_body = view.body
    triage = ConditionSet(root=Group(conditions=[ValueFilter(facet="triage", include=[q.triage])])) \
        if q.triage else None
    conditions = filters.combine(view_body.conditions if view_body else None, _parse_conditions(q.conditions),
                                 triage, text=q.q)
    group = q.group_by or (view_body.group_by if view_body else None)
    sort = q.sort
    if sort is None and view_body and view_body.sort:
        first = view_body.sort[0]
        sort = ("-" if first.direction == "desc" else "") + first.field
    records = await _records(session)
    by_id = {r["id"]: (job, r) for job, r in records}
    try:
        result = filters.query_jobs([r for _, r in records], conditions, group=group, sort=sort, cursor=q.cursor,
                                    limit=q.limit)
    except filters.QueryError as exc:
        raise _bad(exc) from exc
    items = [JobSummary.model_validate(_summary_data(*by_id[r["id"]])) for r in result.items]
    groups = [JobGroup(value=v, count=c) for v, c in result.groups] if result.groups is not None else None
    return JobListOut(items=items, total=result.total, next_cursor=result.next_cursor, groups=groups)


@router.get("/jobs/facets", response_model=list[FacetCatalogEntry], name="jobs_facet_catalog")
async def facet_catalog(session: SessionDep) -> list[FacetCatalogEntry]:
    """Facets available to the filter builder, with value counts."""
    records = [r for _, r in await _records(session)]
    custom = [(c.key, c.question) for c in (await session.scalars(
        select(CustomFacet).where(CustomFacet.enabled.is_(True)).order_by(CustomFacet.key))).all()]
    return [FacetCatalogEntry(facet=d.facet, label=d.label, kind=d.kind,
                              values=[FacetValueCount(value=v, count=c) for v, c in counts])
            for d, counts in filters.catalogue(records, custom)]


@router.get("/jobs/{job_id}", response_model=JobDetail, name="jobs_get")
async def get_job(job_id: uuid.UUID, session: SessionDep) -> JobDetail:
    return await job_detail(session, await _job(session, job_id))


@router.patch("/jobs/{job_id}", response_model=JobDetail, name="jobs_patch")
async def patch_job(job_id: uuid.UUID, body: JobPatch, session: SessionDep, principal: PrincipalDep) -> JobDetail:
    """Triage, pin, snooze, notes and manual tags. Skipping a conflict winner promotes the next role."""
    job = await _job(session, job_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(job, key, value)
    await session.flush()
    if "triage" in changes:
        await conflicts.on_job_changed(session, job)
    await audit.record(session, actor=principal.actor, action="job.updated", subject_type="job", subject_id=job.id,
                       detail={k: str(v) for k, v in changes.items()})
    return await job_detail(session, job)


CaptureEnqueue = Callable[[uuid.UUID], Awaitable[None]]


async def get_capture_enqueue() -> CaptureEnqueue:
    """Defers ``process_capture`` to the worker (tests replace this dependency)."""

    async def enqueue(job_id: uuid.UUID) -> None:
        from app.worker.queue import enqueue_capture, queue_app

        async with queue_app.open_async():
            await enqueue_capture(job_id)

    return enqueue


@router.post("/jobs/capture", response_model=CaptureOut, status_code=status.HTTP_202_ACCEPTED, name="jobs_capture",
             responses={422: {"description": "Neither a link nor text, or a link that is not http(s)"}})
async def capture_job(body: CaptureIn, principal: PrincipalDep, session: SessionDep,
                      enqueue: Annotated[CaptureEnqueue, Depends(get_capture_enqueue)]) -> CaptureOut:
    """Manual capture: persist a Job stub from a pasted link or text (DESIGN 6). Wave 1 runs it
    through the same pipeline as any source."""
    try:
        job = await capture(session, body.url, body.text)
    except CaptureError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await audit.record(session, actor=principal.actor, action="job.captured", subject_type="job",
                       subject_id=job.id, detail={"has_url": body.url is not None, "has_text": body.text is not None})
    await publish(session, "job.created", {"job_id": str(job.id)})
    await session.commit()  # the worker must find the stub when it picks the job up
    await enqueue(job.id)
    return CaptureOut(id=job.id, status="queued")


@router.post("/jobs/bulk", response_model=BulkActionOut, name="jobs_bulk")
async def bulk_action(body: BulkActionIn) -> BulkActionOut:
    not_implemented(4, AREA)


def _value(ref: Any) -> str:
    return str(ref.effective_value)


@router.get("/jobs/{job_id}/why", response_model=WhyOut, name="jobs_why")
async def why(job_id: uuid.UUID, session: SessionDep, campaign_id: uuid.UUID | None = None) -> WhyOut:
    """The "Why?" panel: the decision table's gates for each campaign that assessed the role (or the
    one asked for), with each rule's effective value, source and version, and what would change it."""
    job = await _job(session, job_id)
    now = utcnow()
    record = (await filters.load_records(session, now=now, job_ids=[job.id], include_merged=True))[0][1]
    stmt = select(Assessment).where(Assessment.job_id == job.id)
    if campaign_id:
        stmt = stmt.where(Assessment.campaign_id == campaign_id)
    assessments = {a.campaign_id: a for a in (await session.scalars(stmt)).all()}
    campaign_ids = [campaign_id] if campaign_id else list(assessments)
    if not campaign_ids:
        return WhyOut(decision="not assessed by any campaign yet", rules=[])
    settings, versions = await scoring.setting_versions(session)
    counters = await conflicts.employer_counters(session, job, now=now)
    decisions, rules, explained = [], [], []
    multiple = len(campaign_ids) > 1
    for cid in campaign_ids:
        campaign = await session.get(Campaign, cid)
        if campaign is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="campaign not found")
        a = assessments.get(cid)
        rubric = await session.get(Rubric, a.rubric_id) if a and a.rubric_id else \
            await scoring.active_rubric(session, campaign.rubric_id)
        decision = decide(scoring.decision_input(
            now=now, record=record, crecord=filters.campaign_record(campaign), settings=settings, versions=versions,
            rubric=rubric, base_score=a.base_score if a else None, job=job,
            override=a.override.model_dump() if a and a.override else None, counters=counters))
        prefix = f"{campaign.name}: " if multiple else ""
        decisions.append(f"{prefix}{decision.verdict}")
        for gate in decision.gates:
            rules.append(WhyRule(
                rule=f"{prefix}{gate.layer}.{gate.gate}",
                effective_value="; ".join(f"{r.rule}={_value(r)}" for r in gate.rules) or "-",
                source=", ".join(dict.fromkeys(r.source for r in gate.rules)) or "job",
                version=", ".join(dict.fromkeys(r.version for r in gate.rules if r.version)) or None,
                outcome=gate.outcome if gate.mandatory or gate.outcome != "pass" else "info",
                reason=gate.reason, would_change_if=gate.would_change_if))
        for rule in campaign.criteria.rules:
            explained.append(explain(rule.conditions, record))
    return WhyOut(decision="; ".join(decisions), rules=rules, conditions=explained)


@router.get("/jobs/compare/{job_ids}", response_model=CompareOut, name="jobs_compare")
async def compare(job_ids: str) -> CompareOut:
    """Comma-separated job ids. Wave 3."""
    not_implemented(3, AREA)


# applied-myself, merge, split and employer fixes live in jobs_corrections.py


@router.post("/jobs/{job_id}/release", response_model=JobDetail, name="jobs_release_held")
async def release_held(job_id: uuid.UUID, body: ReleaseHeldIn, session: SessionDep,
                       principal: PrincipalDep) -> JobDetail:
    """Release a held role from its conflict group (7.1), with a reason. Audited."""
    job = await _job(session, job_id)
    try:
        await conflicts.release_held(session, job, actor=principal.actor, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await job_detail(session, job)


class RecheckOut(BaseModel):
    job: JobDetail
    availability_before: Literal["open", "closed", "unknown"]
    availability_after: Literal["open", "closed", "unknown"]
    content_changed: bool
    changed_fields: list[str] = Field(default_factory=list)
    reassessed: bool = False
    note: str | None = Field(default=None, description="Why nothing was re-read, when that is so")


@router.post("/jobs/{job_id}/recheck", response_model=RecheckOut, name="jobs_recheck")
async def recheck(job_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> RecheckOut:
    """Re-read the posting through its source. A failed check is ``unknown``, never ``closed``. A
    material change (text, title, pay, deadline, apply link, place) is re-extracted and reassessed."""
    from app.pipeline import orchestrator
    from app.pipeline import recheck as recheck_pipeline

    job = await _job(session, job_id)
    factory = orchestrator.DEPS.llm_factory
    llm = await factory(session, None) if factory is not None else await scoring.client_for(session)
    result = await recheck_pipeline.recheck_job(session, job, actor=principal.actor, llm=llm)
    return RecheckOut(job=await job_detail(session, job), availability_before=result.availability_before,  # type: ignore[arg-type]
                      availability_after=result.availability_after, content_changed=result.content_changed,  # type: ignore[arg-type]
                      changed_fields=result.changed_fields, reassessed=result.reassessed, note=result.note)


# ----- views, tag rules, custom facets, aliases --------------------------------------------


def _offset(cursor: str | None) -> int:
    try:
        return filters.decode_cursor(cursor)
    except filters.QueryError as exc:
        raise _bad(exc) from exc


async def _view_count(session: SessionDep, body: SavedViewBody, records: list[dict[str, Any]],
                      with_app: set[str]) -> int:
    pool = records if body.scope == "matches" else [r for r in records if r["id"] in with_app]
    return sum(1 for r in pool if evaluate(body.conditions, r))


async def _views_out(session: SessionDep, views: list[SavedView]) -> list[SavedViewOut]:
    records = [r for _, r in await _records(session)]
    with_app = {str(i) for i in (await session.scalars(select(Application.job_id))).all()}
    return [SavedViewOut.model_validate({
        "id": v.id, "created_at": v.created_at, "updated_at": v.updated_at, "name": v.name, "body": v.body,
        "pinned": bool(v.pinned), "sort_order": v.sort_order or 0,
        "count": await _view_count(session, v.body, records, with_app)}) for v in views]


def _plain_out(model_out: type[BaseModel], row: Any) -> BaseModel:
    data = {k: getattr(row, k) for k in model_out.model_fields if hasattr(row, k)}
    return model_out.model_validate(data)


async def _apply_tag_rule(session: SessionDep, rule: TagRule) -> int:
    """Rule tags are free (no model): tag every saved job the rule matches."""
    if not rule.enabled:
        return 0
    tagged = 0
    for job, record in await _records(session):
        if rule.tag not in job.tags and evaluate(rule.conditions, record):
            job.tags = [*job.tags, rule.tag]
            tagged += 1
    return tagged


def _simple_crud(path: str, name: str, model: type[Any], model_in: type[BaseModel], model_out: type[BaseModel], *,
                 ops: tuple[str, ...] = ("list", "get", "create", "update", "delete"), order: Any = None,
                 after_write: Callable[[SessionDep, Any], Awaitable[Any]] | None = None,
                 out_many: Callable[[SessionDep, list[Any]], Awaitable[list[Any]]] | None = None,
                 after_delete: Callable[[SessionDep, Any], Awaitable[Any]] | None = None) -> None:
    """Typed CRUD for a simple table (annotations set explicitly: this module uses postponed annotations)."""

    async def render(session: Any, rows: list[Any]) -> list[Any]:
        if out_many is not None:
            return await out_many(session, rows)
        return [_plain_out(model_out, r) for r in rows]

    async def fetch(session: Any, item_id: uuid.UUID) -> Any:
        row = await session.get(model, item_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name.rstrip('s').replace('_', ' ')} not found")
        return row

    async def list_items(session, cursor=None, limit=50):  # type: ignore[no-untyped-def]
        offset, size = _offset(cursor), max(1, min(limit, 200))
        total = await session.scalar(select(func.count()).select_from(model)) or 0
        rows = list((await session.scalars(select(model).order_by(order if order is not None else model.created_at)
                                           .offset(offset).limit(size))).all())
        return Page(items=await render(session, rows), total=total,
                    next_cursor=filters.encode_cursor(offset + size) if offset + size < total else None)

    async def get_item(item_id, session):  # type: ignore[no-untyped-def]
        return (await render(session, [await fetch(session, item_id)]))[0]

    async def write(session, principal, row, verb):  # type: ignore[no-untyped-def]
        try:
            await session.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="already exists") from exc
        if after_write is not None:
            await after_write(session, row)
        await audit.record(session, actor=principal.actor, action=f"{name}.{verb}", subject_type=name,
                           subject_id=row.id)
        await session.refresh(row)
        return (await render(session, [row]))[0]

    async def create_item(body, session, principal):  # type: ignore[no-untyped-def]
        row = model(**{key: getattr(body, key) for key in type(body).model_fields})
        session.add(row)
        return await write(session, principal, row, "created")

    async def update_item(item_id, body, session, principal):  # type: ignore[no-untyped-def]
        row = await fetch(session, item_id)
        for key in type(body).model_fields:
            setattr(row, key, getattr(body, key))
        return await write(session, principal, row, "updated")

    async def delete_item(item_id, session, principal):  # type: ignore[no-untyped-def]
        row = await fetch(session, item_id)
        await audit.record(session, actor=principal.actor, action=f"{name}.deleted", subject_type=name,
                           subject_id=row.id)
        await session.delete(row)
        if after_delete is not None:
            await session.flush()
            await after_delete(session, row)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    list_items.__annotations__ = {"session": SessionDep, "cursor": str | None, "limit": int}
    get_item.__annotations__ = {"item_id": uuid.UUID, "session": SessionDep}
    create_item.__annotations__ = {"body": model_in, "session": SessionDep, "principal": PrincipalDep}
    update_item.__annotations__ = {"item_id": uuid.UUID, "body": model_in, "session": SessionDep,
                                   "principal": PrincipalDep}
    delete_item.__annotations__ = {"item_id": uuid.UUID, "session": SessionDep, "principal": PrincipalDep}
    item = f"{path}/{{item_id}}"
    if "list" in ops:
        router.add_api_route(path, list_items, methods=["GET"], response_model=Page[model_out], name=f"{name}_list")
    if "get" in ops:
        router.add_api_route(item, get_item, methods=["GET"], response_model=model_out, name=f"{name}_get")
    if "create" in ops:
        router.add_api_route(path, create_item, methods=["POST"], response_model=model_out,
                             status_code=status.HTTP_201_CREATED, name=f"{name}_create")
    if "update" in ops:
        router.add_api_route(item, update_item, methods=["PUT"], response_model=model_out, name=f"{name}_update")
    if "delete" in ops:
        router.add_api_route(item, delete_item, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT,
                             response_class=Response, name=f"{name}_delete")


async def _after_tag_rule(session: SessionDep, rule: TagRule) -> None:
    await _apply_tag_rule(session, rule)


_simple_crud("/views", "views", SavedView, SavedViewIn, SavedViewOut, order=SavedView.sort_order,
             out_many=_views_out)
_simple_crud("/tag-rules", "tag_rules", TagRule, TagRuleIn, TagRuleOut, after_write=_after_tag_rule)
_simple_crud("/custom-facets", "custom_facets", CustomFacet, CustomFacetIn, CustomFacetOut)


async def _after_skill_alias(session: SessionDep, alias: SkillAlias) -> None:
    """A changed alias re-canonicalises stored job skills from the extraction cache (no fetch, no model)."""
    changed = await normalise.recanonicalise_jobs(session)
    await audit.record(session, actor="owner", action="skill_alias.recanonicalised", subject_type="skill_alias",
                       subject_id=alias.id, detail={"jobs_changed": changed})


_simple_crud("/skill-aliases", "skill_aliases", SkillAlias, SkillAliasIn, SkillAliasOut,
             ops=("list", "create", "update", "delete"), after_write=_after_skill_alias,
             after_delete=_after_skill_alias)


@router.post("/custom-facets/{item_id}/backfill", response_model=BackfillEstimate, name="custom_facets_backfill",
             status_code=status.HTTP_202_ACCEPTED)
async def backfill_custom_facet(item_id: uuid.UUID, session: SessionDep, confirm: bool = False) -> BackfillEstimate:
    """Without ``confirm`` returns the cost estimate only; with it, answers the jobs now, each call budgeted."""
    facet = await session.get(CustomFacet, item_id)
    if facet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="custom facet not found")
    client = await scoring.client_for(session)
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no AI provider configured")
    jobs = [job for job, _ in await _records(session) if facet.key not in job.custom_facets]
    currency = await settings_service.get_value(session, "budget.currency")
    if not confirm:
        cost = await custom_facets.estimate(client, facet, jobs)
        return BackfillEstimate(jobs=len(jobs), estimated_cost_minor=micros_to_minor(cost),
                              estimated_cost_micros=cost, currency=currency)
    done = await custom_facets.backfill(client, facet, jobs)
    await audit.record(session, actor="owner", action="custom_facet.backfilled", subject_type="custom_facet",
                       subject_id=facet.id, detail={"answered": done.answered, "remaining": done.remaining,
                                                    "budget": done.budget.scope if done.budget else None})
    return BackfillEstimate(jobs=done.answered, estimated_cost_minor=micros_to_minor(done.cost_micros),
                            estimated_cost_micros=done.cost_micros,
                            currency=currency, remaining=done.remaining,
                            paused_for_budget=done.budget.scope if done.budget else None)
