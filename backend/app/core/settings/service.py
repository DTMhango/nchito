"""Read and write settings: effective values, version history, audit.

No row means the registry default. Writing a value creates or updates the ``Setting`` row,
appends a ``SettingRevision`` (append-only) and an audit event in the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import publish
from app.core.settings.registry import REGISTRY, cross_check, get_def
from app.core.settings.types import SettingDef, SettingValueError
from app.models.platform import Setting, SettingRevision


@dataclass(frozen=True)
class SettingState:
    definition: SettingDef
    value: Any
    is_default: bool
    version: int
    updated_by: str | None
    updated_at: datetime | None


async def _rows(session: AsyncSession) -> dict[str, Setting]:
    rows = (await session.scalars(select(Setting))).all()
    return {r.key: r for r in rows}


def _effective(definition: SettingDef, row: Setting | None) -> Any:
    if row is None:
        return definition.effective_default()
    try:
        return definition.coerce(row.value)
    except SettingValueError:
        # A stored value that no longer validates (registry tightened) falls back to the default.
        return definition.effective_default()


async def get_all(session: AsyncSession) -> dict[str, SettingState]:
    rows = await _rows(session)
    out: dict[str, SettingState] = {}
    for key, definition in REGISTRY.items():
        row = rows.get(key)
        value = _effective(definition, row)
        out[key] = SettingState(
            definition=definition,
            value=value,
            is_default=value == definition.effective_default(),
            version=row.version if row else 0,
            updated_by=row.updated_by if row else None,
            updated_at=row.updated_at if row else None,
        )
    return out


async def values(session: AsyncSession) -> dict[str, Any]:
    return {k: s.value for k, s in (await get_all(session)).items()}


async def get_value(session: AsyncSession, key: str) -> Any:
    definition = get_def(key)
    row = await session.scalar(select(Setting).where(Setting.key == key))
    return _effective(definition, row)


# Caps can be entered in minor units or micros; the two are kept in step (micros wins when set).
_CAP_PAIRS = {"budget.monthly_cap_minor": "budget.monthly_cap_micros",
              "budget.per_run_cap_minor": "budget.per_run_cap_micros"}
_CAP_PAIRS_REV = {v: k for k, v in _CAP_PAIRS.items()}


async def set_value(
    session: AsyncSession, key: str, raw: Any, *, actor: str, reason: str | None = None,
    check_combination: bool = True,
) -> SettingState:
    """Validate and store a value, keeping a cap's minor and micros forms in step."""
    state = await _set_one(session, key, raw, actor=actor, reason=reason, check_combination=check_combination)
    if key in _CAP_PAIRS:
        await _set_one(session, _CAP_PAIRS[key], None, actor=actor, reason=reason, check_combination=False)
    elif key in _CAP_PAIRS_REV:
        from app.llm.money import micros_to_minor

        minor = None if state.value is None else micros_to_minor(state.value)
        await _set_one(session, _CAP_PAIRS_REV[key], minor, actor=actor, reason=reason, check_combination=False)
    return state


async def _set_one(
    session: AsyncSession, key: str, raw: Any, *, actor: str, reason: str | None = None,
    check_combination: bool = True,
) -> SettingState:
    """Validate and store a value. Raises ``SettingValueError`` (and changes nothing) if invalid."""
    definition = get_def(key)
    value = definition.coerce(raw)
    if check_combination:
        current = await values(session)
        current[key] = value
        cross_check(current)

    row = await session.scalar(select(Setting).where(Setting.key == key).with_for_update())
    old_value = _effective(definition, row)
    if row is not None and row.value == value:
        return (await get_all(session))[key]
    if row is None:
        row = Setting(key=key, value=value, version=1, updated_by=actor)
        session.add(row)
    else:
        row.value = value
        row.version += 1
        row.updated_by = actor
    session.add(SettingRevision(key=key, version=row.version, old_value=old_value, new_value=value,
                                changed_by=actor, reason=reason))
    await audit.record(session, actor=actor, action="setting.changed", subject_type="setting", subject_id=key,
                       detail={"old": old_value, "new": value, "version": row.version, "reason": reason})
    await publish(session, "settings.changed", {"key": key, "version": row.version})
    await session.flush()
    await session.refresh(row)
    return SettingState(definition=definition, value=value, is_default=value == definition.effective_default(),
                        version=row.version, updated_by=row.updated_by, updated_at=row.updated_at)


async def set_many(session: AsyncSession, changes: dict[str, Any], *, actor: str) -> None:
    """Apply several changes, validating the combination once before writing any."""
    coerced = {k: get_def(k).coerce(v) for k, v in changes.items()}
    combined = await values(session)
    combined.update(coerced)
    cross_check(combined)
    for key, value in coerced.items():
        await set_value(session, key, value, actor=actor, check_combination=False)


async def history(session: AsyncSession, key: str) -> list[SettingRevision]:
    get_def(key)
    rows = await session.scalars(
        select(SettingRevision).where(SettingRevision.key == key).order_by(SettingRevision.version.desc())
    )
    return list(rows.all())
