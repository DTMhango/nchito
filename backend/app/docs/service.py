"""Render an application's spec to stored documents (DESIGN.md 9, 18.2).

Rendering is deterministic and idempotent: the inputs the file depends on are hashed
(``input_hash``); the same hash for the same application, kind and format finds the existing
``ApplicationDocument`` instead of making another. Files go through the ``FileStore`` and the row
keeps the sha256 of the stored bytes, the hash of the spec it came from, and any render warnings.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect.filestore import FileStore
from app.core import audit
from app.core.settings import service as settings_service
from app.docs.emit_docx import to_docx
from app.docs.emit_html import to_html
from app.docs.emit_pdf import needs_fallback_font, to_pdf
from app.docs.emit_text import to_text
from app.docs.layouts import DocKind, Fmt, TemplateDef, resolve_template
from app.docs.model import (
    DocModel,
    ExperienceView,
    PersonView,
    RenderWarning,
    build_cv,
    build_letter,
    person_view,
)
from app.kit import service as kit_service
from app.models.applications import Application
from app.models.base import ReviewState
from app.models.documents import ApplicationDocument
from app.models.kit import Experience, Fact, FactKind, FactStatus, Template

# Bump when an emitter changes what it writes for the same input; old rows keep their files.
RENDERER_VERSION = "1"

MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8",
}
DEFAULT_FORMATS: tuple[Fmt, ...] = ("pdf", "docx", "txt")
_TITLES = {"cv": "CV", "letter": "Cover letter"}


class TemplateNotFound(LookupError):
    pass


class DocumentFileMissing(RuntimeError):
    """The stored file is gone and a fresh render would not match the recorded hash."""


@dataclass
class Prepared:
    kind: DocKind
    template: TemplateDef
    model: DocModel
    warnings: list[RenderWarning]
    pages: int
    pdf: bytes
    spec_hash: str
    input_hash: str


@dataclass
class RenderResult:
    document: ApplicationDocument
    created: bool


def canonical_hash(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _default_template_key(kind: str, values: dict[str, Any]) -> str:
    return values["documents.cv_template" if kind == "cv" else "documents.letter_template"]


async def _template(session: AsyncSession, kind: DocKind, key: str, values: dict[str, Any]) -> TemplateDef:
    row = await session.scalar(select(Template).where(Template.key == key))
    resolved = resolve_template(key, kind, row)
    if resolved is None:
        raise TemplateNotFound(f"no {kind} template with key {key!r}")
    pages = values["documents.cv_pages" if kind == "cv" else "documents.letter_pages"]
    limits = resolved.limits.model_copy(update={
        "pages": resolved.limits.pages or pages,
        "paragraphs": resolved.limits.paragraphs or (values["documents.letter_paragraphs"] if kind == "letter"
                                                      else None)})
    return resolved.model_copy(update={"limits": limits})


async def _person(session: AsyncSession) -> PersonView:
    p = await kit_service.get_person(session)
    if p is None:
        return PersonView()
    return person_view(p.full_name, [p.email, p.phone, p.location, *p.links.values()])


async def _experiences(session: AsyncSession, ids: list[str]) -> dict[str, ExperienceView]:
    uuids: list[uuid.UUID] = []
    for raw in ids:
        try:
            uuids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not uuids:
        return {}
    rows = await session.scalars(select(Experience).where(Experience.id.in_(uuids)))
    return {str(e.id): ExperienceView(id=str(e.id), org=e.org, location=e.location, start=e.start_date,
                                      end=e.end_date, titles=list(e.titles)) for e in rows}


async def _education(session: AsyncSession) -> list[str]:
    rows = await session.scalars(select(Fact).where(
        Fact.kind == FactKind.education, Fact.status == FactStatus.approved,
        Fact.review_state == ReviewState.confirmed).order_by(Fact.code))
    return [f.text.strip() for f in rows if f.text.strip()]


async def prepare(session: AsyncSession, app: Application, kind: DocKind, template_key: str | None = None) -> Prepared:
    """Build the document model, lay it out once (page count) and compute the hashes."""
    values = await settings_service.values(session)
    template = await _template(session, kind, template_key or _default_template_key(kind, values), values)
    spec = app.spec
    person = await _person(session)
    if kind == "cv":
        experiences = await _experiences(session, [e.experience_id for e in spec.experience])
        model, warnings = build_cv(spec, person, experiences, await _education(session), template)
    else:
        model, warnings = build_letter(spec, person, values["documents.letter_salutation"],
                                       values["documents.letter_signoff"], template)
    title = _TITLES[kind]
    pdf, pages = to_pdf(model, template, f"{model.name} {title}".strip())
    limit = template.limits.pages
    if limit and pages > limit:
        warnings.append(RenderWarning(
            code="page_limit", message=f"The {title.lower()} runs to {pages} pages; the limit is {limit}.",
            detail={"pages": pages, "limit": limit}))
    if needs_fallback_font(model):
        warnings.append(RenderWarning(
            code="font_substituted", message="The text has characters the template font cannot show; "
            "an embedded font was used."))
    return Prepared(
        kind=kind, template=template, model=model, warnings=warnings, pages=pages, pdf=pdf,
        spec_hash=canonical_hash(spec.model_dump(mode="json")),
        input_hash=canonical_hash({"renderer": RENDERER_VERSION, "kind": kind,
                                   "template": template.model_dump(mode="json"),
                                   "model": model.model_dump(mode="json")}))


def _bytes_for(p: Prepared, fmt: Fmt) -> bytes:
    title = f"{p.model.name} {_TITLES[p.kind]}".strip()
    if fmt == "pdf":
        return p.pdf
    if fmt == "docx":
        return to_docx(p.model, p.template, title)
    if fmt == "txt":
        return to_text(p.model, upper_headings=p.template.layout.upper_headings).encode("utf-8")
    return to_html(p.model, p.template, title).encode("utf-8")


async def _existing(session: AsyncSession, app_id: uuid.UUID, p: Prepared, fmt: str) -> ApplicationDocument | None:
    return await session.scalar(select(ApplicationDocument).where(
        ApplicationDocument.application_id == app_id, ApplicationDocument.kind == p.kind,
        ApplicationDocument.fmt == fmt, ApplicationDocument.input_hash == p.input_hash))


async def render(session: AsyncSession, store: FileStore, app: Application, p: Prepared, fmt: Fmt,
                 *, actor: str = "system") -> RenderResult:
    """Store the document for ``fmt`` (or find the one already stored for this exact input)."""
    existing = await _existing(session, app.id, p, fmt)
    if existing is not None:
        await _ensure_file(store, existing, p, fmt)
        return RenderResult(existing, created=False)
    data = _bytes_for(p, fmt)
    key = f"applications/{app.id}/documents/{p.kind}-{p.input_hash[:16]}.{fmt}"
    stored = await store.put(key, data, MIME[fmt])
    values = dict(
        application_id=app.id, kind=p.kind, fmt=fmt, template_key=p.template.key, spec_hash=p.spec_hash,
        input_hash=p.input_hash, content_hash=stored.sha256, file_key=stored.key, size_bytes=stored.size_bytes,
        mime_type=MIME[fmt], page_count=p.pages, warnings=[w.model_dump(mode="json") for w in p.warnings])
    new_id = await session.scalar(pg_insert(ApplicationDocument).values(**values).on_conflict_do_nothing(
        constraint="application_kind_fmt_input").returning(ApplicationDocument.id))
    if new_id is None:  # a concurrent render got there first
        row = await _existing(session, app.id, p, fmt)
        assert row is not None
        return RenderResult(row, created=False)
    row = await session.get(ApplicationDocument, new_id)
    assert row is not None
    await audit.record(session, actor=actor, action="documents.rendered", subject_type="application_document",
                       subject_id=row.id, detail={"application_id": str(app.id), "kind": p.kind, "fmt": fmt,
                                                  "template": p.template.key, "sha256": stored.sha256,
                                                  "spec_hash": p.spec_hash})
    return RenderResult(row, created=True)


async def _ensure_file(store: FileStore, row: ApplicationDocument, p: Prepared, fmt: Fmt) -> None:
    if await store.exists(row.file_key):
        return
    data = _bytes_for(p, fmt)
    if hashlib.sha256(data).hexdigest() != row.content_hash:
        raise DocumentFileMissing(f"stored file for document {row.id} is missing and cannot be reproduced exactly")
    await store.put(row.file_key, data, row.mime_type)


async def render_formats(session: AsyncSession, store: FileStore, app: Application, kind: DocKind,
                         formats: tuple[Fmt, ...] = DEFAULT_FORMATS, template_key: str | None = None,
                         *, actor: str = "system") -> tuple[list[RenderResult], list[RenderWarning]]:
    p = await prepare(session, app, kind, template_key)
    results = [await render(session, store, app, p, f, actor=actor) for f in dict.fromkeys(formats)]
    return results, p.warnings


async def list_documents(session: AsyncSession, application_id: uuid.UUID) -> list[ApplicationDocument]:
    rows = await session.scalars(select(ApplicationDocument).where(
        ApplicationDocument.application_id == application_id).order_by(
        ApplicationDocument.created_at.desc(), ApplicationDocument.id))
    return list(rows)


def download_name(model_name: str, kind: str, fmt: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", model_name).strip("_") or "document"
    return f"{base}_{_TITLES[kind].replace(' ', '_')}.{fmt}"
