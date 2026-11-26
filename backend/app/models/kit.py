"""Kit aggregate: who the person is (DESIGN.md 4 and 5).

Every Kit row carries ``review_state``: imported rows land as ``needs_review`` and cannot
drive automation until confirmed (principle 2).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.conditions import ConditionSet
from app.models.base import Base, Entity, Origin, PydanticJSON, ReviewState, str_enum
from app.schemas.json_types import (
    AnswerPatterns,
    GuardrailParams,
    PersonField,
    TemplateLimits,
    TitleSpan,
)


class KitMixin:
    review_state: Mapped[ReviewState] = mapped_column(
        str_enum(ReviewState), nullable=False, default=ReviewState.needs_review
    )
    origin: Mapped[Origin] = mapped_column(str_enum(Origin), nullable=False, default=Origin.owner)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Person(Base, Entity, KitMixin):
    __tablename__ = "person"

    full_name: Mapped[PersonField] = mapped_column(PydanticJSON(PersonField), nullable=False)
    preferred_name: Mapped[PersonField | None] = mapped_column(PydanticJSON(PersonField))
    email: Mapped[PersonField | None] = mapped_column(PydanticJSON(PersonField))
    phone: Mapped[PersonField | None] = mapped_column(PydanticJSON(PersonField))
    location: Mapped[PersonField | None] = mapped_column(PydanticJSON(PersonField))
    home_country: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[str | None] = mapped_column(String(64))
    links: Mapped[dict[str, PersonField]] = mapped_column(PydanticJSON(dict[str, PersonField]), default=dict)
    extra_fields: Mapped[dict[str, PersonField]] = mapped_column(
        PydanticJSON(dict[str, PersonField]), default=dict, doc="Date of birth, ID numbers, ...: usually forms_only"
    )


class Experience(Base, Entity, KitMixin):
    __tablename__ = "experience"

    org: Mapped[str] = mapped_column(String(200), nullable=False)
    titles: Mapped[list[TitleSpan]] = mapped_column(PydanticJSON(list[TitleSpan]), nullable=False, default=list)
    location: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[str | None] = mapped_column(String(10), doc="YYYY-MM or YYYY-MM-DD")
    end_date: Mapped[str | None] = mapped_column(String(10))
    title_variants: Mapped[dict[str, list[str]]] = mapped_column(
        PydanticJSON(dict[str, list[str]]), default=dict, doc="track key -> allowed alternate titles"
    )
    forbidden_titles: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class FactKind(enum.StrEnum):
    bullet = "bullet"
    achievement = "achievement"
    metric = "metric"
    summary = "summary"
    education = "education"
    cert = "cert"
    project = "project"
    speaking = "speaking"


class FactStatus(enum.StrEnum):
    draft = "draft"
    approved = "approved"
    retired = "retired"


class Fact(Base, Entity, KitMixin):
    __tablename__ = "fact"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, doc="e.g. F-112")
    kind: Mapped[FactKind] = mapped_column(str_enum(FactKind), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_wording: Mapped[bool] = mapped_column(Boolean, default=False)
    experience_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experience.id", ondelete="SET NULL"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    tracks: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    status: Mapped[FactStatus] = mapped_column(str_enum(FactStatus), nullable=False, default=FactStatus.draft)
    keep_out_of_prompts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence_note: Mapped[str | None] = mapped_column(Text)


class SkillClaim(enum.StrEnum):
    yes = "yes"
    no = "no"
    never = "never"


class Skill(Base, Entity, KitMixin):
    __tablename__ = "skill"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    group: Mapped[str | None] = mapped_column(String(60))
    level: Mapped[str | None] = mapped_column(String(30))
    claim: Mapped[SkillClaim] = mapped_column(str_enum(SkillClaim), nullable=False, default=SkillClaim.yes)
    note: Mapped[str | None] = mapped_column(Text)


class SharePolicy(enum.StrEnum):
    on_cv = "on_cv"
    on_request = "on_request"
    forms_only = "forms_only"


class Reference(Base, Entity, KitMixin):
    __tablename__ = "reference"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    organisation: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    share_policy: Mapped[SharePolicy] = mapped_column(str_enum(SharePolicy), default=SharePolicy.on_request)


class Track(Base, Entity, KitMixin):
    __tablename__ = "track"

    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    example_titles: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    lead_fact_codes: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    summary_fact_code: Mapped[str | None] = mapped_column(String(20))
    tone_notes: Mapped[str | None] = mapped_column(Text)
    # Template keys for this track's documents; null falls back to documents.cv_template / letter_template.
    cv_template: Mapped[str | None] = mapped_column(String(60))
    letter_template: Mapped[str | None] = mapped_column(String(60))


class GuardrailType(enum.StrEnum):
    never_mention = "never_mention"
    never_together = "never_together"
    require_wording = "require_wording"
    reframe = "reframe"
    omit_field = "omit_field"
    format = "format"
    positioning = "positioning"
    limit = "limit"
    attach_policy = "attach_policy"


class Severity(enum.StrEnum):
    block = "block"
    warn = "warn"


class Strictness(enum.StrEnum):
    always_block = "always_block"
    block_waivable_once = "block_waivable_once"
    advise = "advise"


class Guardrail(Base, Entity, KitMixin):
    __tablename__ = "guardrail"

    type: Mapped[GuardrailType] = mapped_column(str_enum(GuardrailType), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), nullable=False, default=list, doc="cv, letter, email, form_answers, everywhere"
    )
    severity: Mapped[Severity] = mapped_column(str_enum(Severity), nullable=False, default=Severity.block)
    strictness: Mapped[Strictness] = mapped_column(
        str_enum(Strictness), nullable=False, default=Strictness.always_block
    )
    params: Mapped[GuardrailParams] = mapped_column(PydanticJSON(GuardrailParams), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class GuardrailWaiver(Base, Entity):
    """A one-application waiver of a ``block_waivable_once`` guardrail, with a reason."""

    __tablename__ = "guardrail_waiver"

    guardrail_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guardrail.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    waived_by: Mapped[str] = mapped_column(String(120), nullable=False)


class AnswerClass(enum.StrEnum):
    auto = "auto"
    ask_first = "ask_first"
    never = "never"
    owner_only = "owner_only"


class AnswerScope(enum.StrEnum):
    this_application = "this_application"
    this_employer = "this_employer"
    this_country = "this_country"
    all_matching = "all_matching"


class Answer(Base, Entity, KitMixin):
    __tablename__ = "answer"
    __table_args__ = (Index("ix_answer_scope", "scope", "scope_ref"),)

    patterns: Mapped[AnswerPatterns] = mapped_column(PydanticJSON(AnswerPatterns), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text")
    conditions: Mapped[ConditionSet] = mapped_column(PydanticJSON(ConditionSet), nullable=False,
                                                     default=ConditionSet)
    answer_class: Mapped[AnswerClass] = mapped_column(str_enum(AnswerClass), nullable=False,
                                                      default=AnswerClass.ask_first)
    material: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    settled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                          doc="ask_first answers stop asking once settled")
    scope: Mapped[AnswerScope] = mapped_column(str_enum(AnswerScope), nullable=False,
                                               default=AnswerScope.all_matching)
    scope_ref: Mapped[str | None] = mapped_column(String(200), doc="application id, employer or country code")
    forced_choice: Mapped[str | None] = mapped_column(String(200), doc="What to select for 'never' answers")
    review_after: Mapped[date | None] = mapped_column(Date)


class Sensitivity(enum.StrEnum):
    normal = "normal"
    on_request = "on_request"
    after_offer_only = "after_offer_only"


class VaultDocument(Base, Entity, KitMixin):
    __tablename__ = "vault_document"

    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, doc="cv, degree, transcript, id, photo, cert")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, doc="Relative to FILES_DIR")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sensitivity: Mapped[Sensitivity] = mapped_column(str_enum(Sensitivity), nullable=False,
                                                     default=Sensitivity.normal)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, default=False)


class TemplateKind(enum.StrEnum):
    cv = "cv"
    letter = "letter"
    email = "email"


class Template(Base, Entity, KitMixin):
    __tablename__ = "template"

    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    kind: Mapped[TemplateKind] = mapped_column(str_enum(TemplateKind), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    css: Mapped[str] = mapped_column(Text, nullable=False, default="")
    section_order: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    limits: Mapped[TemplateLimits] = mapped_column(PydanticJSON(TemplateLimits), nullable=False,
                                                   default=TemplateLimits)
    accent: Mapped[str | None] = mapped_column(String(7))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class Prompt(Base, Entity):
    __tablename__ = "prompt"
    __table_args__ = (Index("ix_prompt_stage_version", "stage", "version", unique=True),)

    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
