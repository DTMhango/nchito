"""Pydantic shapes for every JSONB column. Columns use ``PydanticJSON(<model>)`` so a bad
shape is rejected on write and a stored value loads back as the model."""

from __future__ import annotations

from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.conditions import CampaignRule, ConditionSet

T = TypeVar("T")


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


YesNo = Literal["yes", "no", "not_stated"]
MoneyPeriod = Literal["year", "month", "week", "day", "hour"]
UnknownPolicy = Literal["review", "pass_with_penalty", "pass_blocks_auto", "fail"]
AutomationMode = Literal["save_only", "prepare", "ask_then_apply", "auto_apply"]
ChannelName = Literal["email", "browser", "manual"]
# Where a backup or exported file is stored (local disk, S3-compatible, Google Drive, OneDrive).
BackupTargetName = Literal["local", "s3", "gdrive", "onedrive"]
# Connections that sign in with OAuth (start/callback endpoints).
OAuthProviderName = Literal["gmail", "gdrive", "gcalendar", "msgraph", "onedrive"]
# Who created a record: the system, the owner, or an import.
RecordOrigin = Literal["system", "owner", "import"]
# Wave 4 followups: outbound messages about an existing application.
MessageKind = Literal["follow_up", "thank_you", "info_reply", "slot_accept", "slot_decline", "withdraw",
                      "offer_decline"]
MessageStatus = Literal["draft", "approved", "discarded", "budget_paused", "failed"]
MessageSendState = Literal["none", "queued", "sending", "sent", "uncertain", "failed", "cancelled"]
FollowupDueStatus = Literal["upcoming", "due", "snoozed", "not_needed", "drafted", "sent"]
WindDownChoice = Literal["keep", "pause", "withdraw"]
# Interview rounds and mock interviews (wave 4)
RoundKind = Literal["screen", "technical", "panel", "final", "other"]
MockMode = Literal["behavioural", "technical", "role", "mixed", "tough"]
MockStatus = Literal["active", "paused", "failed", "done"]


# ----- Job facets (6.1) ---------------------------------------------------------------------


class Evidenced(Shape, Generic[T]):
    """A facet value with the sentence from the posting that supports it."""

    value: T
    evidence: str | None = None


class WhereMustLive(Shape):
    kind: Literal["places", "anywhere", "not_stated"] = "not_stated"
    places: list[str] = Field(default_factory=list)


class TimezoneOverlap(Shape):
    hours: float | None = None
    zone: str | None = None


class Education(Shape):
    level: Literal["none_stated", "bachelors", "masters", "doctorate"] = "none_stated"
    required: bool = False


class JobFacets(Shape):
    relocation_required: Evidenced[YesNo] = Field(default_factory=lambda: Evidenced[YesNo](value="not_stated"))
    visa_sponsorship: Evidenced[YesNo] = Field(default_factory=lambda: Evidenced[YesNo](value="not_stated"))
    relocation_assistance: Evidenced[YesNo] = Field(default_factory=lambda: Evidenced[YesNo](value="not_stated"))
    needs_account: Evidenced[YesNo] = Field(default_factory=lambda: Evidenced[YesNo](value="not_stated"))
    work_model: Evidenced[Literal["on_site", "hybrid", "remote", "not_stated"]] | None = None
    remote_scope: Evidenced[Literal["worldwide", "regions", "country_only", "not_stated"]] | None = None
    remote_regions: list[str] = Field(default_factory=list)
    where_must_live: Evidenced[WhereMustLive] | None = None
    work_rights: Evidenced[Literal["existing_right_required", "sponsorship_possible", "not_stated"]] | None = None
    timezone_overlap: Evidenced[TimezoneOverlap] | None = None
    hiring_arrangement: Evidenced[Literal["employee", "contractor", "eor", "not_stated"]] | None = None
    employment_type: Evidenced[Literal["permanent", "fixed_term", "contract", "eor", "not_stated"]] | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_education: Evidenced[Education] | None = None
    required_qualifications: list[str] = Field(default_factory=list)
    years_experience: Evidenced[int | None] | None = None
    languages: list[str] = Field(default_factory=list)
    travel_percent: Evidenced[int | None] | None = None
    industry: str | None = None


