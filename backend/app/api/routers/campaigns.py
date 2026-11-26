"""Campaigns and rubrics (criteria, per-item confirmation, automation policy, rule preview, dry run,
rubric versions, backtest). Wave 1 (filters/scoring stream)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.core.conditions import CampaignRule, ConditionSet
from app.core.settings.types import SettingValueError, cron_expr
from app.llm.money import micros_to_minor
from app.models.base import ReviewState
from app.models.search import (
    Assessment,
    AssessmentState,
    Campaign,
    CampaignStatus,
    ConflictState,
    Job,
    Rubric,
    RubricStatus,
    Run,
    RunKind,
    RunStatus,
    SavedView,
    Schedule,
)
from app.pipeline import filters, scoring
from app.pipeline.decisions import MODES, UNCONFIRMED_CEILING, decide
from app.schemas.json_types import (
    AutomationPolicy,
    CampaignBudget,
    CampaignCriteria,
    RubricBody,
    UnknownDataPolicy,
)

router = APIRouter(prefix="/api", tags=["campaigns"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "campaigns"

# Criteria groups confirmed one by one (principle 2): the mode lock lifts when none remain.
ConfirmItem = Literal["titles", "keywords", "rules", "locations", "work_models", "seniority", "pay_floors",
                      "deprioritise_themes", "unknown_data_policy"]
CRITERIA_ITEMS: tuple[str, ...] = ("titles", "keywords", "rules", "locations", "work_models", "seniority",
                                   "pay_floors", "deprioritise_themes")


class CampaignIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    track_id: uuid.UUID | None = None
    priority: int = 0
    criteria: CampaignCriteria = Field(default_factory=CampaignCriteria)
    unknown_data_policy: UnknownDataPolicy = Field(default_factory=UnknownDataPolicy)
    rubric_id: uuid.UUID | None = None
    automation: AutomationPolicy = Field(default_factory=AutomationPolicy)
    budget: CampaignBudget = Field(default_factory=CampaignBudget)
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    schedule_cron: str | None = Field(default=None, description="None: schedule.sweep_cron")
    preferred_seniority: str | None = None


class CampaignMatchCounts(BaseModel):
    new: int = 0
    shortlisted: int = 0
    held: int = 0


class CampaignOut(CampaignIn, Timestamps):
    status: Literal["draft", "active", "paused", "archived"]
    review_state: Literal["needs_review", "confirmed"]
    confirmed_at: datetime | None = None
    paused_until: date | None = None
    last_sweep_checkpoint: datetime | None = None
    mode_ceiling: Literal["save_only", "prepare", "ask_then_apply", "auto_apply"] = Field(
        description="Highest mode allowed now: 'prepare' until criteria and answers are confirmed")
    unconfirmed: list[ConfirmItem] = Field(
        default_factory=list, description="Criteria items still to confirm; the campaign is confirmed when empty")
    match_counts: CampaignMatchCounts = Field(default_factory=CampaignMatchCounts,
                                              description="Assessed jobs by triage, and held by a conflict group")
    last_run_at: datetime | None = None


class CampaignStatusChange(BaseModel):
    status: Literal["active", "paused", "archived"]
    paused_until: date | None = None


class RulePreviewIn(BaseModel):
    conditions: ConditionSet
    limit: int = Field(default=50, ge=1, le=500)


class RulePreviewOut(BaseModel):
    matched: int
    total: int
    sample_job_ids: list[uuid.UUID]


class RuleFromViewIn(BaseModel):
    """"Use as campaign rule": copy a saved view's conditions into the campaign."""

    view_id: uuid.UUID
    effect: Literal["exclude", "include", "penalty", "bonus"]
    points: int | None = Field(default=None, ge=1, le=100)
    reason: str | None = None


class RubricIn(ApiModel):
    name: str
    body: RubricBody


class RubricOut(RubricIn, Timestamps):
    family: uuid.UUID
    version: int
    status: Literal["draft", "active", "retired"]


class BacktestIn(BaseModel):
    rubric_id: uuid.UUID = Field(description="Draft rubric to test")
    job_ids: list[uuid.UUID] | None = Field(default=None, description="None: recent saved roles")
    campaign_id: uuid.UUID


