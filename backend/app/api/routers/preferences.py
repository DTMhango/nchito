"""Preference feedback, rubric suggestions and the policy preview (wave 4 feedback stream).

Feedback is evidence only and never changes a score. Suggestions are proposals the owner accepts,
edits or dismisses; accepting a rubric change creates a new rubric version. The policy preview runs the
decision table over recent roles and writes nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.common import Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core.clock import utcnow
from app.models.platform import AuditEvent
from app.models.preferences import PreferenceFeedback, PreferenceSuggestion
from app.models.search import Campaign, Job
from app.pipeline import filters, policy_preview, preferences, scoring
from app.schemas.json_types import (
    AutomationPolicy,
    CampaignCriteria,
    FeedbackReason,
    FeedbackVerdict,
    RubricThresholds,
    SuggestionBacktest,
    SuggestionChange,
    SuggestionEvidence,
    SuggestionKind,
    SuggestionStatus,
    UnknownDataPolicy,
)

router = APIRouter(prefix="/api", tags=["preferences"], dependencies=[RequireOwner])


# ----- models -----------------------------------------------------------------------------------


class FeedbackIn(BaseModel):
    campaign_id: uuid.UUID | None = Field(default=None, description="The match's campaign; default: the "
                                                                    "campaign that scored the role highest")
    verdict: FeedbackVerdict
    reasons: list[FeedbackReason] = Field(default_factory=list)
    note: str | None = Field(default=None, description="Free text; kept as evidence, never an instruction")


class FeedbackOut(Timestamps):
    job_id: uuid.UUID
    campaign_id: uuid.UUID | None
    verdict: FeedbackVerdict
    reasons: list[FeedbackReason]
    note: str | None
    score_at: int | None
    rubric_version: int | None
    actor: str
    job_title: str | None = None
    employer: str | None = None


class SuggestionOut(Timestamps):
    campaign_id: uuid.UUID
    kind: SuggestionKind
    target: str
    title: str
    change: SuggestionChange
    evidence: SuggestionEvidence
    backtest: SuggestionBacktest | None
    rubric_id: uuid.UUID | None
    status: SuggestionStatus
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    result: dict[str, Any]


class OwnerOnlyNoteOut(BaseModel):
    area: str
    down: int
    feedback_ids: list[str]
    message: str


class AnalyseIn(BaseModel):
    campaign_id: uuid.UUID


class AnalyseOut(BaseModel):
    created: list[SuggestionOut]
    kept: int = Field(description="Suggestions already raised (or dismissed) for the same evidence")
    up: int
    down: int
    owner_only: list[OwnerOnlyNoteOut]


class PreferencesSummaryOut(BaseModel):
    campaign_id: uuid.UUID
    up: int
    down: int
    open_suggestions: int
    owner_only: list[OwnerOnlyNoteOut]
    last_analysed_at: datetime | None


class SuggestionEditIn(BaseModel):
    change: SuggestionChange | None = Field(default=None, description="The owner's edit; default: as suggested")


class AcceptIn(SuggestionEditIn):
    note: str | None = None


class DismissIn(BaseModel):
    note: str | None = None


class PolicyPreviewIn(BaseModel):
    days: int | None = Field(default=None, description="Window of recent roles; default preferences.preview_days")
    automation: AutomationPolicy | None = None
    thresholds: RubricThresholds | None = Field(default=None, description="Rubric thresholds to try")
    criteria: CampaignCriteria | None = None
    unknown_data_policy: UnknownDataPolicy | None = None
    settings: dict[str, Any] = Field(default_factory=dict, description="Autopilot limits and global thresholds "
                                                                       "to try (caps, quiet hours, thresholds)")


class PreviewThresholds(BaseModel):
    shortlist: int
    tailor: int
    auto_apply: int


class PreviewBin(BaseModel):
    start: int
    end: int
    count: int


class PreviewLine(BaseModel):
    would_apply: int = Field(description="Roles that would have gone automatically in the window, caps applied")
    by_channel: dict[str, int]
    held: int = Field(description="Runner-ups held by their employer group")
    capped: int = Field(description="Qualifying roles the daily or weekly cap would have held back")
    qualifying: int


class PreviewChange(BaseModel):
    job_id: uuid.UUID
    title: str
    employer: str
    score: int | None
    before: str
    after: str
    change: str = Field(description="newly_automatic, newly_blocked or changed")
    reasons: list[str]


class PreviewUnknown(BaseModel):
    gate: str
    count: int
    message: str


class PreviewCaps(BaseModel):
    daily_cap: int
    weekly_cap: int
    sent_today: int
    sent_week: int
    run_now_would_send: int
    quiet_hours: str | None
    quiet_now: bool | None
    needs_open_check: int


class PolicyPreviewOut(BaseModel):
    campaign_id: uuid.UUID
    window_days: int
    jobs: int
    thresholds: PreviewThresholds
    baseline_thresholds: PreviewThresholds
    histogram: list[PreviewBin]
    unscored: int
    line: PreviewLine
    baseline_line: PreviewLine
    run_now: dict[str, int] = Field(description="Dry-run actions for a run right now, by action")
    changes: list[PreviewChange]
    changes_total: int
    unknowns: list[PreviewUnknown]
    caps: PreviewCaps


# ----- helpers ----------------------------------------------------------------------------------


async def _campaign(session: SessionDep, campaign_id: uuid.UUID) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="campaign not found")
    return campaign


async def _suggestion(session: SessionDep, item_id: uuid.UUID, *, lock: bool = False) -> PreferenceSuggestion:
    row = await session.get(PreferenceSuggestion, item_id, with_for_update=lock)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="suggestion not found")
    return row


def _feedback_out(row: PreferenceFeedback, job: Job | None = None) -> FeedbackOut:
    return FeedbackOut.model_validate({
        "id": row.id, "created_at": row.created_at, "updated_at": row.updated_at, "job_id": row.job_id,
        "campaign_id": row.campaign_id, "verdict": row.verdict, "reasons": row.reasons, "note": row.note,
        "score_at": row.score_at, "rubric_version": row.rubric_version, "actor": row.actor,
        "job_title": job.title if job else None, "employer": job.employer if job else None})


def _suggestion_out(row: PreferenceSuggestion) -> SuggestionOut:
    return SuggestionOut.model_validate({k: getattr(row, k) for k in SuggestionOut.model_fields})


def _notes(notes: list[preferences.OwnerOnlyNote]) -> list[OwnerOnlyNoteOut]:
    return [OwnerOnlyNoteOut(area=n.area, down=n.down, feedback_ids=n.feedback_ids, message=n.message) for n in notes]


def _offset(cursor: str | None) -> int:
    try:
        return filters.decode_cursor(cursor)
    except filters.QueryError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


# ----- feedback ---------------------------------------------------------------------------------


@router.put("/jobs/{job_id}/feedback", response_model=FeedbackOut, name="feedback_put")
async def put_feedback(job_id: uuid.UUID, body: FeedbackIn, session: SessionDep, principal: PrincipalDep
                       ) -> FeedbackOut:
    """Thumbs up or down on a match, with optional reasons. Stored as evidence; no score changes."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    try:
        row = await preferences.record_feedback(session, job, campaign_id=body.campaign_id, verdict=body.verdict,
                                                reasons=body.reasons, note=body.note, actor=principal.actor)
    except preferences.FeedbackError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await session.refresh(row)
    return _feedback_out(row, job)


