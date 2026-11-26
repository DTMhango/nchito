"""Search aggregate: campaigns, rubrics, sources, jobs, assessments, runs, schedules (DESIGN.md 4, 6, 7, 18)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.conditions import ConditionSet
from app.models.base import Base, Entity, Origin, PydanticJSON, ReviewState, str_enum
from app.schemas.json_types import (
    AutomationPolicy,
    CampaignBudget,
    CampaignCriteria,
    CriterionRating,
    CustomFacetValue,
    FilterResult,
    JobFacets,
    Override,
    RateLimit,
    Requirement,
    RubricBody,
    SavedViewBody,
    SourceHealth,
    SourceRunResult,
    StructuredLocation,
    UnknownDataPolicy,
)


class CampaignStatus(enum.StrEnum):
    draft = "draft"
    active = "active"
    paused = "paused"
    archived = "archived"


class Campaign(Base, Entity):
    __tablename__ = "campaign"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    track_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("track.id", ondelete="SET NULL"))
    status: Mapped[CampaignStatus] = mapped_column(str_enum(CampaignStatus), nullable=False,
                                                   default=CampaignStatus.draft)
    review_state: Mapped[ReviewState] = mapped_column(str_enum(ReviewState), nullable=False,
                                                      default=ReviewState.needs_review)
    origin: Mapped[Origin] = mapped_column(str_enum(Origin), nullable=False, default=Origin.owner)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criteria: Mapped[CampaignCriteria] = mapped_column(PydanticJSON(CampaignCriteria), nullable=False,
                                                       default=CampaignCriteria)
    unknown_data_policy: Mapped[UnknownDataPolicy] = mapped_column(
        PydanticJSON(UnknownDataPolicy), nullable=False, default=UnknownDataPolicy)
    rubric_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rubric.id", ondelete="SET NULL"))
    automation: Mapped[AutomationPolicy] = mapped_column(PydanticJSON(AutomationPolicy), nullable=False,
                                                         default=AutomationPolicy)
    budget: Mapped[CampaignBudget] = mapped_column(PydanticJSON(CampaignBudget), nullable=False,
                                                   default=CampaignBudget)
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False, default=list)
    paused_until: Mapped[date | None] = mapped_column(Date)
    preferred_seniority: Mapped[str | None] = mapped_column(String(60))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sweep_checkpoint: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RubricStatus(enum.StrEnum):
    draft = "draft"
    active = "active"
    retired = "retired"


class Rubric(Base, Entity):
    __tablename__ = "rubric"
    __table_args__ = (UniqueConstraint("family", "version", name="family_version"),)

    family: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, default=uuid.uuid4,
                                              doc="Versions of one rubric share a family id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body: Mapped[RubricBody] = mapped_column(PydanticJSON(RubricBody), nullable=False)
    status: Mapped[RubricStatus] = mapped_column(str_enum(RubricStatus), nullable=False,
                                                 default=RubricStatus.draft)


class SourceAccess(enum.StrEnum):
    api = "api"
    feed = "feed"
    html = "html"
    agent = "agent"
    email = "email"


class Source(Base, Entity):
    __tablename__ = "source"

    connector: Mapped[str] = mapped_column(String(40), nullable=False, doc="greenhouse, lever, workday, rss, ...")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    access: Mapped[SourceAccess] = mapped_column(str_enum(SourceAccess), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    access_notes: Mapped[str | None] = mapped_column(Text)
    rate_limit: Mapped[RateLimit] = mapped_column(PydanticJSON(RateLimit), nullable=False, default=RateLimit)
    health: Mapped[SourceHealth] = mapped_column(PydanticJSON(SourceHealth), nullable=False, default=SourceHealth)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permitted_actions: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), nullable=False, default=list, doc="search, fetch, check_open, apply_email, apply_browser"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SavedView(Base, Entity):
    __tablename__ = "saved_view"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[SavedViewBody] = mapped_column(PydanticJSON(SavedViewBody), nullable=False, default=SavedViewBody)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TagRule(Base, Entity):
    __tablename__ = "tag_rule"

    tag: Mapped[str] = mapped_column(String(60), nullable=False)
    conditions: Mapped[ConditionSet] = mapped_column(PydanticJSON(ConditionSet), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CustomFacet(Base, Entity):
    __tablename__ = "custom_facet"

    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SkillAlias(Base, Entity):
    __tablename__ = "skill_alias"

    alias: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    canonical: Mapped[str] = mapped_column(String(120), nullable=False, index=True)


class WatchedEmployer(Base, Entity):
    __tablename__ = "watched_employer"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    board_type: Mapped[str] = mapped_column(String(30), nullable=False)
    board_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_days: Mapped[int | None] = mapped_column(Integer, doc="Overrides matching.employer_cooldown_days")
    always_ask_first: Mapped[bool] = mapped_column(Boolean, default=False)


class EmployerAlias(Base, Entity):
    """Subsidiaries and brands merged to one canonical employer (7.1)."""

    __tablename__ = "employer_alias"

    alias: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    canonical: Mapped[str] = mapped_column(String(200), nullable=False, index=True)


class TrustedSite(Base, Entity):
    """Application systems trusted for unattended browser submission (18.1)."""

    __tablename__ = "trusted_site"

    domain: Mapped[str] = mapped_column(String(253), unique=True, nullable=False,
                                        doc="Suffix match, e.g. greenhouse.io")
    system: Mapped[str | None] = mapped_column(String(60))
    trusted_by: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class ConflictState(enum.StrEnum):
    none = "none"
    winner = "winner"
    held = "held"
    released = "released"


class PayState(enum.StrEnum):
    stated = "stated"
    estimated = "estimated"
    not_stated = "not_stated"


class DeadlineState(enum.StrEnum):
    dated = "dated"
    open_until_filled = "open_until_filled"
    not_stated = "not_stated"


class Availability(enum.StrEnum):
    open = "open"
    closed = "closed"
    unknown = "unknown"


class Job(Base, Entity):
    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_employer_function", "canonical_employer", "function"),
        Index("ix_job_content_hash", "content_hash"),
        Index("ix_job_requisition", "canonical_employer", "requisition_id"),
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    employer: Mapped[str] = mapped_column(String(200), nullable=False, doc="As posted")
    canonical_employer: Mapped[str] = mapped_column(String(200), nullable=False)
    recruiter: Mapped[str | None] = mapped_column(String(200), doc="When posted by an agency")
    requisition_id: Mapped[str | None] = mapped_column(String(120))
    function: Mapped[str | None] = mapped_column(String(120), doc="Department/function; unknown counts as same")
    level: Mapped[str | None] = mapped_column(String(60))
    conflict_state: Mapped[ConflictState] = mapped_column(str_enum(ConflictState), nullable=False,
                                                          default=ConflictState.none)
    conflict_note: Mapped[str | None] = mapped_column(Text)
    facets: Mapped[JobFacets] = mapped_column(PydanticJSON(JobFacets), nullable=False, default=JobFacets)
    custom_facets: Mapped[dict[str, CustomFacetValue]] = mapped_column(
        PydanticJSON(dict[str, CustomFacetValue]), nullable=False, default=dict)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    location: Mapped[StructuredLocation] = mapped_column(PydanticJSON(StructuredLocation), nullable=False,
                                                         default=StructuredLocation)
    pay_state: Mapped[PayState] = mapped_column(str_enum(PayState), nullable=False, default=PayState.not_stated)
    pay_min_minor: Mapped[int | None] = mapped_column(BigInteger, doc="Stated pay only; estimates are in pay_estimate")
    pay_max_minor: Mapped[int | None] = mapped_column(BigInteger)
    pay_currency: Mapped[str | None] = mapped_column(String(3))
    pay_period: Mapped[str | None] = mapped_column(String(10))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_state: Mapped[DeadlineState] = mapped_column(str_enum(DeadlineState), nullable=False,
                                                          default=DeadlineState.not_stated)
    deadline: Mapped[date | None] = mapped_column(Date)
    apply_url: Mapped[str | None] = mapped_column(Text)
    apply_method: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown",
                                              doc="email, greenhouse, lever, workday, ..., unknown")
    apply_email: Mapped[str | None] = mapped_column(String(320))
    requirements: Mapped[list[Requirement]] = mapped_column(PydanticJSON(list[Requirement]), nullable=False,
                                                            default=list)
    raw_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    availability: Mapped[Availability] = mapped_column(str_enum(Availability), nullable=False,
                                                       default=Availability.unknown)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triage: Mapped[str] = mapped_column(String(20), nullable=False, default="new",
                                        doc="new, shortlisted, below_threshold, archived, skipped")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    repost_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"))


class PayEstimate(Base, Entity):
    """Estimated pay, stored apart from the posting with its source and assumptions (7)."""

    __tablename__ = "pay_estimate"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    min_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False, default="year")
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    estimated_on: Mapped[date] = mapped_column(Date, nullable=False)
    assumptions: Mapped[str | None] = mapped_column(Text)


class ExtractionCache(Base, Entity):
    """Model extraction results, keyed on (content hash, prompt version, model), so unchanged
    postings are never sent to a model twice (DESIGN 6, 11)."""

    __tablename__ = "extraction_cache"

    cache_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_currency: Mapped[str | None] = mapped_column(String(3))


class JobSighting(Base, Entity):
    __tablename__ = "job_sighting"
    __table_args__ = (UniqueConstraint("job_id", "source_id", "url", name="job_source_url"),)

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Assessment(Base, Entity):
    __tablename__ = "assessment"
    __table_args__ = (Index("ix_assessment_job_campaign", "job_id", "campaign_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False)
    rubric_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rubric.id", ondelete="SET NULL"))
    rubric_version: Mapped[int | None] = mapped_column(Integer)
    filter_results: Mapped[list[FilterResult]] = mapped_column(PydanticJSON(list[FilterResult]), nullable=False,
                                                               default=list)
    ratings: Mapped[list[CriterionRating]] = mapped_column(PydanticJSON(list[CriterionRating]), nullable=False,
                                                           default=list)
    score: Mapped[int | None] = mapped_column(Integer)
    gaps: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    model: Mapped[str | None] = mapped_column(String(128))
    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    override: Mapped[Override | None] = mapped_column(PydanticJSON(Override))
    cache_key: Mapped[str | None] = mapped_column(String(128), index=True,
                                                  doc="hash(job, kit version, rubric version, prompt version, model)")
    is_conflict_winner: Mapped[bool] = mapped_column(Boolean, default=False)


class RunKind(enum.StrEnum):
    sweep = "sweep"
    rescore = "rescore"
    expiry_check = "expiry_check"
    digest = "digest"
    backup = "backup"
    retention = "retention"


class RunStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"
    cancelled = "cancelled"
    skipped = "skipped"


class Run(Base, Entity):
    __tablename__ = "run"
    __table_args__ = (Index("ix_run_schedule_status", "schedule_id", "status"),)

    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False, doc="schedule, catch_up, manual, api")
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign.id", ondelete="SET NULL"))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schedule.id", ondelete="SET NULL"))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    counts: Mapped[dict[str, int]] = mapped_column(PydanticJSON(dict[str, int]), nullable=False, default=dict)
    source_results: Mapped[list[SourceRunResult]] = mapped_column(PydanticJSON(list[SourceRunResult]),
                                                                  nullable=False, default=list)
    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    config_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus), nullable=False, default=RunStatus.queued)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Schedule(Base, Entity):
    """A UI-editable schedule read by the one-minute scheduler tick (croniter)."""

    __tablename__ = "schedule"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[RunKind] = mapped_column(str_enum(RunKind), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    cron: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), doc="None: general.timezone")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL", use_alter=True, name="fk_schedule_last_run_id_run"))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
