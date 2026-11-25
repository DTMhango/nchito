"""Jobs (Matches and the job page), manual capture, corrections, saved views, tag rules,
custom facets, skill aliases. Wave 1."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Ok, Page, Timestamps, not_implemented
from app.api.crud import add_crud
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.conditions import ConditionResult, ConditionSet
from app.core.events import publish
from app.pipeline.capture import CaptureError, capture
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


class JobSummary(Timestamps):
    title: str
    employer: str
    canonical_employer: str
    location: StructuredLocation
    triage: Triage
    best_score: int | None = None
    conflict_state: Literal["none", "winner", "held", "released"]
    conflict_note: str | None = None
    pay: PayOut
    deadline: DeadlineOut
    availability: Literal["open", "closed", "unknown"]
    tags: list[str]
    pinned: bool
    posted_at: datetime | None = None


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
    jobs: int
    estimated_cost_minor: int
    currency: str


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


# ----- jobs -------------------------------------------------------------------------------


@router.get("/jobs", response_model=JobListOut, name="jobs_list")
async def list_jobs(q: Annotated[JobQuery, Query()]) -> JobListOut:
    not_implemented(WAVE, AREA)


@router.get("/jobs/facets", response_model=list[FacetCatalogEntry], name="jobs_facet_catalog")
async def facet_catalog() -> list[FacetCatalogEntry]:
    """Facets available to the filter builder, with value counts."""
    not_implemented(WAVE, AREA)


@router.get("/jobs/{job_id}", response_model=JobDetail, name="jobs_get")
async def get_job(job_id: uuid.UUID) -> JobDetail:
    not_implemented(WAVE, AREA)


@router.patch("/jobs/{job_id}", response_model=JobDetail, name="jobs_patch")
async def patch_job(job_id: uuid.UUID, body: JobPatch) -> JobDetail:
    not_implemented(WAVE, AREA)


@router.post("/jobs/capture", response_model=CaptureOut, status_code=status.HTTP_202_ACCEPTED, name="jobs_capture",
             responses={422: {"description": "Neither a link nor text, or a link that is not http(s)"}})
async def capture_job(body: CaptureIn, principal: PrincipalDep, session: SessionDep) -> CaptureOut:
    """Manual capture: persist a Job stub from a pasted link or text (DESIGN 6). Wave 1 runs it
    through the same pipeline as any source."""
    try:
        job = await capture(session, body.url, body.text)
    except CaptureError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    await audit.record(session, actor=principal.actor, action="job.captured", subject_type="job",
                       subject_id=job.id, detail={"has_url": body.url is not None, "has_text": body.text is not None})
    await publish(session, "job.created", {"job_id": str(job.id)})
    return CaptureOut(id=job.id, status="queued")


@router.post("/jobs/bulk", response_model=BulkActionOut, name="jobs_bulk")
async def bulk_action(body: BulkActionIn) -> BulkActionOut:
    not_implemented(4, AREA)


@router.get("/jobs/{job_id}/why", response_model=WhyOut, name="jobs_why")
async def why(job_id: uuid.UUID, campaign_id: uuid.UUID | None = None) -> WhyOut:
    not_implemented(WAVE, AREA)


@router.get("/jobs/compare/{job_ids}", response_model=CompareOut, name="jobs_compare")
async def compare(job_ids: str) -> CompareOut:
    """Comma-separated job ids. Wave 3."""
    not_implemented(3, AREA)


# applied-myself, merge, split and employer fixes live in jobs_corrections.py


@router.post("/jobs/{job_id}/release", response_model=JobDetail, name="jobs_release_held")
async def release_held(job_id: uuid.UUID, body: ReleaseHeldIn) -> JobDetail:
    """Release a held role from its conflict group (7.1), with a reason. Audited."""
    not_implemented(WAVE, AREA)


@router.post("/jobs/{job_id}/recheck", response_model=JobDetail, name="jobs_recheck")
async def recheck(job_id: uuid.UUID) -> JobDetail:
    not_implemented(WAVE, AREA)


# ----- views, tag rules, custom facets, aliases --------------------------------------------

add_crud(router, "/views", "views", SavedViewIn, SavedViewOut, wave=WAVE, area="views")
add_crud(router, "/tag-rules", "tag_rules", TagRuleIn, TagRuleOut, wave=WAVE, area="views")
add_crud(router, "/custom-facets", "custom_facets", CustomFacetIn, CustomFacetOut, wave=WAVE, area="views")
add_crud(router, "/skill-aliases", "skill_aliases", SkillAliasIn, SkillAliasOut, wave=WAVE, area="views",
         ops=("list", "create", "update", "delete"))


@router.post("/custom-facets/{item_id}/backfill", response_model=BackfillEstimate, name="custom_facets_backfill",
             status_code=status.HTTP_202_ACCEPTED)
async def backfill_custom_facet(item_id: uuid.UUID, confirm: bool = False) -> BackfillEstimate:
    """Without ``confirm`` returns the cost estimate only; with it, queues the backfill under the budget cap."""
    not_implemented(WAVE, "views")
