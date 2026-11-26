"""Settings (registry-backed), appearance, and setting history."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import PrincipalDep, SessionDep
from app.core.settings import service
from app.core.settings.registry import GROUPS, REGISTRY
from app.core.settings.types import SettingValueError
from app.themes.service import get_theme

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingOut(BaseModel):
    key: str
    group: str
    label: str
    description: str
    kind: str
    value: Any
    default: Any
    is_default: bool
    nullable: bool
    choices: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


class SettingGroupOut(BaseModel):
    key: str
    label: str
    settings: list[SettingOut]


class SettingsOut(BaseModel):
    groups: list[SettingGroupOut]


class SettingWrite(BaseModel):
    value: Any = Field(description="New value; null resets a nullable setting")
    reason: str | None = Field(default=None, max_length=500)


class SettingRevisionOut(BaseModel):
    version: int
    old_value: Any
    new_value: Any
    changed_by: str
    changed_at: datetime
    reason: str | None = None


class Appearance(BaseModel):
    theme_id: str = Field(min_length=1, description="Theme id: slug (built-ins) or UUID")
    mode: Literal["light", "dark", "system"]
    density: Literal["comfortable", "compact"]
    radius: int | None = Field(default=None, ge=0, le=24)
    font_scale: float = Field(ge=0.85, le=1.25, description="Root text size relative to 14px")
    accent_override: str | None = Field(default=None, description="Accent swatch id or #RRGGBB; null = theme's")
    reduced_motion: bool


APPEARANCE_KEYS: dict[str, str] = {
    "theme_id": "appearance.theme_id",
    "mode": "appearance.mode",
    "density": "appearance.density",
    "radius": "appearance.radius",
    "font_scale": "appearance.font_scale",
    "accent_override": "appearance.accent_override",
    "reduced_motion": "appearance.reduced_motion",
}


def _out(state: service.SettingState) -> SettingOut:
    d = state.definition
    return SettingOut(
        key=d.key, group=d.group, label=d.label, description=d.description, kind=d.kind, value=state.value,
        default=d.effective_default(), is_default=state.is_default, nullable=d.nullable,
        choices=list(d.choices) if d.choices else None, minimum=d.minimum, maximum=d.maximum, unit=d.unit,
        version=state.version, updated_by=state.updated_by, updated_at=state.updated_at,
    )


async def read_appearance(session: SessionDep) -> Appearance:
    values = await service.values(session)
    return Appearance(**{field: values[key] for field, key in APPEARANCE_KEYS.items()})


@router.get("", response_model=SettingsOut, operation_id="settings_list")
async def list_settings(_: PrincipalDep, session: SessionDep) -> SettingsOut:
    states = await service.get_all(session)
    groups: list[SettingGroupOut] = []
    for group_key, label in GROUPS.items():
        items = [_out(s) for s in states.values() if s.definition.group == group_key]
        if items:
            groups.append(SettingGroupOut(key=group_key, label=label, settings=items))
    return SettingsOut(groups=groups)


@router.get("/appearance", response_model=Appearance, operation_id="settings_get_appearance")
async def get_appearance(session: SessionDep) -> Appearance:
    """Public: the sign-in screen is themed too. Contains nothing personal."""
    return await read_appearance(session)


@router.put("/appearance", response_model=Appearance, operation_id="settings_put_appearance")
async def put_appearance(body: Appearance, principal: PrincipalDep, session: SessionDep) -> Appearance:
    if await get_theme(session, body.theme_id) is None:
        raise HTTPException(422, detail="unknown theme_id")
    changes = {key: getattr(body, field) for field, key in APPEARANCE_KEYS.items()}
    changes["appearance.theme_id"] = str(body.theme_id)
    current = await service.values(session)
    changed = {k: v for k, v in changes.items() if current[k] != v}
    try:
        await service.set_many(session, changed, actor=principal.actor)
    except SettingValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return await read_appearance(session)


@router.get("/{key}", response_model=SettingOut, operation_id="settings_get")
async def get_setting(key: str, _: PrincipalDep, session: SessionDep) -> SettingOut:
    if key not in REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown setting")
    return _out((await service.get_all(session))[key])


@router.put("/{key}", response_model=SettingOut, operation_id="settings_put",
            responses={404: {"description": "Unknown setting"}, 422: {"description": "Invalid value"}})
async def put_setting(key: str, body: SettingWrite, principal: PrincipalDep, session: SessionDep) -> SettingOut:
    if key not in REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown setting")
    try:
        if key == "appearance.theme_id" and await get_theme(session, str(body.value)) is None:
            raise SettingValueError("unknown theme")
        await service.set_value(session, key, body.value, actor=principal.actor, reason=body.reason)
    except (SettingValueError, ValueError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _out((await service.get_all(session))[key])


@router.get("/{key}/history", response_model=list[SettingRevisionOut], operation_id="settings_history")
async def setting_history(key: str, _: PrincipalDep, session: SessionDep) -> list[SettingRevisionOut]:
    if key not in REGISTRY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown setting")
    rows = await service.history(session, key)
    return [SettingRevisionOut(version=r.version, old_value=r.old_value, new_value=r.new_value,
                               changed_by=r.changed_by, changed_at=r.created_at, reason=r.reason) for r in rows]