@router.get("/jobs/{job_id}/feedback", response_model=list[FeedbackOut], name="feedback_for_job")
async def job_feedback(job_id: uuid.UUID, session: SessionDep) -> list[FeedbackOut]:
    job = await session.get(Job, job_id)
    rows = (await session.scalars(select(PreferenceFeedback).where(PreferenceFeedback.job_id == job_id)
                                  .order_by(PreferenceFeedback.created_at))).all()
    return [_feedback_out(r, job) for r in rows]


@router.delete("/jobs/{job_id}/feedback", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
               name="feedback_withdraw")
async def withdraw_feedback(job_id: uuid.UUID, session: SessionDep, principal: PrincipalDep,
                            campaign_id: uuid.UUID | None = None) -> Response:
    if not await preferences.withdraw_feedback(session, job_id, campaign_id, actor=principal.actor):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no feedback on this match")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences/feedback", response_model=Page[FeedbackOut], name="feedback_list")
async def list_feedback(session: SessionDep, campaign_id: uuid.UUID | None = None,
                        verdict: FeedbackVerdict | None = None, cursor: str | None = None,
                        limit: int = Query(default=50, ge=1, le=200)) -> Page[FeedbackOut]:
    stmt = select(PreferenceFeedback, Job).join(Job, Job.id == PreferenceFeedback.job_id)
    if campaign_id is not None:
        stmt = stmt.where(PreferenceFeedback.campaign_id == campaign_id)
    if verdict is not None:
        stmt = stmt.where(PreferenceFeedback.verdict == verdict)
    offset = _offset(cursor)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await session.execute(stmt.order_by(PreferenceFeedback.updated_at.desc(), PreferenceFeedback.id)
                                  .offset(offset).limit(limit))).all()
    return Page(items=[_feedback_out(f, j) for f, j in rows], total=total,
                next_cursor=filters.encode_cursor(offset + limit) if offset + limit < total else None)


