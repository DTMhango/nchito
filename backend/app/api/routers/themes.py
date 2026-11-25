"""Themes: list (public, so the sign-in screen is themed), create, update, delete.
Built-in themes are read-only (403)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import PrincipalDep, SessionDep
from app.core import audit
from app.core.settings import service as settings_service
from app.core.settings.registry import get_def
from app.themes import service
from app.themes.schema import ThemeIn, ThemeOut

router = APIRouter(prefix="/api/themes", tags=["themes"])


async def _load(session: SessionDep, theme_id: str):
    theme = await service.get_theme(session, theme_id)
    if theme is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="theme not found")
    return theme


@router.get("", response_model=list[ThemeOut], operation_id="themes_list")
async def list_themes(session: SessionDep) -> list[ThemeOut]:
    return [service.to_out(t) for t in await service.list_themes(session)]


@router.get("/{theme_id}", response_model=ThemeOut, operation_id="themes_get")
async def get_theme(theme_id: str, session: SessionDep) -> ThemeOut:
    return service.to_out(await _load(session, theme_id))


@router.post("", response_model=ThemeOut, status_code=status.HTTP_201_CREATED, operation_id="themes_create")
async def create_theme(body: ThemeIn, principal: PrincipalDep, session: SessionDep) -> ThemeOut:
    try:
        theme = await service.create_theme(session, body, slug=body.id)
    except service.ThemeIdTaken as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await audit.record(session, actor=principal.actor, action="theme.created", subject_type="theme",
                       subject_id=theme.id, detail={"name": theme.name})
    return service.to_out(theme)


@router.put("/{theme_id}", response_model=ThemeOut, operation_id="themes_update",
            responses={403: {"description": "Built-in themes are read-only"}})
async def update_theme(theme_id: str, body: ThemeIn, principal: PrincipalDep,
                       session: SessionDep) -> ThemeOut:
    theme = await _load(session, theme_id)
    try:
        theme = await service.update_theme(session, theme, body)
    except service.BuiltinThemeError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    await audit.record(session, actor=principal.actor, action="theme.updated", subject_type="theme",
                       subject_id=theme.id, detail={"name": theme.name})
    return service.to_out(theme)


@router.delete("/{theme_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="themes_delete",
               responses={403: {"description": "Built-in themes cannot be deleted"}})
async def delete_theme(theme_id: str, principal: PrincipalDep, session: SessionDep) -> Response:
    theme = await _load(session, theme_id)
    try:
        await service.delete_theme(session, theme)
    except service.BuiltinThemeError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    await audit.record(session, actor=principal.actor, action="theme.deleted", subject_type="theme",
                       subject_id=theme_id, detail={"name": theme.name})
    if await settings_service.get_value(session, "appearance.theme_id") in (theme_id, service.api_id(theme)):
        default = get_def("appearance.theme_id").effective_default()
        await settings_service.set_value(session, "appearance.theme_id", default, actor="system",
                                         reason="active theme deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
