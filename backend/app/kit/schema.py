"""The Kit file: ``kit.json`` inside ``<name>.kit.zip`` (DESIGN.md 5.5, 18.5).

Two export kinds:

- ``share_setup``: rubrics, templates, themes, guardrail *types* without personal terms,
  sources, tag rules, custom facets, saved views, aliases, prompts. Scanned for personal
  details and previewed before download. ``person``, ``experiences``, ``facts``, ``skills``,
  ``references``, ``answers``, ``vault`` and ``history`` MUST be empty.
- ``personal_backup``: everything, including vault files and application history.

Cross references inside the file use stable keys (fact ``code``, track ``key``, template
``key``, ``ref`` strings for experiences), never database ids. Import validates against this
schema, shows a diff, and lands every item as ``needs_review``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.conditions import ConditionSet
from app.schemas.json_types import (
    AnswerPatterns,
    AutomationPolicy,
    CampaignCriteria,
    GuardrailParams,
    PersonField,
    RateLimit,
    RubricBody,
    SavedViewBody,
    TemplateLimits,
    TitleSpan,
    UnknownDataPolicy,
)
from app.themes.schema import ThemeBody

KIT_SCHEMA_VERSION = 1


class _K(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KitPerson(_K):
    full_name: PersonField
    preferred_name: PersonField | None = None
    email: PersonField | None = None
    phone: PersonField | None = None
    location: PersonField | None = None
    home_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    timezone: str | None = None
    links: dict[str, PersonField] = Field(default_factory=dict)
    extra_fields: dict[str, PersonField] = Field(default_factory=dict)


class KitExperience(_K):
    ref: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    org: str
    titles: list[TitleSpan]
    location: str | None = None
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    title_variants: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_titles: list[str] = Field(default_factory=list)


class KitFact(_K):
    code: str = Field(pattern=r"^F-\d{1,6}$")
    kind: Literal["bullet", "achievement", "metric", "summary", "education", "cert", "project", "speaking"]
    text: str
    canonical_wording: bool = False
    experience_ref: str | None = None
    tags: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    status: Literal["draft", "approved", "retired"] = "draft"
    keep_out_of_prompts: bool = False
    confidence_note: str | None = None


class KitSkill(_K):
    name: str
    group: str | None = None
    level: str | None = None
    claim: Literal["yes", "no", "never"] = "yes"
    note: str | None = None


class KitReference(_K):
    name: str
    role: str | None = None
    organisation: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    consent: bool = False
    share_policy: Literal["on_cv", "on_request", "forms_only"] = "on_request"


class KitTrack(_K):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    name: str
    priority: int = 0
    example_titles: list[str] = Field(default_factory=list)
    lead_fact_codes: list[str] = Field(default_factory=list)
    summary_fact_code: str | None = None
    tone_notes: str | None = None
    cv_template: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$",
                                    description="CV template key for this track; null uses the documents setting")
    letter_template: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$",
                                        description="Letter template key; null uses the documents setting")


class KitGuardrail(_K):
    name: str
    scope: list[Literal["cv", "letter", "email", "form_answers", "everywhere"]]
    severity: Literal["block", "warn"] = "block"
    strictness: Literal["always_block", "block_waivable_once", "advise"] = "always_block"
    params: GuardrailParams
    reason: str | None = None


class KitAnswer(_K):
    patterns: AnswerPatterns
    value: str | None = None
    value_type: Literal["text", "number", "boolean", "choice", "date", "money"] = "text"
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    answer_class: Literal["auto", "ask_first", "never", "owner_only"]
    material: bool = False
    scope: Literal["this_application", "this_employer", "this_country", "all_matching"] = "all_matching"
    scope_ref: str | None = None
    forced_choice: str | None = None
    review_after: date | None = None


class KitVaultDocument(_K):
    path: str = Field(description="Path inside the zip, under vault/")
    title: str
    doc_type: Literal["cv", "degree", "transcript", "id", "photo", "cert", "other"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sensitivity: Literal["normal", "on_request", "after_offer_only"] = "normal"


class KitTemplate(_K):
    key: str
    kind: Literal["cv", "letter", "email"]
    name: str
    html: str
    css: str = ""
    section_order: list[str] = Field(default_factory=list)
    limits: TemplateLimits = Field(default_factory=TemplateLimits)
    accent: str | None = None


class KitPrompt(_K):
    stage: str
    text: str
    version: int = 1


class KitRubric(_K):
    name: str
    body: RubricBody


class KitCampaign(_K):
    name: str
    track_key: str | None = None
    priority: int = 0
    criteria: CampaignCriteria
    unknown_data_policy: UnknownDataPolicy = Field(default_factory=UnknownDataPolicy)
    rubric_name: str | None = None
    automation: AutomationPolicy = Field(default_factory=AutomationPolicy)
    source_names: list[str] = Field(default_factory=list)


class KitSource(_K):
    connector: str
    name: str
    access: Literal["api", "feed", "html", "agent", "email"]
    config: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    access_notes: str | None = None
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    permitted_actions: list[str] = Field(default_factory=list)


class KitWatchedEmployer(_K):
    name: str
    board_type: str
    board_slug: str
    priority: int = 0
    cooldown_days: int | None = None
    always_ask_first: bool = False


class KitAlias(_K):
    alias: str
    canonical: str


class KitTagRule(_K):
    tag: str
    conditions: ConditionSet


class KitCustomFacet(_K):
    key: str
    question: str


class KitSavedView(_K):
    name: str
    body: SavedViewBody
    pinned: bool = False


class KitTheme(ThemeBody):
    pass


class KitHistoryItem(_K):
    """Application history (personal backup only): blocks duplicates from day one."""

    employer: str
    title: str
    applied_on: date
    url: str | None = None
    requisition_id: str | None = None
    stage: str = "submitted"
    channel: Literal["email", "browser", "manual"] = "manual"


class KitFile(_K):
    schema_version: Literal[1] = KIT_SCHEMA_VERSION
    kind: Literal["share_setup", "personal_backup"]
    exported_at: datetime
    app_version: str
    person: KitPerson | None = None
    experiences: list[KitExperience] = Field(default_factory=list)
    facts: list[KitFact] = Field(default_factory=list)
    skills: list[KitSkill] = Field(default_factory=list)
    references: list[KitReference] = Field(default_factory=list)
    tracks: list[KitTrack] = Field(default_factory=list)
    guardrails: list[KitGuardrail] = Field(default_factory=list)
    answers: list[KitAnswer] = Field(default_factory=list)
    vault: list[KitVaultDocument] = Field(default_factory=list)
    templates: list[KitTemplate] = Field(default_factory=list)
    prompts: list[KitPrompt] = Field(default_factory=list)
    rubrics: list[KitRubric] = Field(default_factory=list)
    campaigns: list[KitCampaign] = Field(default_factory=list)
    sources: list[KitSource] = Field(default_factory=list)
    watched_employers: list[KitWatchedEmployer] = Field(default_factory=list)
    employer_aliases: list[KitAlias] = Field(default_factory=list)
    skill_aliases: list[KitAlias] = Field(default_factory=list)
    tag_rules: list[KitTagRule] = Field(default_factory=list)
    custom_facets: list[KitCustomFacet] = Field(default_factory=list)
    saved_views: list[KitSavedView] = Field(default_factory=list)
    themes: list[KitTheme] = Field(default_factory=list)
    history: list[KitHistoryItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> KitFile:
        if self.kind == "share_setup":
            personal = {"person": self.person, "experiences": self.experiences, "facts": self.facts,
                        "skills": self.skills, "references": self.references, "answers": self.answers,
                        "vault": self.vault, "history": self.history}
            present = [k for k, v in personal.items() if v]
            if present:
                raise ValueError(f"a share_setup kit must not contain personal sections: {present}")
        codes = [f.code for f in self.facts]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate fact codes")
        code_set = set(codes)
        refs = {e.ref for e in self.experiences}
        for fact in self.facts:
            if fact.experience_ref and fact.experience_ref not in refs:
                raise ValueError(f"{fact.code}: unknown experience_ref {fact.experience_ref!r}")
        track_keys = {t.key for t in self.tracks}
        for track in self.tracks:
            for code in [*track.lead_fact_codes, *([track.summary_fact_code] if track.summary_fact_code else [])]:
                if code not in code_set and self.kind == "personal_backup":
                    raise ValueError(f"track {track.key}: unknown fact {code}")
        for fact in self.facts:
            unknown = set(fact.tracks) - track_keys
            if unknown:
                raise ValueError(f"{fact.code}: unknown tracks {sorted(unknown)}")
        rubric_names = {r.name for r in self.rubrics}
        source_names = {s.name for s in self.sources}
        for campaign in self.campaigns:
            if campaign.track_key and campaign.track_key not in track_keys:
                raise ValueError(f"campaign {campaign.name}: unknown track {campaign.track_key}")
            if campaign.rubric_name and campaign.rubric_name not in rubric_names:
                raise ValueError(f"campaign {campaign.name}: unknown rubric {campaign.rubric_name}")
            missing = set(campaign.source_names) - source_names
            if missing:
                raise ValueError(f"campaign {campaign.name}: unknown sources {sorted(missing)}")
        return self