class BacktestEstimateOut(BaseModel):
    jobs: int = Field(description="Roles in the backtest")
    to_score: int = Field(description="Roles that need a model call (not filtered out, not cached)")
    estimated_cost_minor: int
    estimated_cost_micros: int = 0
    cost_currency: str


class BacktestRow(BaseModel):
    job_id: uuid.UUID
    title: str
    employer: str
    old_score: int | None
    new_score: int | None
    old_rank: int | None
    new_rank: int | None
    crossed: list[Literal["shortlist_up", "shortlist_down", "tailor_up", "tailor_down", "auto_up", "auto_down"]]


class BacktestOut(BaseModel):
    rows: list[BacktestRow]
    estimated_cost_minor: int
    estimated_cost_micros: int = 0
    cost_currency: str


class DryRunOut(BaseModel):
    run_id: uuid.UUID


# ----- helpers ----------------------------------------------------------------------------


def _offset(cursor: str | None) -> int:
    try:
        return filters.decode_cursor(cursor)
    except filters.QueryError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


async def _campaign(session: SessionDep, item_id: uuid.UUID, *, lock: bool = False) -> Campaign:
    campaign = await session.get(Campaign, item_id, with_for_update=lock)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="campaign not found")
    return campaign


def _nonempty_items(criteria: CampaignCriteria, policy: UnknownDataPolicy) -> list[str]:
    items = [name for name in CRITERIA_ITEMS if getattr(criteria, name)]
    if any(v is not None for v in policy.model_dump().values()):
        items.append("unknown_data_policy")
    return items


def _sync_confirmation(campaign: Campaign) -> None:
    if campaign.unconfirmed_items:
        campaign.review_state, campaign.confirmed_at = ReviewState.needs_review, None
    elif campaign.review_state != ReviewState.confirmed:
        campaign.review_state, campaign.confirmed_at = ReviewState.confirmed, utcnow()


async def _schedule(session: SessionDep, campaign: Campaign) -> Schedule | None:
    return await session.scalar(select(Schedule).where(Schedule.campaign_id == campaign.id,
                                                       Schedule.kind == RunKind.sweep).limit(1))


async def _set_schedule(session: SessionDep, campaign: Campaign, cron: str | None) -> None:
    current = await _schedule(session, campaign)
    if cron is None:
        if current is not None:
            await session.delete(current)
        return
    try:
        cron_expr(cron)
    except SettingValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if current is None:
        session.add(Schedule(name=f"Sweep: {campaign.name}", kind=RunKind.sweep, campaign_id=campaign.id, cron=cron))
    else:
        current.cron = cron


async def campaign_out(session: SessionDep, campaign: Campaign) -> CampaignOut:
    await session.flush()
    await session.refresh(campaign)
    schedule = await _schedule(session, campaign)
    counts = dict((await session.execute(
        select(Job.triage, func.count()).join(Assessment, Assessment.job_id == Job.id)
        .where(Assessment.campaign_id == campaign.id).group_by(Job.triage))).all())
    held = await session.scalar(select(func.count()).select_from(Job).join(Assessment, Assessment.job_id == Job.id)
                                .where(Assessment.campaign_id == campaign.id,
                                       Job.conflict_state == ConflictState.held)) or 0
    last_run = await session.scalar(select(func.max(func.coalesce(Run.finished_at, Run.created_at)))
                                    .where(Run.campaign_id == campaign.id))
    confirmed = campaign.review_state == ReviewState.confirmed and not campaign.unconfirmed_items
    return CampaignOut.model_validate({
        **{k: getattr(campaign, k) for k in (
            "id", "created_at", "updated_at", "name", "track_id", "priority", "criteria", "unknown_data_policy",
            "rubric_id", "automation", "budget", "source_ids", "preferred_seniority", "confirmed_at",
            "paused_until", "last_sweep_checkpoint")},
        "status": campaign.status.value, "review_state": campaign.review_state.value,
        "schedule_cron": schedule.cron if schedule else None,
        "mode_ceiling": MODES[-1] if confirmed else UNCONFIRMED_CEILING,
        "unconfirmed": list(campaign.unconfirmed_items),
        "match_counts": CampaignMatchCounts(new=counts.get("new", 0), shortlisted=counts.get("shortlisted", 0),
                                            held=held),
        "last_run_at": last_run,
    })


