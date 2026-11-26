"""Prompt registry: versioned prompts per stage in the ``prompt`` table.

Defaults live in ``prompt_defaults/<stage>.md`` and are loaded as version 1 (active) the first
time a stage is read. Saving creates a new, inactive version; activating one switches the stage
to it. Both write a ``ConfigRevision`` (kind ``prompt``) and an audit event, so the history shows
who changed what. Rolling back is activating an earlier version; it affects future work only.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.llm.routing import STAGES
from app.models.kit import Prompt
from app.models.platform import ConfigKind, ConfigRevision

DEFAULTS_DIR = Path(__file__).with_name("prompt_defaults")
_NAMESPACE = uuid.UUID("6b1f6d2e-4f43-4b8e-9a51-0d6f3c2a7e10")


class PromptError(ValueError):
    pass


def default_stages() -> list[str]:
    return sorted(p.stem for p in DEFAULTS_DIR.glob("*.md"))


def default_text(stage: str) -> str | None:
    path = DEFAULTS_DIR / f"{stage}.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def stage_subject(stage: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"prompt:{stage}")


def check_stage(stage: str) -> None:
    if stage not in STAGES:
        raise PromptError(f"unknown stage {stage!r}; one of: {', '.join(STAGES)}")


async def seed_defaults(session: AsyncSession) -> None:
    seeded = set((await session.scalars(select(Prompt.stage).distinct())).all())
    for stage in default_stages():
        if stage in seeded:
            continue
        text = default_text(stage)
        assert text is not None
        session.add(Prompt(stage=stage, text=text, version=1, active=True, note="Default"))
    await session.flush()


async def list_prompts(session: AsyncSession, stage: str | None = None) -> list[Prompt]:
    await seed_defaults(session)
    query = select(Prompt).order_by(Prompt.stage, Prompt.version.desc())
    if stage is not None:
        query = query.where(Prompt.stage == stage)
    return list((await session.scalars(query)).all())


async def active_prompt(session: AsyncSession, stage: str) -> Prompt | None:
    """The prompt text a stage uses now (callers put it in a system ``TextPart``)."""
    await seed_defaults(session)
    return await session.scalar(select(Prompt).where(Prompt.stage == stage, Prompt.active.is_(True)))


async def _record(session: AsyncSession, stage: str, prompt: Prompt, *, actor: str, change: str,
                  previous: Prompt | None) -> None:
    subject = stage_subject(stage)
    version = (await session.scalar(select(func.coalesce(func.max(ConfigRevision.version), 0)).where(
        ConfigRevision.kind == ConfigKind.prompt, ConfigRevision.subject_id == subject)) or 0) + 1
    session.add(ConfigRevision(
        kind=ConfigKind.prompt, subject_id=subject, version=version, author=actor, note=f"{change} v{prompt.version}",
        snapshot={"stage": stage, "prompt_id": str(prompt.id), "prompt_version": prompt.version,
                  "active": prompt.active, "text": prompt.text},
        diff={"change": change, "from_version": previous.version if previous else None,
              "to_version": prompt.version}))
    await audit.record(session, actor=actor, action=f"prompt.{change}", subject_type="prompt", subject_id=prompt.id,
                       detail={"stage": stage, "version": prompt.version})


async def create_version(session: AsyncSession, *, stage: str, text: str, note: str | None, actor: str) -> Prompt:
    check_stage(stage)
    if not text.strip():
        raise PromptError("a prompt cannot be empty")
    await seed_defaults(session)
    latest = await session.scalar(select(func.max(Prompt.version)).where(Prompt.stage == stage)) or 0
    previous = await session.scalar(select(Prompt).where(Prompt.stage == stage, Prompt.active.is_(True)))
    prompt = Prompt(stage=stage, text=text, version=latest + 1, active=False, note=note)
    session.add(prompt)
    await session.flush()
    await _record(session, stage, prompt, actor=actor, change="saved", previous=previous)
    return prompt


async def activate(session: AsyncSession, prompt_id: uuid.UUID, *, actor: str) -> Prompt | None:
    prompt = await session.get(Prompt, prompt_id, with_for_update=True)
    if prompt is None:
        return None
    if prompt.active:
        return prompt
    previous = await session.scalar(select(Prompt).where(Prompt.stage == prompt.stage, Prompt.active.is_(True)))
    await session.execute(update(Prompt).where(Prompt.stage == prompt.stage, Prompt.active.is_(True))
                          .values(active=False))
    prompt.active = True
    await session.flush()
    await session.refresh(prompt)
    await _record(session, prompt.stage, prompt, actor=actor, change="activated", previous=previous)
    return prompt
