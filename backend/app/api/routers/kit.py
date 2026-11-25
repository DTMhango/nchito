"""Kit: person, library (experience, facts, skills, references), tracks, guardrails, answer
bank, vault, templates, prompts, and the needs-review queue. Wave 1 (Kit stream)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, ApiModel, Ok, Page, Timestamps, not_implemented
from app.api.deps import Principal, PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.core.conditions import ConditionSet
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.kit import answers as answer_matcher
from app.kit import crud, guardrails, service, vault
from app.kit.crud import Resource, add_kit_crud
from app.models.base import Origin, ReviewState
from app.models.kit import (
    Answer,
    Experience,
    Fact,
    FactStatus,
    Guardrail,
    Person,
    Reference,
    Skill,
    SkillClaim,
    Template,
    Track,
    VaultDocument,
)
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
CODE_ENFORCED = frozenset({"never_mention", "never_together", "require_wording", "omit_field", "format", "limit"})

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
async def get_person(session: SessionDep) -> PersonOut:
    row = await service.get_person(session)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="person not set up yet")
    return PersonOut.model_validate(row)


@router.put("/person", response_model=PersonOut, name="kit_person_put")
async def put_person(body: PersonIn, principal: PrincipalDep, session: SessionDep) -> PersonOut:
    row = await service.get_person(session)
    cols = body.model_dump()
    if row is None:
        row = Person(**cols, origin=Origin.owner, review_state=ReviewState.confirmed, confirmed_at=utcnow())
        session.add(row)
        action = "kit.person.created"
    else:
        for key, value in cols.items():
            setattr(row, key, value)
        action = "kit.person.updated"
    await session.flush()
    await session.refresh(row)
    await audit.record(session, actor=principal.actor, action=action, subject_type="person", subject_id=row.id,
                       detail={"fields": sorted(cols)})
    return PersonOut.model_validate(row)


# ----- library and the rest (CRUD) -------------------------------------------------------


async def _fact_on_create(session: AsyncSession, cols: dict[str, Any]) -> None:
    if cols.get("code") is None:
        cols["code"] = await service.next_fact_code(session)


async def _retire(session: AsyncSession, row: Fact) -> None:
    """Facts are never deleted: their codes are cited by tracks, packets and the audit trail."""
    row.status = FactStatus.retired


def _fact_filters(stmt: Select[Any], p: FactListParams) -> Select[Any]:
    if p.status:
        stmt = stmt.where(Fact.status == p.status)
    if p.review_state:
        stmt = stmt.where(Fact.review_state == p.review_state)
    if p.kind:
        stmt = stmt.where(Fact.kind == p.kind)
    if p.tag:
        stmt = stmt.where(Fact.tags.any(p.tag))
    if p.track:
        stmt = stmt.where(Fact.tracks.any(p.track))
    if p.q:
        like = f"%{p.q}%"
        stmt = stmt.where(or_(Fact.text.ilike(like), Fact.code.ilike(like)))
    return stmt


def _guardrail_columns(body: GuardrailIn) -> dict[str, Any]:
    return {**body.model_dump(), "type": body.params.type}


async def _drop_template(session: AsyncSession, row: Template) -> None:
    if row.builtin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="built-in templates cannot be deleted")
    await session.delete(row)


async def _drop_vault(session: AsyncSession, row: VaultDocument) -> None:
    await session.delete(row)
    await vault.remove(get_config().files_dir, row.file_path)


def _res(entity: str, model: Any, m_in: Any, m_out: Any, **kw: Any) -> Resource:
    return Resource(entity=entity, model=model, model_in=m_in, model_out=m_out, **kw)


add_kit_crud(router, "/experiences", "kit_experiences",
             _res("experience", Experience, ExperienceIn, ExperienceOut,
                  order_by=(Experience.sort_order, Experience.start_date.desc().nulls_last()),
                  subject=lambda r: r.org))
add_kit_crud(router, "/facts", "kit_facts",
             _res("fact", Fact, FactIn, FactOut, on_create=_fact_on_create,
                  order_by=(Fact.created_at, Fact.code), delete=_retire, subject=lambda r: r.code),
             list_params=FactListParams, apply_filters=_fact_filters)
add_kit_crud(router, "/skills", "kit_skills",
             _res("skill", Skill, SkillIn, SkillOut, order_by=(Skill.group, Skill.name), subject=lambda r: r.name))
add_kit_crud(router, "/references", "kit_references",
             _res("reference", Reference, ReferenceIn, ReferenceOut, order_by=(Reference.name,),
                  subject=lambda r: r.name))
add_kit_crud(router, "/tracks", "kit_tracks",
             _res("track", Track, TrackIn, TrackOut, order_by=(Track.priority.desc(), Track.key),
                  subject=lambda r: r.key))
add_kit_crud(router, "/guardrails", "kit_guardrails",
             _res("guardrail", Guardrail, GuardrailIn, GuardrailOut, to_columns=_guardrail_columns,
                  order_by=(Guardrail.created_at,), subject=lambda r: r.name))
add_kit_crud(router, "/answers", "kit_answers",
             _res("answer", Answer, AnswerIn, AnswerOut, order_by=(Answer.created_at,),
                  subject=lambda r: r.patterns.canonical))
add_kit_crud(router, "/templates", "kit_templates",
             _res("template", Template, TemplateIn, TemplateOut, order_by=(Template.kind, Template.key),
                  delete=_drop_template, subject=lambda r: r.key))
add_kit_crud(router, "/vault", "kit_vault",
             _res("vault_document", VaultDocument, VaultDocumentUpdate, VaultDocumentOut,
                  order_by=(VaultDocument.created_at,), delete=_drop_vault, subject=lambda r: r.title),
             ops=("list", "get", "update", "delete"))


async def _set_fact_status(session: AsyncSession, principal: Principal, item_id: uuid.UUID,
                           new: FactStatus, action: str) -> FactOut:
    fact = await session.get(Fact, item_id)
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="fact not found")
    fact.status = new
    if new == FactStatus.approved:  # approving is an explicit owner decision: it also confirms
        fact.review_state = ReviewState.confirmed
        fact.confirmed_at = utcnow()
    await session.flush()
    await session.refresh(fact)
    await audit.record(session, actor=principal.actor, action=action, subject_type="fact",
                       subject_id=fact.id, detail={"code": fact.code})
    return FactOut.model_validate(fact)


@router.post("/facts/{item_id}/approve", response_model=FactOut, name="kit_facts_approve")
async def approve_fact(item_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> FactOut:
    return await _set_fact_status(session, principal, item_id, FactStatus.approved, "kit.fact.approved")


@router.post("/facts/{item_id}/retire", response_model=FactOut, name="kit_facts_retire")
async def retire_fact(item_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> FactOut:
    return await _set_fact_status(session, principal, item_id, FactStatus.retired, "kit.fact.retired")


@router.post("/guardrails/check", response_model=GuardrailCheckOut, name="kit_guardrails_check")
async def check_guardrails(body: GuardrailCheckIn, session: SessionDep) -> GuardrailCheckOut:
    rows = (await session.scalars(select(Guardrail).where(Guardrail.enabled.is_(True)))).all()
    never = (await session.scalars(select(Skill.name).where(Skill.claim == SkillClaim.never))).all()
    rules = [
        guardrails.Rule(id=str(g.id), name=g.name, params=g.params, scope=tuple(g.scope),
                        severity=g.severity.value, strictness=g.strictness.value, reason=g.reason)
        for g in rows
    ] + guardrails.never_skill_rules(never)
    docs = [guardrails.Document(scope=scope, text=text) for scope, text in body.texts.items()]
    violations = guardrails.check(rules, docs, file_names=body.file_names)
    failed = {v.guardrail_id for v in violations}
    results = [
        CheckResult(check=v.name, status=v.status, detail=v.detail, guardrail_id=v.guardrail_id)
        for v in violations
    ] + [CheckResult(check=r.name, status="pass", guardrail_id=r.id) for r in rules
         if r.id not in failed and r.params.type in CODE_ENFORCED]
    return GuardrailCheckOut(results=results, blocked=guardrails.blocked(violations))


@router.post("/answers/match", response_model=AnswerMatchOut, name="kit_answers_match")
async def match_answer(body: AnswerMatchIn, session: SessionDep) -> AnswerMatchOut:
    rows = (await session.scalars(select(Answer))).all()
    records = [
        answer_matcher.AnswerRecord(
            id=a.id, patterns=(a.patterns.canonical, *a.patterns.variants), value=a.value,
            answer_class=a.answer_class.value, conditions=a.conditions, scope=a.scope.value,
            scope_ref=a.scope_ref, settled=a.settled, confirmed=a.review_state == ReviewState.confirmed,
            forced_choice=a.forced_choice, review_after=a.review_after)
        for a in rows
    ]
    threshold = await settings_service.get_value(session, "answers.match_similarity")
    result = answer_matcher.match(body.question, records, threshold=threshold, context=body.context,
                                  options=body.options, today=utcnow().date())
    return AnswerMatchOut(outcome=result.outcome, answer_id=result.answer_id, value=result.value,
                          select=result.select, similarity=result.similarity)


@router.post("/vault", response_model=VaultDocumentOut, status_code=status.HTTP_201_CREATED,
             name="kit_vault_upload")
async def upload_vault_document(
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()],
    doc_type: Annotated[Literal["cv", "degree", "transcript", "id", "photo", "cert", "other"], Form()],
    principal: PrincipalDep,
    session: SessionDep,
    sensitivity: Annotated[Literal["normal", "on_request", "after_offer_only"], Form()] = "normal",
) -> VaultDocumentOut:
    mb = await settings_service.get_value(session, "documents.vault_max_upload_mb")
    limit = mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file is larger than the vault limit")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="file is empty")
    row = await service.store_vault_file(
        session, filename=file.filename or title, content=content, declared_mime=file.content_type,
        title=title, doc_type=doc_type, sensitivity=sensitivity)
    await audit.record(session, actor=principal.actor, action="kit.vault_document.created",
                       subject_type="vault_document", subject_id=row.id,
                       detail={"title": title, "doc_type": doc_type, "sha256": row.sha256,
                               "size_bytes": row.size_bytes})
    return VaultDocumentOut.model_validate(row)


@router.get("/vault/{item_id}/download", name="kit_vault_download",
            responses={200: {"content": {"application/octet-stream": {}}}})
async def download_vault_document(item_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> FileResponse:
    row = await session.get(VaultDocument, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vault document not found")
    path = vault.resolve(get_config().files_dir, row.file_path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="vault file is missing from the files directory")
    await audit.record(session, actor=principal.actor, action="kit.vault_document.downloaded",
                       subject_type="vault_document", subject_id=row.id, detail={"title": row.title})
    return FileResponse(path, media_type=row.mime_type, filename=vault.safe_name(row.title + path.suffix))


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
async def list_review(session: SessionDep,
                      entity: Annotated[ReviewEntity | None, Query()] = None) -> Page[ReviewItem]:
    """Everything marked needs_review, stale items first (DESIGN.md 13 step 4)."""
    rows = await service.review_queue(session, entity)
    items = [ReviewItem(entity=r.entity, id=r.id, title=r.title, group=r.group, stale_first_rank=i,  # type: ignore[arg-type]
                        conflicts_with=r.conflicts_with) for i, r in enumerate(rows)]
    return Page[ReviewItem](items=items, total=len(items))


@router.post("/review/{entity}/{item_id}", response_model=Ok, name="kit_review_decide")
async def decide_review(entity: ReviewEntity, item_id: uuid.UUID, body: ReviewDecision, principal: PrincipalDep,
                        session: SessionDep) -> Ok:
    """Confirm keeps the record; drop removes it (facts are retired so their code is never reused).
    Edit a record with its own PUT: it stays in the queue until confirmed."""
    model = service.REVIEW_MODELS[entity]
    row = await session.get(model, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")
    if row.review_state != ReviewState.needs_review:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{entity} is not waiting for review")
    if body.decision == "confirm":
        row.review_state = ReviewState.confirmed
        row.confirmed_at = utcnow()
    elif entity == "fact":
        row.status = FactStatus.retired
        row.review_state = ReviewState.confirmed
        row.confirmed_at = utcnow()
    else:
        if entity == "template" and row.builtin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="built-in templates cannot be dropped")
        await session.delete(row)
        if entity == "vault_document":
            await vault.remove(get_config().files_dir, row.file_path)
    await crud.flush_or_409(session, f"{entity} is still in use")
    await audit.record(session, actor=principal.actor, action=f"kit.{entity}.review_{body.decision}",
                       subject_type=entity, subject_id=item_id, detail={"note": body.note})
    return Ok()