def _apply(campaign: Campaign, body: CampaignIn) -> list[str]:
    """Copy the editable fields; returns criteria items whose value changed (to re-confirm)."""
    changed = [name for name in CRITERIA_ITEMS
               if getattr(campaign.criteria, name, None) != getattr(body.criteria, name)] \
        if campaign.criteria is not None else _nonempty_items(body.criteria, body.unknown_data_policy)
    if campaign.unknown_data_policy is not None and campaign.unknown_data_policy != body.unknown_data_policy:
        changed.append("unknown_data_policy")
    for key in ("name", "track_id", "priority", "rubric_id", "source_ids", "preferred_seniority"):
        setattr(campaign, key, getattr(body, key))
    campaign.criteria = body.criteria
    campaign.unknown_data_policy = body.unknown_data_policy
    campaign.automation = body.automation
    campaign.budget = body.budget
    return changed


# ----- campaigns --------------------------------------------------------------------------


@router.get("/campaigns", response_model=Page[CampaignOut], name="campaigns_list")
async def list_campaigns(session: SessionDep, cursor: str | None = None, limit: int = 50) -> Page[CampaignOut]:
    offset, limit = _offset(cursor), max(1, min(limit, 200))
    total = await session.scalar(select(func.count()).select_from(Campaign)) or 0
    rows = (await session.scalars(select(Campaign).order_by(Campaign.priority.desc(), Campaign.created_at)
                                  .offset(offset).limit(limit))).all()
    items = [await campaign_out(session, c) for c in rows]
    return Page(items=items, total=total,
                next_cursor=filters.encode_cursor(offset + limit) if offset + limit < total else None)


@router.get("/campaigns/{item_id}", response_model=CampaignOut, name="campaigns_get")
async def get_campaign(item_id: uuid.UUID, session: SessionDep) -> CampaignOut:
    return await campaign_out(session, await _campaign(session, item_id))


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED, name="campaigns_create")
async def create_campaign(body: CampaignIn, session: SessionDep, principal: PrincipalDep) -> CampaignOut:
    campaign = Campaign(status=CampaignStatus.draft, review_state=ReviewState.needs_review)
    _apply(campaign, body)
    campaign.unconfirmed_items = _nonempty_items(body.criteria, body.unknown_data_policy)
    session.add(campaign)
    await session.flush()
    await _set_schedule(session, campaign, body.schedule_cron)
    await audit.record(session, actor=principal.actor, action="campaign.created", subject_type="campaign",
                       subject_id=campaign.id, detail={"name": campaign.name})
    return await campaign_out(session, campaign)


@router.put("/campaigns/{item_id}", response_model=CampaignOut, name="campaigns_update")
async def update_campaign(item_id: uuid.UUID, body: CampaignIn, session: SessionDep,
                          principal: PrincipalDep) -> CampaignOut:
    campaign = await _campaign(session, item_id, lock=True)
    changed = _apply(campaign, body)
    campaign.unconfirmed_items = sorted(set(campaign.unconfirmed_items) | set(changed))
    _sync_confirmation(campaign)
    await _set_schedule(session, campaign, body.schedule_cron)
    await audit.record(session, actor=principal.actor, action="campaign.updated", subject_type="campaign",
                       subject_id=campaign.id, detail={"changed_criteria": changed})
    return await campaign_out(session, campaign)


