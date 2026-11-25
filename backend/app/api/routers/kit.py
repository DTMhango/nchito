"""Kit: person, library (experience, facts, skills, references), tracks, guardrails, answer
bank, vault, templates, prompts, and the needs-review queue. Wave 1 (Kit stream)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Ok, Page, Timestamps, not_implemented
from app.api.crud import add_crud
from app.api.deps import RequireOwner
from app.core.conditions import ConditionSet
from app.schemas.json_types import (
    AnswerPatterns,
    CheckResult,
    GuardrailParams,
    PersonField,
    TemplateLimits,
    TitleSpan,
)

router = APIRouter(prefix="/api/kit", tags=["kit"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)
WAVE, AREA = 1, "kit"

ReviewStateT = Literal["needs_review", "confirmed"]
OriginT = Literal["import", "owner", "system"]


class KitMeta(Timestamps):
    review_state: ReviewStateT
    origin: OriginT
    confirmed_at: datetime | None = None


class PersonIn(ApiModel):
    full_name: PersonField
    preferred_name: PersonField | None = None
    email: PersonField | None = None
    phone: PersonField | None = None
    location: PersonField | None = None
    home_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    timezone: str | None = None
    links: dict[str, PersonField] = Field(default_factory=dict)
    extra_fields: dict[str, PersonField] = Field(default_factory=dict)


class PersonOut(PersonIn, KitMeta):
    pass


class ExperienceIn(ApiModel):
    org: str
    titles: list[TitleSpan] = Field(default_factory=list)
    location: str | None = None
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$")
    title_variants: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_titles: list[str] = Field(default_factory=list)
    sort_order: int = 0


class ExperienceOut(ExperienceIn, KitMeta):
    pass


FactKindT = Literal["bullet", "achievement", "metric", "summary", "education", "cert", "project", "speaking"]


class FactIn(ApiModel):
    code: str | None = Field(default=None, pattern=r"^F-\d{1,6}$", description="Assigned when omitted")
    kind: FactKindT
    text: str = Field(min_length=1)
    canonical_wording: bool = False
    experience_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    keep_out_of_prompts: bool = False
    confidence_note: str | None = None


class FactOut(FactIn, KitMeta):
    code: str  # type: ignore[assignment]
    status: Literal["draft", "approved", "retired"]


class FactListParams(BaseModel):
    status: Literal["draft", "approved", "retired"] | None = None
    review_state: ReviewStateT | None = None
    kind: FactKindT | None = None
    tag: str | None = None
    track: str | None = None
    q: str | None = None
    cursor: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class SkillIn(ApiModel):
    name: str
    group: str | None = None
    level: str | None = None
    claim: Literal["yes", "no", "never"] = "yes"
    note: str | None = None


class SkillOut(SkillIn, KitMeta):
    pass


class ReferenceIn(ApiModel):
    name: str
    role: str | None = None
    organisation: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    consent: bool = False
    share_policy: Literal["on_cv", "on_request", "forms_only"] = "on_request"


class ReferenceOut(ReferenceIn, KitMeta):
    pass


class TrackIn(ApiModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    name: str
    priority: int = 0
    example_titles: list[str] = Field(default_factory=list)
    lead_fact_codes: list[str] = Field(default_factory=list)
    summary_fact_code: str | None = None
    tone_notes: str | None = None


class TrackOut(TrackIn, KitMeta):
    pass


GuardrailScope = Literal["cv", "letter", "email", "form_answers", "everywhere"]


class GuardrailIn(ApiModel):
    name: str
    scope: list[GuardrailScope] = Field(default_factory=lambda: ["everywhere"])
    severity: Literal["block", "warn"] = "block"
    strictness: Literal["always_block", "block_waivable_once", "advise"] = "always_block"
    params: GuardrailParams
    reason: str | None = None
    enabled: bool = True


class GuardrailOut(GuardrailIn, KitMeta):
    type: str


class GuardrailCheckIn(BaseModel):
    """Run the code checker over ad-hoc text (Studio preview, tests in the UI)."""

    texts: dict[GuardrailScope, str]
    file_names: list[str] = Field(default_factory=list)


class GuardrailCheckOut(BaseModel):
    results: list[CheckResult]
    blocked: bool


class AnswerIn(ApiModel):
    patterns: AnswerPatterns
    value: str | None = None
    value_type: Literal["text", "number", "boolean", "choice", "date", "money"] = "text"
    conditions: ConditionSet = Field(default_factory=ConditionSet)
    answer_class: Literal["auto", "ask_first", "never", "owner_only"] = "ask_first"
    material: bool = False
    settled: bool = False
    scope: Literal["this_application", "this_employer", "this_country", "all_matching"] = "all_matching"
    scope_ref: str | None = None
    forced_choice: str | None = None
    review_after: date | None = None


class AnswerOut(AnswerIn, KitMeta):
    pending_applications_using: int = Field(default=0, description="Pending applications using this value")


class AnswerMatchIn(BaseModel):
    question: str
    options: list[str] | None = None
    context: dict[str, str] = Field(default_factory=dict, description="country, employer, employment_type, ...")


class AnswerMatchOut(BaseModel):
    outcome: Literal["value", "ask_owner", "do_not_answer"]
    answer_id: uuid.UUID | None = None
    value: str | None = None
    select: str | None = Field(default=None, description="For do_not_answer: the option to pick")
    similarity: float | None = None


class VaultDocumentOut(KitMeta):
    doc_type: str
    title: str
    sha256: str
    mime_type: str
    size_bytes: int
    sensitivity: Literal["normal", "on_request", "after_offer_only"]
    has_text_layer: bool


class VaultDocumentUpdate(ApiModel):
    title: str
    doc_type: Literal["cv", "degree", "transcript", "id", "photo", "cert", "other"]
    sensitivity: Literal["normal", "on_request", "after_offer_only"]


class TemplateIn(ApiModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    kind: Literal["cv", "letter", "email"]
    name: str
    html: str
    css: str = ""
    section_order: list[str] = Field(default_factory=list)
    limits: TemplateLimits = Field(default_factory=TemplateLimits)
    accent: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TemplateOut(TemplateIn, KitMeta):
    builtin: bool


class PromptIn(ApiModel):
    stage: str
    text: str
    note: str | None = None


class PromptOut(PromptIn, Timestamps):
    version: int
    active: bool


ReviewEntity = Literal["person", "experience", "fact", "skill", "reference", "track", "guardrail", "answer",
                       "vault_document", "template", "campaign"]


class ReviewItem(BaseModel):
    entity: ReviewEntity
    id: uuid.UUID
    title: str
    group: str = Field(description="pay_floors, countries, seniority, visa, relocation, salary, notice, ...")
    stale_first_rank: int
    conflicts_with: list[uuid.UUID] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    decision: Literal["confirm", "drop"]
    note: str | None = None


# ----- person ----------------------------------------------------------------------------


@router.get("/person", response_model=PersonOut, name="kit_person_get")
async def get_person() -> PersonOut:
    not_implemented(WAVE, AREA)


@router.put("/person", response_model=PersonOut, name="kit_person_put")
async def put_person(body: PersonIn) -> PersonOut:
    not_implemented(WAVE, AREA)


# ----- library and the rest (CRUD) -------------------------------------------------------

add_crud(router, "/experiences", "kit_experiences", ExperienceIn, ExperienceOut, wave=WAVE, area=AREA)
add_crud(router, "/facts", "kit_facts", FactIn, FactOut, wave=WAVE, area=AREA, list_params=FactListParams)
add_crud(router, "/skills", "kit_skills", SkillIn, SkillOut, wave=WAVE, area=AREA)
add_crud(router, "/references", "kit_references", ReferenceIn, ReferenceOut, wave=WAVE, area=AREA)
add_crud(router, "/tracks", "kit_tracks", TrackIn, TrackOut, wave=WAVE, area=AREA)
add_crud(router, "/guardrails", "kit_guardrails", GuardrailIn, GuardrailOut, wave=WAVE, area=AREA)
add_crud(router, "/answers", "kit_answers", AnswerIn, AnswerOut, wave=WAVE, area=AREA)
add_crud(router, "/templates", "kit_templates", TemplateIn, TemplateOut, wave=WAVE, area=AREA)
add_crud(router, "/vault", "kit_vault", VaultDocumentUpdate, VaultDocumentOut, wave=WAVE, area=AREA,
         ops=("list", "get", "update", "delete"))


@router.post("/facts/{item_id}/approve", response_model=FactOut, name="kit_facts_approve")
async def approve_fact(item_id: uuid.UUID) -> FactOut:
    not_implemented(WAVE, AREA)


@router.post("/facts/{item_id}/retire", response_model=FactOut, name="kit_facts_retire")
async def retire_fact(item_id: uuid.UUID) -> FactOut:
    not_implemented(WAVE, AREA)


@router.post("/guardrails/check", response_model=GuardrailCheckOut, name="kit_guardrails_check")
async def check_guardrails(body: GuardrailCheckIn) -> GuardrailCheckOut:
    not_implemented(WAVE, AREA)


@router.post("/answers/match", response_model=AnswerMatchOut, name="kit_answers_match")
async def match_answer(body: AnswerMatchIn) -> AnswerMatchOut:
    not_implemented(WAVE, AREA)


@router.post("/vault", response_model=VaultDocumentOut, status_code=status.HTTP_201_CREATED,
             name="kit_vault_upload")
async def upload_vault_document(
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    doc_type: Annotated[Literal["cv", "degree", "transcript", "id", "photo", "cert", "other"], Form()],
    sensitivity: Annotated[Literal["normal", "on_request", "after_offer_only"], Form()] = "normal",
) -> VaultDocumentOut:
    not_implemented(WAVE, AREA)


@router.get("/vault/{item_id}/download", name="kit_vault_download",
            responses={200: {"content": {"application/octet-stream": {}}}})
async def download_vault_document(item_id: uuid.UUID) -> None:
    not_implemented(WAVE, AREA)


@router.get("/prompts", response_model=list[PromptOut], name="kit_prompts_list")
async def list_prompts(stage: str | None = None) -> list[PromptOut]:
    not_implemented(WAVE, "llm")


@router.post("/prompts", response_model=PromptOut, status_code=status.HTTP_201_CREATED,
             name="kit_prompts_create_version")
async def create_prompt_version(body: PromptIn) -> PromptOut:
    """Each save is a new version; activating one records a ConfigRevision."""
    not_implemented(WAVE, "llm")


@router.post("/prompts/{item_id}/activate", response_model=PromptOut, name="kit_prompts_activate")
async def activate_prompt(item_id: uuid.UUID) -> PromptOut:
    not_implemented(WAVE, "llm")


@router.get("/review", response_model=Page[ReviewItem], name="kit_review_list")
async def list_review(entity: Annotated[ReviewEntity | None, Query()] = None) -> Page[ReviewItem]:
    """Everything marked needs_review, stale items first (DESIGN.md 13 step 4)."""
    not_implemented(WAVE, AREA)


@router.post("/review/{entity}/{item_id}", response_model=Ok, name="kit_review_decide")
async def decide_review(entity: ReviewEntity, item_id: uuid.UUID, body: ReviewDecision) -> Ok:
    not_implemented(WAVE, AREA)