class CustomFacetValue(Shape):
    value: YesNo
    evidence: str | None = None
    model: str | None = None


class StructuredLocation(Shape):
    country: str | None = None
    region: str | None = None
    city: str | None = None
    raw: str | None = None


class Requirement(Shape):
    text: str
    kind: Literal["required", "preferred"] = "required"
    skill: str | None = None


# ----- Campaign ---------------------------------------------------------------------------


class LocationRule(Shape):
    place: str
    kind: Literal["allow", "deny", "priority"]


class PayFloor(Shape):
    employment_type: Literal["permanent", "fixed_term", "contract", "eor"]
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period: MoneyPeriod = "year"


class CampaignCriteria(Shape):
    titles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    rules: list[CampaignRule] = Field(default_factory=list)
    locations: list[LocationRule] = Field(default_factory=list)
    work_models: list[Literal["on_site", "hybrid", "remote"]] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    pay_floors: list[PayFloor] = Field(default_factory=list)
    deprioritise_themes: list[str] = Field(default_factory=list)


class UnknownDataPolicy(Shape):
    """None means: use the global setting (scoring.unknown_*)."""

    pay: UnknownPolicy | None = None
    eligibility: UnknownPolicy | None = None
    deadline: UnknownPolicy | None = None


class AutomationPolicy(Shape):
    mode: AutomationMode = "prepare"
    per_channel: dict[ChannelName, AutomationMode] = Field(default_factory=dict)


class CampaignBudget(Shape):
    monthly_cap_minor: int | None = Field(default=None, ge=0)
    per_run_cap_minor: int | None = Field(default=None, ge=0)


# ----- Rubric -----------------------------------------------------------------------------


class RubricCriterion(Shape):
    name: str
    weight: int = Field(ge=0, le=100)
    anchors: dict[Literal["0", "1", "2", "3", "4", "5"], str] = Field(default_factory=dict)


class RubricPenalty(Shape):
    name: str
    points: int = Field(ge=1, le=100)
    conditions: ConditionSet


class RubricThresholds(Shape):
    shortlist: int | None = Field(default=None, ge=0, le=100)
    tailor: int | None = Field(default=None, ge=0, le=100)
    auto_apply: int | None = Field(default=None, ge=0, le=100)


class RubricBody(Shape):
    criteria: list[RubricCriterion]
    penalties: list[RubricPenalty] = Field(default_factory=list)
    thresholds: RubricThresholds = Field(default_factory=RubricThresholds)

    @model_validator(mode="after")
    def _weights(self) -> RubricBody:
        if sum(c.weight for c in self.criteria) != 100:
            raise ValueError("rubric weights must sum to 100")
        return self


# ----- Sources ----------------------------------------------------------------------------


class RateLimit(Shape):
    requests_per_minute: int = Field(default=30, ge=1)
    burst: int = Field(default=5, ge=1)


class SourceHealth(Shape):
    status: Literal["ok", "degraded", "failing", "unknown"] = "unknown"
    consecutive_failures: int = 0
    last_error: str | None = None


# ----- Assessment -------------------------------------------------------------------------


class FilterResult(Shape):
    name: str
    result: Literal["pass", "fail", "unknown"]
    reason: str
    mandatory: bool = True


class CriterionRating(Shape):
    criterion: str
    rating: int = Field(ge=0, le=5)
    evidence_fact_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class Override(Shape):
    by: str
    reason: str
    at: str
    score: int | None = None


# ----- Run --------------------------------------------------------------------------------


class SourceRunResult(Shape):
    source_id: str
    status: Literal["ok", "failed", "skipped"]
    found: int = 0
    new: int = 0
    error: str | None = None


# ----- Applications -----------------------------------------------------------------------


