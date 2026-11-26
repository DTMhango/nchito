"""Themes: list (public, so the sign-in screen is themed), create, update, delete, plus the theme
studio's duplicate, revisions (undo/redo/restore), default, contrast report, import and export.
Built-in themes are read-only (403); the active and the default theme cannot be deleted (409)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.deps import PrincipalDep, SessionDep
from app.core import audit
from app.core.settings import service as settings_service
from app.models.platform import Theme
from app.themes import service
from app.themes.schema import (
    ContrastPairOut,
    ThemeBody,
    ThemeDuplicateIn,
    ThemeExport,
    ThemeIn,
    ThemeOut,
    ThemeRevisionOut,
)

router = APIRouter(prefix="/api/themes", tags=["themes"])

_LOW_CONTRAST = {422: {"description": "Invalid theme, or body text below WCAG AA (code theme_low_contrast) "
                                      "without accept_low_contrast"}}


async def _load(session: SessionDep, theme_id: str) -> Theme:
    theme = await service.get_theme(session, theme_id)
    if theme is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="theme not found")
    return theme


def _low_contrast(exc: service.LowContrast) -> HTTPException:
    pairs = [{"mode": r.mode, "fg": r.fg, "bg": r.bg, "ratio": r.ratio} for r in exc.failures]
    return HTTPException(422, detail={
        "code": "theme_low_contrast",
        "reason": "Body text is below WCAG AA contrast. Fix the colours, or accept it for this personal theme.",
        "pairs": pairs})


async def _audit(session: SessionDep, principal: Any, action: str, theme: Theme, **detail: Any) -> None:
    await audit.record(session, actor=principal.actor, action=action, subject_type="theme",
                       subject_id=theme.id, detail={"name": theme.name, **detail})


async def _audit_waiver(session: SessionDep, principal: Any, theme: Theme, before: Any) -> None:
    if theme.contrast_waiver is not None and theme.contrast_waiver != before:
        await _audit(session, principal, "theme.contrast_accepted", theme,
                     pairs=[p.model_dump() for p in theme.contrast_waiver.pairs])


@router.get("", response_model=list[ThemeOut], operation_id="themes_list")
async def list_themes(session: SessionDep) -> list[ThemeOut]:
    default_id = await service.default_theme_id(session)
    return [await service.to_out(session, t, default_id) for t in await service.list_themes(session)]


@router.post("/import", response_model=ThemeOut, status_code=status.HTTP_201_CREATED, operation_id="themes_import",
             openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {
                 "description": "A theme file: ThemeExport, or a bare theme object (ThemeBody; id and builtin "
                                "are ignored). Size-limited by themes.import_max_bytes.",
                 "type": "object"}}}}},
             responses={413: {"description": "Larger than themes.import_max_bytes"}, **_LOW_CONTRAST})
async def import_theme(request: Request, principal: PrincipalDep, session: SessionDep,
                       accept_low_contrast: bool = Query(default=False)) -> ThemeOut:
    limit = int(await settings_service.get_value(session, "themes.import_max_bytes"))
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, detail=f"theme file is larger than {limit} bytes")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            raise HTTPException(413, detail=f"theme file is larger than {limit} bytes")
    try:
        body = service.parse_theme_file(raw, limit)
        theme = await service.import_theme(session, body, actor=principal.actor,
                                           accept_low_contrast=accept_low_contrast)
    except service.ThemeFileError as exc:
        raise HTTPException(422, detail={"code": "invalid_theme_file", "reason": str(exc)}) from exc
    except service.LowContrast as exc:
        raise _low_contrast(exc) from exc
    await _audit(session, principal, "theme.imported", theme)
    await _audit_waiver(session, principal, theme, None)
    return await service.to_out(session, theme)


@router.post("/contrast", response_model=list[ContrastPairOut], operation_id="themes_contrast")
async def contrast_report(body: ThemeBody, _: PrincipalDep) -> list[ContrastPairOut]:
    """Every text/surface pair the app uses (derived from the token spec), with its WCAG ratio and result.
    The studio computes the same live; this is the server's view, which decides the save block."""
    return [ContrastPairOut(**r.__dict__) for r in service.contrast_report(body)]


@router.get("/{theme_id}", response_model=ThemeOut, operation_id="themes_get")
async def get_theme(theme_id: str, session: SessionDep) -> ThemeOut:
    return await service.to_out(session, await _load(session, theme_id))


@router.post("", response_model=ThemeOut, status_code=status.HTTP_201_CREATED, operation_id="themes_create",
             responses=_LOW_CONTRAST)
async def create_theme(body: ThemeIn, principal: PrincipalDep, session: SessionDep) -> ThemeOut:
    try:
        theme = await service.create_theme(session, ThemeBody.model_validate(body.model_dump(
            exclude={"id", "accept_low_contrast"})), slug=body.id, actor=principal.actor,
            accept_low_contrast=body.accept_low_contrast, check_contrast=True)
    except service.ThemeIdTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.LowContrast as exc:
        raise _low_contrast(exc) from exc
    await _audit(session, principal, "theme.created", theme)
    await _audit_waiver(session, principal, theme, None)
    return await service.to_out(session, theme)


