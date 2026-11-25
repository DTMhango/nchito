"""Load a validated ``KitFile`` into the database (tests, the onboarding wizard, kit import).

Every loaded row is marked ``needs_review`` and ``origin=import``: nothing drives automation
until the owner confirms it. Loading is repeatable: rows are matched on stable keys (fact
``code``, track ``key``, template ``key``, skill name, ...) and updated in place, never
duplicated. An existing row whose content changed goes back to ``needs_review``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.kit import service, vault
from app.kit.schema import KitFile
from app.models.base import Origin, ReviewState
from app.models.kit import (
    Answer,
    Experience,
    Fact,
    Guardrail,
    Person,
    Reference,
    Skill,
    Template,
    Track,
    VaultDocument,
)


@dataclass
class LoadReport:
    created: Counter[str] = field(default_factory=Counter)
    updated: Counter[str] = field(default_factory=Counter)
    unchanged: Counter[str] = field(default_factory=Counter)
    skipped: list[str] = field(default_factory=list)


def _apply(session: AsyncSession, report: LoadReport, entity: str, model: Any, row: Any,
           cols: dict[str, Any]) -> Any:
    """Create ``row`` (None) or update it when a column differs; mark needs_review on change."""
    if row is None:
        row = model(**cols, origin=Origin.imported, review_state=ReviewState.needs_review)
        session.add(row)
        report.created[entity] += 1
        return row
    changed = False
    for key, value in cols.items():
        if getattr(row, key) != value and not _same_json(getattr(row, key), value):
            setattr(row, key, value)
            changed = True
    if changed:
        row.review_state = ReviewState.needs_review
        row.confirmed_at = None
        report.updated[entity] += 1
    else:
        report.unchanged[entity] += 1
    return row


def _same_json(current: Any, new: Any) -> bool:
    dump = getattr(current, "model_dump", None)
    if dump is not None and isinstance(new, dict):
        return dump(mode="json") == new
    if isinstance(current, list) and isinstance(new, list):
        return len(current) == len(new) and all(_same_json(c, n) or c == n for c, n in zip(current, new, strict=True))
    if isinstance(current, dict) and isinstance(new, dict):
        return all(_same_json(current.get(k), v) for k, v in new.items()) and current.keys() == new.keys()
    return False


async def load_kit(
    session: AsyncSession, kit: KitFile, *, actor: str = "system",
    vault_files: Mapping[str, bytes] | None = None,
) -> LoadReport:
    """Load the Kit sections (not rubrics, campaigns, sources, themes or history: other streams).

    ``vault_files`` maps a ``KitVaultDocument.path`` to its bytes; entries without bytes are
    reported in ``skipped``.
    """
    report = LoadReport()

    if kit.person:
        existing = await service.get_person(session)
        _apply(session, report, "person", Person, existing, kit.person.model_dump())

    experiences: dict[str, Experience] = {}
    for e in kit.experiences:
        cols = e.model_dump(exclude={"ref"})
        row = await session.scalar(
            select(Experience).where(Experience.org == e.org, Experience.start_date == e.start_date))
        experiences[e.ref] = _apply(session, report, "experience", Experience, row, cols)
    await session.flush()

    for f in kit.facts:
        cols = f.model_dump(exclude={"experience_ref"})
        cols["experience_id"] = experiences[f.experience_ref].id if f.experience_ref else None
        row = await session.scalar(select(Fact).where(Fact.code == f.code))
        _apply(session, report, "fact", Fact, row, cols)

    for s in kit.skills:
        row = await session.scalar(select(Skill).where(Skill.name == s.name))
        _apply(session, report, "skill", Skill, row, s.model_dump())

    for r in kit.references:
        row = await session.scalar(
            select(Reference).where(Reference.name == r.name, Reference.organisation == r.organisation))
        _apply(session, report, "reference", Reference, row, r.model_dump())

    for t in kit.tracks:
        row = await session.scalar(select(Track).where(Track.key == t.key))
        _apply(session, report, "track", Track, row, t.model_dump())

    for g in kit.guardrails:
        row = await session.scalar(select(Guardrail).where(Guardrail.name == g.name))
        _apply(session, report, "guardrail", Guardrail, row, {**g.model_dump(), "type": g.params.type})

    existing_answers = (await session.scalars(select(Answer))).all()
    for a in kit.answers:
        row = next((x for x in existing_answers
                    if x.patterns.canonical == a.patterns.canonical and x.conditions == a.conditions
                    and x.scope == a.scope and x.scope_ref == a.scope_ref), None)
        _apply(session, report, "answer", Answer, row, a.model_dump())

    for tpl in kit.templates:
        row = await session.scalar(select(Template).where(Template.key == tpl.key))
        _apply(session, report, "template", Template, row, tpl.model_dump())

    for v in kit.vault:
        content = (vault_files or {}).get(v.path)
        if content is None:
            report.skipped.append(f"vault:{v.path}")
            continue
        if await session.scalar(select(VaultDocument.id).where(VaultDocument.sha256 == vault.sha256_hex(content))):
            report.unchanged["vault_document"] += 1
            continue
        await service.store_vault_file(
            session, filename=v.path, content=content, declared_mime=None, title=v.title,
            doc_type=v.doc_type, sensitivity=v.sensitivity, origin=Origin.imported,
            review_state=ReviewState.needs_review)
        report.created["vault_document"] += 1

    await session.flush()
    await audit.record(session, actor=actor, action="kit.loaded", subject_type="kit",
                       detail={"created": dict(report.created), "updated": dict(report.updated),
                               "unchanged": dict(report.unchanged), "skipped": report.skipped})
    return report