class SpecItem(Shape):
    text: str
    fact_ids: list[str] = Field(default_factory=list)


class SpecExperience(Shape):
    experience_id: str
    title: str | None = None
    bullets: list[SpecItem] = Field(default_factory=list)


class RequirementMatch(Shape):
    requirement: str
    strength: Literal["strong", "partial", "gap"]
    evidence_fact_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class ApplicationSpec(Shape):
    headline: SpecItem | None = None
    summary: SpecItem | None = None
    competencies: list[SpecItem] = Field(default_factory=list)
    experience: list[SpecExperience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    letter: list[SpecItem] = Field(default_factory=list)
    requirement_match: list[RequirementMatch] = Field(default_factory=list)


class DraftAnswer(Shape):
    """A screening question and what the answer bank says about it (5.4). Only ``outcome == "value"``
    carries an answer; ``ask_owner`` raised a pending action, ``do_not_answer`` is a ``never`` answer."""

    question: str
    outcome: Literal["value", "ask_owner", "do_not_answer"]
    value: str | None = None
    select: str | None = None
    answer_id: str | None = None
    material: bool = False
    reason: str = ""
    pending_action_id: str | None = None


class CheckResult(Shape):
    check: str
    status: Literal["pass", "warn", "block"]
    detail: str | None = None
    guardrail_id: str | None = None
    waived: bool = False


class GateResult(Shape):
    """One gate's result. ``outcome`` is the three-state answer (unknown is never a pass); ``passed`` is
    kept for compatibility and is true only when ``outcome`` is ``pass``."""

    gate: str
    passed: bool
    detail: str | None = None
    outcome: Literal["pass", "fail", "unknown"] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> GateResult:
        if self.outcome is None:
            self.outcome = "pass" if self.passed else "fail"
        elif self.passed != (self.outcome == "pass"):
            raise ValueError("passed must be true exactly when outcome is pass")
        return self


class PacketDestination(Shape):
    url: str
    domain: str
    verified: bool = False
    trusted: bool = False


class PacketAnswer(Shape):
    question: str
    value: str
    answer_id: str | None = None
    material: bool = False


def _optional_in_output(*names: str) -> Any:
    """``json_schema_extra`` for fields left out of the JSON when null (``exclude_if``): never required."""

    def fix(schema: dict[str, Any]) -> None:
        for name in names:  # the frontend generator keeps these optional in response-only schemas
            schema.get("properties", {}).get(name, {})["x-omitted-when-null"] = True
        req = [r for r in schema.get("required", []) if r not in names]
        if req:
            schema["required"] = req
        else:
            schema.pop("required", None)

    return fix


class PacketEmail(Shape):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_optional_in_output("thread_ref"))

    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    # Wave 4 followups: left out of the canonical JSON when null, so packets built before it hash the same.
    thread_ref: str | None = Field(default=None, exclude_if=lambda v: v is None,
                                   description="The mail thread a message replies in (provider thread id)")


