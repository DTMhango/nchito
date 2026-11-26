"""Document endpoints, included by ``api/routers/applications.py``: list, render, download."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import Field
from sqlalchemy import select

from app.api.common import ApiModel, Timestamps
from app.api.deps import PrincipalDep, SessionDep
from app.connect.filestore import FileStore
from app.connect.local_store import default_file_store
from app.docs import service
from app.docs.layouts import DocKind, Fmt
from app.docs.model import RenderWarning
from app.models.applications import Application
from app.models.documents import ApplicationDocument

router = APIRouter()

StoreDep = Annotated[FileStore, Depends(default_file_store)]


class DocumentOut(Timestamps):
    application_id: uuid.UUID
    kind: Literal["cv", "letter"]
    fmt: Fmt
    template_key: str
    spec_hash: str = Field(description="sha256 of the canonical spec this file was rendered from")
    content_hash: str = Field(description="sha256 of the stored file; packets bind to this")
    size_bytes: int
    mime_type: str
    page_count: int | None
    warnings: list[RenderWarning]


class RenderIn(ApiModel):
    kind: DocKind
    template_key: str | None = Field(default=None, description="Template key; default from the documents settings")
    formats: list[Fmt] = Field(default_factory=lambda: list(service.DEFAULT_FORMATS), min_length=1)


class RenderOut(ApiModel):
    documents: list[DocumentOut]
    warnings: list[RenderWarning] = Field(description="Page limit, overflow and omission notices for the Studio")


async def _load(session: SessionDep, application_id: uuid.UUID) -> Application:
    app = await session.get(Application, application_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="application not found")
    return app


@router.get("/applications/{application_id}/documents", response_model=list[DocumentOut],
            name="applications_documents")
async def list_documents(application_id: uuid.UUID, session: SessionDep) -> list[DocumentOut]:
    """Every file rendered for this application (newest first), including ones from earlier spec versions."""
    await _load(session, application_id)
    return [DocumentOut.model_validate(d) for d in await service.list_documents(session, application_id)]


@router.post("/applications/{application_id}/documents/render", response_model=RenderOut,
             name="applications_render_documents")
async def render_documents(application_id: uuid.UUID, body: RenderIn, principal: PrincipalDep, session: SessionDep,
                           store: StoreDep) -> RenderOut:
    """Render the current spec. The same spec and template return the files already stored (no new rows)."""
    app = await _load(session, application_id)
    try:
        results, warnings = await service.render_formats(
            session, store, app, body.kind, tuple(body.formats), body.template_key, actor=principal.actor)
    except service.TemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DocumentFileMissing as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RenderOut(documents=[DocumentOut.model_validate(r.document) for r in results], warnings=warnings)


def _file_response(data: bytes, doc: ApplicationDocument, filename: str) -> Response:
    return Response(content=data, media_type=doc.mime_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-SHA256": doc.content_hash,
        "X-Document-Id": str(doc.id),
        "Cache-Control": "private, no-store",
    })


@router.get("/applications/{application_id}/documents/{kind}", name="applications_document",
            responses={200: {"content": {"application/pdf": {}, "text/html": {}, "text/plain": {},
                                         service.MIME["docx"]: {}}}})
async def document(application_id: uuid.UUID, kind: Literal["cv", "letter", "answers"], session: SessionDep,
                   principal: PrincipalDep, store: StoreDep, fmt: Fmt = "pdf",
                   template: Annotated[str | None, Query(description="Template key")] = None) -> Response:
    """Download the current spec's document, rendering it first when it is not stored yet.

    Warnings travel in the ``X-Render-Warnings`` header as a count; the render endpoint lists them.
    """
    app = await _load(session, application_id)
    if kind == "answers":  # from the current packet, exactly what would be sent
        from app.apply import handoff, packets

        packet = await packets.current(session, app.id)
        if packet is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no packet has been built")
        return Response(handoff.answers_sheet(packet.contents).encode("utf-8"), media_type="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="answers-{app.id}.txt"'})
    try:
        p = await service.prepare(session, app, kind, template)
        result = await service.render(session, store, app, p, fmt, actor=principal.actor)
    except service.TemplateNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DocumentFileMissing as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    doc = result.document
    response = _file_response(await store.get(doc.file_key), doc, service.download_name(p.model.name, kind, fmt))
    response.headers["X-Render-Warnings"] = str(len(doc.warnings))
    return response


@router.get("/applications/{application_id}/document-files/{document_id}", name="applications_document_file")
async def document_file(application_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep,
                        store: StoreDep) -> Response:
    """Download a stored file exactly as rendered (what a packet's hash refers to), whatever the spec says now."""
    doc = await session.scalar(select(ApplicationDocument).where(
        ApplicationDocument.id == document_id, ApplicationDocument.application_id == application_id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    if not await store.exists(doc.file_key):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="the stored file is missing")
    return _file_response(await store.get(doc.file_key),
                          doc, f"{doc.kind}-{doc.id}.{doc.fmt}")
