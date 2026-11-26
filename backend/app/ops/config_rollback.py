"""Restore a settings or configuration revision as a NEW revision (never an edit of history).

What a rollback may do is the same as what a normal change may do: a setting goes back through the
settings service (validators and cross-checks run; a setting with its own endpoint, such as the global
pause, is refused), a prompt version is activated again, and a model route goes through the route
activation, so the "tested recently" rule still holds. Rollback affects future work only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.settings import service as settings_service
from app.core.settings.types import SettingValueError
from app.llm import prompts as prompt_registry
from app.models.kit import Prompt
from app.models.platform import ConfigKind, ConfigRevision, SettingRevision

# Settings whose own endpoint enforces what the generic write cannot (the restore lock, pause effects).
OWN_ENDPOINT = {
    "automation.paused": "use PUT /api/autopilot (and POST /api/autopilot/resume-after-restore after a restore)",
}


class RollbackError(Exception):
    """Refused; ``status`` is the HTTP status the API answers with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class RolledBack:
    new_id: uuid.UUID
    kind: str


async def _newest_config(session: AsyncSession, kind: ConfigKind, subject_id: uuid.UUID | None) -> ConfigRevision:
    row = await session.scalar(select(ConfigRevision).where(
        ConfigRevision.kind == kind, ConfigRevision.subject_id == subject_id)
        .order_by(ConfigRevision.version.desc()).limit(1))
    assert row is not None
    return row


async def rollback_setting(session: AsyncSession, rev: SettingRevision, *, actor: str,
                           note: str | None) -> RolledBack:
    if rev.key in OWN_ENDPOINT:
        raise RollbackError(409, f"{rev.key} cannot be restored here: {OWN_ENDPOINT[rev.key]}")
    current = await settings_service.get_value(session, rev.key)
    if current == rev.new_value:
        raise RollbackError(409, f"{rev.key} already has this value")
    try:
        await settings_service.set_value(session, rev.key, rev.new_value, actor=actor, rollback_of=rev.id,
                                         reason=note or f"Restored the value of version {rev.version}")
    except SettingValueError as exc:
        raise RollbackError(422, f"that value is no longer valid for {rev.key}: {exc}") from exc
    new = await session.scalar(select(SettingRevision).where(SettingRevision.rollback_of == rev.id)
                               .order_by(SettingRevision.created_at.desc()).limit(1))
    assert new is not None
    await audit.record(session, actor=actor, action="config.rolled_back", subject_type="setting",
                       subject_id=rev.key, detail={"revision": str(rev.id), "version": rev.version})
    return RolledBack(new.id, "setting")


async def _rollback_prompt(session: AsyncSession, rev: ConfigRevision, *, actor: str) -> None:
    snap: dict[str, Any] = rev.snapshot
    try:
        prompt_id = uuid.UUID(str(snap["prompt_id"]))
    except (KeyError, ValueError) as exc:
        raise RollbackError(409, "this revision does not record which prompt version it was") from exc
    prompt = await session.get(Prompt, prompt_id)
    if prompt is None:
        raise RollbackError(409, "that prompt version no longer exists")
    if prompt.active:
        raise RollbackError(409, "this prompt version is already the active one")
    await prompt_registry.activate(session, prompt_id, actor=actor)


async def rollback_config(session: AsyncSession, rev: ConfigRevision, *, actor: str, note: str | None,
                          route_activator: Any = None) -> RolledBack:
    if rev.kind == ConfigKind.prompt:
        await _rollback_prompt(session, rev, actor=actor)
    elif rev.kind == ConfigKind.model_routing:
        if route_activator is None:
            raise RollbackError(409, "model routes are restored from Settings, AI")
        await route_activator(rev.snapshot, note)
    else:
        raise RollbackError(409, f"{rev.kind.value} revisions cannot be restored here yet")
    new = await _newest_config(session, rev.kind, rev.subject_id)
    if new.id == rev.id:
        raise RollbackError(409, "nothing changed: this is already the current version")
    new.rollback_of = rev.id
    new.note = note or f"Restored version {rev.version}"
    await session.flush()
    await audit.record(session, actor=actor, action="config.rolled_back", subject_type=rev.kind.value,
                       subject_id=rev.subject_id, detail={"revision": str(rev.id), "version": rev.version})
    return RolledBack(new.id, rev.kind.value)