class PacketFile(Shape):
    name: str
    kind: Literal["cv", "letter", "vault", "other"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str | None = None
    share_link: str | None = None


class PacketContents(Shape):
    """Everything an approval or permit binds to (18.2). Hashed canonically."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=_optional_in_output("message_kind"))

    requisition: str | None = None
    destination: PacketDestination
    sending_identity: str
    answers: list[PacketAnswer] = Field(default_factory=list)
    email: PacketEmail | None = None
    files: list[PacketFile] = Field(default_factory=list)
    link_permissions: list[str] = Field(default_factory=list)
    channel: ChannelName | None = Field(default=None, description="The channel this packet is sent through")
    job_version: str | None = Field(default=None, description="Content hash of the job as it was packed")
    # Wave 4 followups: set only on a message packet (never on the application's own packet); left out of the
    # canonical JSON when null, so application packets hash exactly as before.
    message_kind: MessageKind | None = Field(default=None, exclude_if=lambda v: v is None,
                                             description="Set when the packet is a message about the application")


class SubmittedSnapshot(Shape):
    packet_hash: str
    files: list[PacketFile]
    answers: list[PacketAnswer]
    submitted_at: str


class Evidence(Shape):
    kind: Literal["confirmation_page", "reference", "sent_mail_id", "confirmation_email", "owner_marked"]
    value: str
    screenshot_ref: str | None = None
    at: str | None = None


# ----- Kit --------------------------------------------------------------------------------

FieldVisibility = Literal["show_on_cv", "forms_only", "hidden"]


class PersonField(Shape):
    value: str
    visibility: FieldVisibility = "show_on_cv"


class TitleSpan(Shape):
    title: str
    start: str | None = None  # ISO date or YYYY-MM
    end: str | None = None


class AnswerPatterns(Shape):
    canonical: str
    variants: list[str] = Field(default_factory=list)


class TemplateLimits(Shape):
    pages: int | None = Field(default=None, ge=1)
    paragraphs: int | None = Field(default=None, ge=1)
    bullets_per_role: int | None = Field(default=None, ge=1)


# Guardrail parameters, one shape per type (5.3).
class NeverMention(Shape):
    type: Literal["never_mention"] = "never_mention"
    terms: list[str] = Field(default_factory=list)
    regex: list[str] = Field(default_factory=list)


class NeverTogether(Shape):
    type: Literal["never_together"] = "never_together"
    group_a: list[str]
    group_b: list[str]


class RequireWording(Shape):
    type: Literal["require_wording"] = "require_wording"
    use: str
    instead_of: list[str]


class Reframe(Shape):
    type: Literal["reframe"] = "reframe"
    prefer: str
    over: str


class OmitField(Shape):
    type: Literal["omit_field"] = "omit_field"
    fields: list[str]


class FormatRule(Shape):
    type: Literal["format"] = "format"
    rule: str
    params: dict[str, str | int | float] = Field(default_factory=dict)


class Positioning(Shape):
    type: Literal["positioning"] = "positioning"
    instruction: str


class LimitRule(Shape):
    type: Literal["limit"] = "limit"
    document: Literal["cv", "letter", "email"]
    pages: int | None = None
    paragraphs: int | None = None


class AttachPolicy(Shape):
    type: Literal["attach_policy"] = "attach_policy"
    document_type: str
    when: Literal["never", "when_asked", "after_offer"]


GuardrailParams = Annotated[
    NeverMention | NeverTogether | RequireWording | Reframe | OmitField | FormatRule | Positioning
    | LimitRule | AttachPolicy,
    Field(discriminator="type"),
]


# ----- Views, rules, platform -------------------------------------------------------------


class SortSpec(Shape):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class SavedViewBody(Shape):
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    group_by: str | None = None
    sort: list[SortSpec] = Field(default_factory=list)
    scope: Literal["matches", "applications"] = "matches"


class ThemeFonts(Shape):
    display: str
    body: str
    mono: str
    data: str | None = None
    label: str | None = None


class ScoreRamp(Shape):
    low: str
    mid: str
    high: str


ThemeModeName = Literal["light", "dark"]


class ContrastWaiverPair(Shape):
    mode: ThemeModeName
    fg: str
    bg: str
    ratio: float


class ContrastWaiver(Shape):
    """The owner accepted body text below WCAG AA on a personal theme (recorded, also in the audit)."""

    pairs: list[ContrastWaiverPair]
    accepted_at: str
    accepted_by: str


class AgentTaskState(Shape):
    """Checkpoint saved by a runner. Free-form fields go in ``data``."""

    step: str | None = None
    fields_filled: list[str] = Field(default_factory=list)
    screenshot_ref: str | None = None
    url: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# One definition, one order: equal Literals in different orders share a typing cache entry, so a second
# spelling would make the generated OpenAPI depend on import order.
AgentTaskTypeName = Literal["apply", "sweep_site", "check_posting"]

JsonDict = dict[str, Any]


# ----- Preference feedback and suggestions (wave 4 feedback stream) ------------------------

FeedbackVerdict = Literal["up", "down"]
FeedbackReason = Literal["too_junior", "too_senior", "wrong_stack", "pay", "location", "employer_type",
                         "commute_remote", "more_like_this"]
SuggestionKind = Literal["reweight_criterion", "add_penalty", "add_bonus", "add_tag_rule", "add_saved_view",
                         "tighten_filter"]
SuggestionStatus = Literal["open", "accepted", "dismissed", "superseded"]


class ReweightChange(Shape):
    """New weights for the rubric's criteria (same names, summing to 100): a new rubric version."""

    kind: Literal["reweight_criterion"] = "reweight_criterion"
    weights: dict[str, int]


class PenaltyChange(Shape):
    """A rubric penalty (a new rubric version)."""

    kind: Literal["add_penalty"] = "add_penalty"
    name: str = Field(min_length=1, max_length=120)
    points: int = Field(ge=1, le=100)
    conditions: ConditionSet


class BonusChange(Shape):
    """A campaign bonus rule (raises the effective score of matching roles)."""

    kind: Literal["add_bonus"] = "add_bonus"
    reason: str = Field(min_length=1, max_length=200)
    points: int = Field(ge=1, le=100)
    conditions: ConditionSet


class TagRuleChange(Shape):
    kind: Literal["add_tag_rule"] = "add_tag_rule"
    tag: str = Field(min_length=1, max_length=60)
    conditions: ConditionSet


class SavedViewChange(Shape):
    kind: Literal["add_saved_view"] = "add_saved_view"
    name: str = Field(min_length=1, max_length=120)
    conditions: ConditionSet


class TightenChange(Shape):
    """A campaign exclusion rule: only ever narrows what the campaign matches."""

    kind: Literal["tighten_filter"] = "tighten_filter"
    reason: str = Field(min_length=1, max_length=200)
    conditions: ConditionSet


SuggestionChange = Annotated[ReweightChange | PenaltyChange | BonusChange | TagRuleChange | SavedViewChange
                             | TightenChange, Field(discriminator="kind")]


class SuggestionEvidence(Shape):
    """What a suggestion rests on: owner feedback and real outcomes, counted and listed."""

    up: int = 0
    down: int = 0
    feedback_ids: list[str] = Field(default_factory=list)
    application_ids: list[str] = Field(default_factory=list)
    reasons: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    summary: str = ""


class BacktestChangeRow(Shape):
    job_id: str
    title: str
    employer: str
    old_score: int | None = None
    new_score: int | None = None
    old_verdict: str
    new_verdict: str


class SuggestionBacktest(Shape):
    """The change replayed over recent roles with the decision table (no model calls)."""

    window_days: int
    jobs: int
    matched: int = Field(default=0, description="Recent roles the change's conditions match")
    newly_pass: list[BacktestChangeRow] = Field(default_factory=list)
    newly_drop: list[BacktestChangeRow] = Field(default_factory=list)
    excluded_past_applications: list[BacktestChangeRow] = Field(default_factory=list)
    score_changed: int = 0


# ----- wave 4 bulk: one spelling each (equal Literals share a typing cache entry) ------------------------
BulkSubject = Literal["jobs", "applications"]
BulkActionName = Literal["tag", "untag", "skip", "snooze", "move_stage", "assign_campaign", "queue_tailoring",
                         "send_for_approval", "approve_reviewed", "archive", "recheck", "export_csv"]
BulkStatus = Literal["previewed", "queued", "running", "done", "partial", "failed", "undone"]
BulkItemOutcome = Literal["pending", "changed", "unchanged", "refused", "failed", "undone", "undo_skipped"]
BulkVerdict = Literal["change", "unchanged", "refused"]
EmployerStateName = Literal["free", "role_in_progress", "cooling_down", "always_ask_first", "blocked"]
CooldownKind = Literal["end_state", "applied_date"]