@router.delete("/campaigns/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               name="campaigns_delete")
async def delete_campaign(item_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> Response:
    campaign = await _campaign(session, item_id)
    await audit.record(session, actor=principal.actor, action="campaign.deleted", subject_type="campaign",
                       subject_id=campaign.id, detail={"name": campaign.name})
    await session.delete(campaign)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/campaigns/{item_id}/status", response_model=CampaignOut, name="campaigns_set_status")
async def set_campaign_status(item_id: uuid.UUID, body: CampaignStatusChange, session: SessionDep,
                              principal: PrincipalDep) -> CampaignOut:
    campaign = await _campaign(session, item_id, lock=True)
    campaign.status = CampaignStatus(body.status)
    campaign.paused_until = body.paused_until if body.status == "paused" else None
    await audit.record(session, actor=principal.actor, action="campaign.status", subject_type="campaign",
                       subject_id=campaign.id, detail={"status": body.status, "paused_until": str(body.paused_until)})
    return await campaign_out(session, campaign)


@router.post("/campaigns/{item_id}/confirm", response_model=CampaignOut, name="campaigns_confirm")
async def confirm_campaign(item_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> CampaignOut:
    """Confirm every remaining criteria item (principle 2). Required before the mode can go above Prepare."""
    campaign = await _campaign(session, item_id, lock=True)
    items = list(campaign.unconfirmed_items)
    campaign.unconfirmed_items = []
    _sync_confirmation(campaign)
    await audit.record(session, actor=principal.actor, action="campaign.confirmed", subject_type="campaign",
                       subject_id=campaign.id, detail={"items": items})
    return await campaign_out(session, campaign)


@router.post("/campaigns/{item_id}/confirm/{item}", response_model=CampaignOut, name="campaigns_confirm_item")
async def confirm_campaign_item(item_id: uuid.UUID, item: ConfirmItem, session: SessionDep,
                                principal: PrincipalDep) -> CampaignOut:
    """Confirm one criteria item; the campaign is confirmed (and the mode lock lifts) when none remain."""
    campaign = await _campaign(session, item_id, lock=True)
    if item not in campaign.unconfirmed_items:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"'{item}' is not awaiting confirmation")
    campaign.unconfirmed_items = [i for i in campaign.unconfirmed_items if i != item]
    _sync_confirmation(campaign)
    await audit.record(session, actor=principal.actor, action="campaign.item_confirmed", subject_type="campaign",
                       subject_id=campaign.id, detail={"item": item, "remaining": campaign.unconfirmed_items})
    return await campaign_out(session, campaign)


@router.post("/campaigns/{item_id}/clone", response_model=CampaignOut, status_code=status.HTTP_201_CREATED,
             name="campaigns_clone")
async def clone_campaign(item_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> CampaignOut:
    """A copy in draft, needing confirmation again."""
    source = await _campaign(session, item_id)
    body = CampaignIn.model_validate((await campaign_out(session, source)).model_dump())
    body.name = f"{source.name} (copy)"[:120]
    copy = Campaign(status=CampaignStatus.draft, review_state=ReviewState.needs_review)
    _apply(copy, body)
    copy.unconfirmed_items = _nonempty_items(body.criteria, body.unknown_data_policy)
    session.add(copy)
    await session.flush()
    await _set_schedule(session, copy, body.schedule_cron)
    await audit.record(session, actor=principal.actor, action="campaign.cloned", subject_type="campaign",
                       subject_id=copy.id, detail={"from": str(source.id)})
    return await campaign_out(session, copy)


async def _add_rule(session: SessionDep, campaign: Campaign, rule: CampaignRule, actor: str,
                    origin: dict[str, str] | None = None) -> CampaignOut:
    campaign.criteria = campaign.criteria.model_copy(update={"rules": [*campaign.criteria.rules, rule]})
    campaign.unconfirmed_items = sorted(set(campaign.unconfirmed_items) | {"rules"})
    _sync_confirmation(campaign)
    await audit.record(session, actor=actor, action="campaign.rule_added", subject_type="campaign",
                       subject_id=campaign.id, detail={"effect": rule.effect, "reason": rule.reason, **(origin or {})})
    return await campaign_out(session, campaign)


@router.post("/campaigns/{item_id}/rules", response_model=CampaignOut, name="campaigns_add_rule")
async def add_campaign_rule(item_id: uuid.UUID, body: CampaignRule, session: SessionDep,
                            principal: PrincipalDep) -> CampaignOut:
    """"Use as campaign rule": copies a view's conditions into the campaign as a rule."""
    return await _add_rule(session, await _campaign(session, item_id, lock=True), body, principal.actor)


@router.post("/campaigns/{item_id}/rules/from-view", response_model=CampaignOut, name="campaigns_rule_from_view")
async def add_rule_from_view(item_id: uuid.UUID, body: RuleFromViewIn, session: SessionDep,
                             principal: PrincipalDep) -> CampaignOut:
    """Convert a saved view into an exclusion, an inclusion, or a scoring penalty or bonus."""
    view = await session.get(SavedView, body.view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="view not found")
    try:
        rule = filters.view_to_rule(view.body, body.effect, points=body.points, reason=body.reason or view.name)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return await _add_rule(session, await _campaign(session, item_id, lock=True), rule, principal.actor,
                           {"view_id": str(view.id)})


@router.post("/campaigns/{item_id}/preview", response_model=RulePreviewOut, name="campaigns_preview_rule")
async def preview_rule(item_id: uuid.UUID, body: RulePreviewIn, session: SessionDep) -> RulePreviewOut:
    """What a rule would match among saved jobs. Reads only."""
    await _campaign(session, item_id)
    records = [r for _, r in await filters.load_records(session, now=utcnow())]
    result = filters.preview(body.conditions, records, body.limit)
    return RulePreviewOut(matched=result.matched, total=result.total,
                          sample_job_ids=[uuid.UUID(i) for i in result.sample_ids])


@router.post("/campaigns/{item_id}/dry-run", response_model=DryRunOut, status_code=status.HTTP_202_ACCEPTED,
             name="campaigns_dry_run")
async def dry_run(item_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> DryRunOut:
    """Run the decision table over saved jobs with this campaign as it stands; nothing is changed
    except the run record (counts per verdict). No model calls and no fetching."""
    campaign = await _campaign(session, item_id)
    now = utcnow()
    settings, versions = await scoring.setting_versions(session)
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    crecord = filters.campaign_record(campaign)
    assessments = {a.job_id: a for a in (await session.scalars(
        select(Assessment).where(Assessment.campaign_id == campaign.id))).all()}
    counts: dict[str, int] = {}
    for job, record in await filters.load_records(session, now=now):
        a = assessments.get(job.id)
        decision = decide(scoring.decision_input(
            now=now, record=record, crecord=crecord, settings=settings, versions=versions, rubric=rubric,
            base_score=a.base_score if a and a.state == AssessmentState.scored else None, job=job,
            override=a.override.model_dump() if a and a.override else None, purpose="dry_run"))
        counts[decision.verdict] = counts.get(decision.verdict, 0) + 1
    run = Run(kind=RunKind.sweep, trigger="api", campaign_id=campaign.id, dry_run=True, counts=counts,
              status=RunStatus.succeeded, started_at=now, finished_at=utcnow(),
              config_versions={"campaign": crecord["version"], "rubric": rubric.version if rubric else None,
                               "settings": {k: v for k, v in versions.items() if v}})
    session.add(run)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="campaign.dry_run", subject_type="campaign",
                       subject_id=campaign.id, detail={"run_id": str(run.id), "counts": counts})
    return DryRunOut(run_id=run.id)


# ----- rubrics ----------------------------------------------------------------------------


def _rubric_out(rubric: Rubric) -> RubricOut:
    return RubricOut.model_validate({"id": rubric.id, "created_at": rubric.created_at,
                                     "updated_at": rubric.updated_at, "name": rubric.name, "body": rubric.body,
                                     "family": rubric.family, "version": rubric.version,
                                     "status": getattr(rubric.status, "value", rubric.status)})


async def _rubric(session: SessionDep, item_id: uuid.UUID) -> Rubric:
    rubric = await session.get(Rubric, item_id)
    if rubric is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rubric not found")
    return rubric


@router.get("/rubrics", response_model=Page[RubricOut], name="rubrics_list")
async def list_rubrics(session: SessionDep, cursor: str | None = None, limit: int = 50) -> Page[RubricOut]:
    offset, limit = _offset(cursor), max(1, min(limit, 200))
    total = await session.scalar(select(func.count()).select_from(Rubric)) or 0
    rows = (await session.scalars(select(Rubric).order_by(Rubric.name, Rubric.family, Rubric.version.desc())
                                  .offset(offset).limit(limit))).all()
    return Page(items=[_rubric_out(r) for r in rows], total=total,
                next_cursor=filters.encode_cursor(offset + limit) if offset + limit < total else None)


@router.get("/rubrics/{item_id}", response_model=RubricOut, name="rubrics_get")
async def get_rubric(item_id: uuid.UUID, session: SessionDep) -> RubricOut:
    return _rubric_out(await _rubric(session, item_id))


@router.post("/rubrics", response_model=RubricOut, status_code=status.HTTP_201_CREATED, name="rubrics_create")
async def create_rubric(body: RubricIn, session: SessionDep, principal: PrincipalDep) -> RubricOut:
    """A new rubric family, as draft version 1 (weights must sum to 100)."""
    rubric = Rubric(name=body.name, body=body.body, version=1, status=RubricStatus.draft, family=uuid.uuid4())
    session.add(rubric)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="rubric.created", subject_type="rubric",
                       subject_id=rubric.id, detail={"name": rubric.name})
    await session.refresh(rubric)
    return _rubric_out(rubric)


@router.put("/rubrics/{item_id}", response_model=RubricOut, name="rubrics_update")
async def update_rubric(item_id: uuid.UUID, body: RubricIn, session: SessionDep, principal: PrincipalDep
                        ) -> RubricOut:
    """Edits a draft in place. Editing an active or retired version creates a new draft version."""
    rubric = await _rubric(session, item_id)
    if rubric.status == RubricStatus.draft:
        rubric.name, rubric.body = body.name, body.body
    else:
        latest = await session.scalar(select(func.max(Rubric.version)).where(Rubric.family == rubric.family))
        rubric = Rubric(name=body.name, body=body.body, family=rubric.family, version=(latest or 0) + 1,
                        status=RubricStatus.draft)
        session.add(rubric)
    await session.flush()
    await audit.record(session, actor=principal.actor, action="rubric.updated", subject_type="rubric",
                       subject_id=rubric.id, detail={"version": rubric.version})
    await session.refresh(rubric)
    return _rubric_out(rubric)


@router.post("/rubrics/{item_id}/activate", response_model=RubricOut, name="rubrics_activate")
async def activate_rubric(item_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> RubricOut:
    """Activating creates a new version; earlier assessments keep their version."""
    rubric = await _rubric(session, item_id)
    if rubric.status == RubricStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already active")
    new = await scoring.activate(session, rubric)
    await audit.record(session, actor=principal.actor, action="rubric.activated", subject_type="rubric",
                       subject_id=new.id, detail={"from": str(rubric.id), "version": new.version})
    await session.refresh(new)
    return _rubric_out(new)


async def _backtest(session: SessionDep, body: BacktestIn, estimate_only: bool) -> scoring.BacktestResult:
    draft = await _rubric(session, body.rubric_id)
    campaign = await _campaign(session, body.campaign_id)
    client = await scoring.client_for(session)
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="no AI provider configured")
    return await scoring.backtest(session, draft, campaign, body.job_ids, client=client,
                                  estimate_only=estimate_only)


@router.post("/rubrics/backtest/estimate", response_model=BacktestEstimateOut, name="rubrics_backtest_estimate")
async def backtest_estimate(body: BacktestIn, session: SessionDep) -> BacktestEstimateOut:
    """Step one: how many roles and what the backtest would cost. Spends nothing."""
    result = await _backtest(session, body, estimate_only=True)
    return BacktestEstimateOut(jobs=len(result.rows), to_score=result.to_score,
                               estimated_cost_minor=micros_to_minor(result.estimated_cost_micros),
                               estimated_cost_micros=result.estimated_cost_micros,
                               cost_currency=result.currency)


@router.post("/rubrics/backtest", response_model=BacktestOut, name="rubrics_backtest")
async def backtest(body: BacktestIn, session: SessionDep, principal: PrincipalDep) -> BacktestOut:
    """Step two: score the roles with the draft rubric (old vs new, ranks, threshold crossings).
    Stored assessments are not changed."""
    result = await _backtest(session, body, estimate_only=False)
    await audit.record(session, actor=principal.actor, action="rubric.backtested", subject_type="rubric",
                       subject_id=body.rubric_id,
                       detail={"jobs": len(result.rows), "campaign_id": str(body.campaign_id),
                               "estimated_cost_minor": micros_to_minor(result.estimated_cost_micros)})
    return BacktestOut(rows=[BacktestRow.model_validate(r) for r in result.rows],
                       estimated_cost_minor=micros_to_minor(result.estimated_cost_micros),
                       estimated_cost_micros=result.estimated_cost_micros,
                       cost_currency=result.currency)