@router.put("/{theme_id}", response_model=ThemeOut, operation_id="themes_update",
            responses={403: {"description": "Built-in themes are read-only"}, **_LOW_CONTRAST})
async def update_theme(theme_id: str, body: ThemeIn, principal: PrincipalDep,
                       session: SessionDep) -> ThemeOut:
    theme = await _load(session, theme_id)
    before = theme.contrast_waiver
    old_name = theme.name
    try:
        theme = await service.update_theme(session, theme, ThemeBody.model_validate(body.model_dump(
            exclude={"id", "accept_low_contrast"})), actor=principal.actor,
            accept_low_contrast=body.accept_low_contrast, check_contrast=True,
            note="Renamed" if body.name != old_name else "Saved")
    except service.BuiltinThemeError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except service.LowContrast as exc:
        raise _low_contrast(exc) from exc
    await _audit(session, principal, "theme.updated", theme, revision=theme.current_revision)
    await _audit_waiver(session, principal, theme, before)
    return await service.to_out(session, theme)


@router.delete("/{theme_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="themes_delete",
               responses={403: {"description": "Built-in themes cannot be deleted"},
                          409: {"description": "The active or the default theme cannot be deleted"}})
async def delete_theme(theme_id: str, principal: PrincipalDep, session: SessionDep) -> Response:
    theme = await _load(session, theme_id)
    try:
        await service.delete_theme(session, theme)
    except service.BuiltinThemeError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except service.ThemeInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await audit.record(session, actor=principal.actor, action="theme.deleted", subject_type="theme",
                       subject_id=theme_id, detail={"name": theme.name})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{theme_id}/duplicate", response_model=ThemeOut, status_code=status.HTTP_201_CREATED,
             operation_id="themes_duplicate")
async def duplicate_theme(theme_id: str, body: ThemeDuplicateIn, principal: PrincipalDep,
                          session: SessionDep) -> ThemeOut:
    source = await _load(session, theme_id)
    theme = await service.duplicate_theme(session, source, body.name, actor=principal.actor)
    await _audit(session, principal, "theme.created", theme, duplicated_from=service.api_id(source))
    return await service.to_out(session, theme)


@router.put("/{theme_id}/default", response_model=ThemeOut, operation_id="themes_set_default",
            responses={409: {"description": "The theme needs review (body text below AA, not accepted)"}})
async def set_default(theme_id: str, principal: PrincipalDep, session: SessionDep) -> ThemeOut:
    theme = await _load(session, theme_id)
    try:
        await service.set_default(session, theme, actor=principal.actor)
    except service.ThemeNeedsReview as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "theme_needs_review", "reason": str(exc)}) \
            from exc
    return await service.to_out(session, theme)


@router.get("/{theme_id}/export", response_model=ThemeExport, operation_id="themes_export")
async def export_theme(theme_id: str, _: PrincipalDep, session: SessionDep) -> ThemeExport:
    return service.export_file(await _load(session, theme_id))


@router.get("/{theme_id}/revisions", response_model=list[ThemeRevisionOut], operation_id="themes_revisions")
async def list_revisions(theme_id: str, _: PrincipalDep, session: SessionDep) -> list[ThemeRevisionOut]:
    theme = await _load(session, theme_id)
    return [ThemeRevisionOut(number=r.number, parent=r.parent, note=r.note, actor=r.actor, created_at=r.created_at,
                             current=r.number == theme.current_revision, body=ThemeBody.model_validate(r.body))
            for r in await service.list_revisions(session, theme)]


async def _move(theme_id: str, principal: Any, session: Any, action: str, number: int | None = None) -> ThemeOut:
    theme = await _load(session, theme_id)
    try:
        if action == "undo":
            theme = await service.undo(session, theme)
        elif action == "redo":
            theme = await service.redo(session, theme)
        else:
            theme = await service.restore(session, theme, number or 0)
    except service.BuiltinThemeError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except service.NoRevision as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _audit(session, principal, f"theme.{action}", theme, revision=theme.current_revision)
    return await service.to_out(session, theme)


_MOVE_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"description": "Built-in themes have no revisions"}, 409: {"description": "Nothing to move to"}}


@router.post("/{theme_id}/undo", response_model=ThemeOut, operation_id="themes_undo", responses=_MOVE_RESPONSES)
async def undo(theme_id: str, principal: PrincipalDep, session: SessionDep) -> ThemeOut:
    return await _move(theme_id, principal, session, "undo")


@router.post("/{theme_id}/redo", response_model=ThemeOut, operation_id="themes_redo", responses=_MOVE_RESPONSES)
async def redo(theme_id: str, principal: PrincipalDep, session: SessionDep) -> ThemeOut:
    return await _move(theme_id, principal, session, "redo")


@router.post("/{theme_id}/revisions/{number}/restore", response_model=ThemeOut, operation_id="themes_restore",
             responses=_MOVE_RESPONSES)
async def restore(theme_id: str, number: int, principal: PrincipalDep, session: SessionDep) -> ThemeOut:
    return await _move(theme_id, principal, session, "restore", number)