# ----- suggestions ------------------------------------------------------------------------------


@router.get("/preferences/summary", response_model=PreferencesSummaryOut, name="preferences_summary")
async def summary(campaign_id: uuid.UUID, session: SessionDep) -> PreferencesSummaryOut:
    """Counts of the evidence, open suggestions and owner-only notes for one campaign. Reads only."""
    campaign = await _campaign(session, campaign_id)
    group = await preferences.signals(session, campaign, now=utcnow())
    open_count = await session.scalar(select(func.count()).select_from(PreferenceSuggestion).where(
        PreferenceSuggestion.campaign_id == campaign_id, PreferenceSuggestion.status == "open")) or 0
    last = await session.scalar(select(func.max(AuditEvent.created_at)).where(
        AuditEvent.action == "preferences.analysed", AuditEvent.subject_id == str(campaign_id)))
    return PreferencesSummaryOut(campaign_id=campaign_id, up=sum(s.liked for s in group),
                                 down=sum(not s.liked for s in group), open_suggestions=open_count,
                                 owner_only=_notes(preferences.owner_only_notes(group)), last_analysed_at=last)


@router.post("/preferences/analyse", response_model=AnalyseOut, name="preferences_analyse")
async def analyse(body: AnalyseIn, session: SessionDep, principal: PrincipalDep) -> AnalyseOut:
    """Turn the campaign's feedback and outcomes into suggestions now (also runs periodically)."""
    campaign = await _campaign(session, body.campaign_id)
    result = await preferences.generate(session, campaign, actor=principal.actor)
    for row in result.created:
        await session.refresh(row)
    return AnalyseOut(created=[_suggestion_out(r) for r in result.created], kept=result.kept, up=result.up,
                      down=result.down, owner_only=_notes(result.owner_only))


@router.get("/preferences/suggestions", response_model=Page[SuggestionOut], name="suggestions_list")
async def list_suggestions(session: SessionDep, campaign_id: uuid.UUID | None = None,
                           status_: SuggestionStatus | None = Query(default="open", alias="status"),
                           cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200)
                           ) -> Page[SuggestionOut]:
    stmt = select(PreferenceSuggestion)
    if campaign_id is not None:
        stmt = stmt.where(PreferenceSuggestion.campaign_id == campaign_id)
    if status_ is not None:
        stmt = stmt.where(PreferenceSuggestion.status == status_)
    offset = _offset(cursor)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await session.scalars(stmt.order_by(PreferenceSuggestion.created_at.desc(), PreferenceSuggestion.id)
                                  .offset(offset).limit(limit))).all()
    return Page(items=[_suggestion_out(r) for r in rows], total=total,
                next_cursor=filters.encode_cursor(offset + limit) if offset + limit < total else None)


@router.get("/preferences/suggestions/{item_id}", response_model=SuggestionOut, name="suggestions_get")
async def get_suggestion(item_id: uuid.UUID, session: SessionDep) -> SuggestionOut:
    return _suggestion_out(await _suggestion(session, item_id))


@router.post("/preferences/suggestions/{item_id}/backtest", response_model=SuggestionBacktest,
             name="suggestions_backtest")
async def backtest_suggestion(item_id: uuid.UUID, body: SuggestionEditIn, session: SessionDep
                              ) -> SuggestionBacktest:
    """Replay the suggestion (or an edit of it) over recent roles. No model calls; nothing is saved."""
    row = await _suggestion(session, item_id)
    campaign = await _campaign(session, row.campaign_id)
    change = body.change if body.change is not None else preferences.parse_change(row.change)
    if change.kind != row.kind:
        raise HTTPException(422, detail="an edit keeps the kind of change")
    try:
        preferences.guard(change, await scoring.active_rubric(session, campaign.rubric_id))
    except preferences.ForbiddenChange as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return await preferences.backtest(session, campaign, change)


@router.post("/preferences/suggestions/{item_id}/accept", response_model=SuggestionOut, name="suggestions_accept",
             responses={409: {"description": "Already decided, or the rubric moved on"},
                        422: {"description": "The (edited) change is owner-only ground"}})
async def accept_suggestion(item_id: uuid.UUID, body: AcceptIn, session: SessionDep, principal: PrincipalDep
                            ) -> SuggestionOut:
    """Apply it as suggested or as edited. A rubric change creates a new rubric version. Audited."""
    row = await _suggestion(session, item_id, lock=True)
    try:
        await preferences.accept(session, row, actor=principal.actor,
                                 change=body.change.model_dump(mode="json") if body.change else None, note=body.note)
    except preferences.StaleSuggestion as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except preferences.ForbiddenChange as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await session.refresh(row)
    return _suggestion_out(row)


@router.post("/preferences/suggestions/{item_id}/dismiss", response_model=SuggestionOut,
             name="suggestions_dismiss", responses={409: {"description": "Already decided"}})
async def dismiss_suggestion(item_id: uuid.UUID, body: DismissIn, session: SessionDep, principal: PrincipalDep
                             ) -> SuggestionOut:
    """Not raised again for the same evidence."""
    row = await _suggestion(session, item_id, lock=True)
    try:
        await preferences.dismiss(session, row, actor=principal.actor, note=body.note)
    except preferences.StaleSuggestion as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.refresh(row)
    return _suggestion_out(row)


# ----- policy preview ---------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/policy-preview", response_model=PolicyPreviewOut,
             name="campaigns_policy_preview")
async def policy_preview_endpoint(campaign_id: uuid.UUID, body: PolicyPreviewIn, session: SessionDep
                                  ) -> PolicyPreviewOut:
    """What a policy change would do to recent roles, through the decision table. Writes nothing."""
    campaign = await _campaign(session, campaign_id)
    proposal = policy_preview.Proposal(automation=body.automation, thresholds=body.thresholds,
                                       criteria=body.criteria, unknown_data_policy=body.unknown_data_policy,
                                       settings=body.settings)
    try:
        result = await policy_preview.preview(session, campaign, proposal, days=body.days)
    except policy_preview.PreviewError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    def line(value: policy_preview.Line) -> PreviewLine:
        return PreviewLine(would_apply=value.would_apply, by_channel=value.by_channel, held=value.held,
                           capped=value.capped, qualifying=value.qualifying)

    return PolicyPreviewOut(
        campaign_id=campaign_id, window_days=result.window_days, jobs=result.jobs,
        thresholds=PreviewThresholds(**result.thresholds),
        baseline_thresholds=PreviewThresholds(**result.baseline_thresholds),
        histogram=[PreviewBin(start=lo, end=hi, count=n) for lo, hi, n in result.bins], unscored=result.unscored,
        line=line(result.line), baseline_line=line(result.baseline_line), run_now=result.run_now,
        changes=[PreviewChange(job_id=c.outcome.job.id, title=c.outcome.job.title, employer=c.outcome.job.employer,
                               score=c.outcome.score, before=c.before.action, after=c.outcome.action, change=c.kind,
                               reasons=c.reasons) for c in result.changes],
        changes_total=result.changes_total,
        unknowns=[PreviewUnknown(gate=u.gate, count=u.count, message=u.message) for u in result.unknowns],
        caps=PreviewCaps(**result.caps.__dict__))
