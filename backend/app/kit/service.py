"""Kit services: fact codes, the singleton person, the review queue, vault storage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_config
from app.kit import answers as answer_matcher
from app.kit import vault
from app.models.base import Origin, ReviewState
from app.models.kit import (
    Answer,
    Experience,
    Fact,
    FactStatus,
    Guardrail,
    Person,
    Reference,
    Sensitivity,
    Skill,
    Template,
    Track,
    VaultDocument,
)
from app.models.search import Campaign

REVIEW_MODELS: dict[str, Any] = {
    "person": Person, "experience": Experience, "fact": Fact, "skill": Skill, "reference": Reference,
    "track": Track, "guardrail": Guardrail, "answer": Answer, "vault_document": VaultDocument,
    "template": Template, "campaign": Campaign,
}

# Answer groups the review screen lists first (DESIGN.md 13 step 4). Keywords are matched
# against the canonical question; the first group that matches wins.
ANSWER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pay_floors", ("salary", "pay ", "compensation", "remuneration", "rate")),
    ("visa", ("visa", "sponsor", "work permit", "right to work", "authori")),
    ("relocation", ("relocat", "move to")),
    ("countries", ("country", "reside", "citizen", "nationality")),
    ("seniority", ("seniority", "level", "years of experience")),
    ("notice", ("notice", "start date", "available")),
)


async def next_fact_code(session: AsyncSession) -> str:
    """``F-<n+1>``. Codes are never reused: facts are retired, not deleted, and the next
    number is one above the highest ever stored. A transaction lock serialises allocation."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('kit.fact.code'))"))
    top = await session.scalar(select(func.max(cast(func.substr(Fact.code, 3), Integer))))
    return f"F-{(top or 0) + 1}"


async def get_person(session: AsyncSession) -> Person | None:
    return await session.scalar(select(Person).order_by(Person.created_at).limit(1))


def vault_limit_bytes(megabytes: int) -> int:
    return megabytes * 1024 * 1024


async def store_vault_file(
    session: AsyncSession, *, filename: str, content: bytes, declared_mime: str | None, title: str,
    doc_type: str, sensitivity: str, origin: Origin = Origin.owner,
    review_state: ReviewState = ReviewState.confirmed,
) -> VaultDocument:
    sha = vault.sha256_hex(content)
    if await session.scalar(select(VaultDocument.id).where(VaultDocument.sha256 == sha)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="this file is already in the vault")
    mime = vault.guess_mime(filename, content, declared_mime)
    key = vault.new_key(sha, filename)
    await vault.write(get_config().files_dir, key, content)
    row = VaultDocument(
        doc_type=doc_type, title=title, file_path=key, sha256=sha, mime_type=mime, size_bytes=len(content),
        sensitivity=Sensitivity(sensitivity), has_text_layer=vault.has_text_layer(mime, content),
        origin=origin, review_state=review_state,
        confirmed_at=utcnow() if review_state == ReviewState.confirmed else None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# ----- review queue ---------------------------------------------------------------------


@dataclass
class ReviewRow:
    entity: str
    id: uuid.UUID
    title: str
    group: str
    created_at: Any
    conflicts_with: list[uuid.UUID]


def _title(entity: str, row: Any) -> str:
    match entity:
        case "person":
            return row.full_name.value
        case "experience":
            return row.org
        case "fact":
            return f"{row.code} {row.text[:80]}"
        case "answer":
            return row.patterns.canonical
        case "vault_document" | "template" | "campaign" | "skill" | "reference" | "track" | "guardrail":
            return getattr(row, "title", None) or row.name
    return str(row.id)


def answer_group(canonical: str) -> str:
    low = f"{canonical.casefold()} "
    return next((g for g, words in ANSWER_GROUPS if any(w in low for w in words)), "answer")


def _same(a: str, b: str) -> bool:
    return answer_matcher.normalise(a) == answer_matcher.normalise(b)


async def review_queue(session: AsyncSession, entity: str | None = None) -> list[ReviewRow]:
    rows: list[ReviewRow] = []
    for name, model in REVIEW_MODELS.items():
        if entity and name != entity:
            continue
        found = (await session.scalars(select(model).where(model.review_state == ReviewState.needs_review))).all()
        for r in found:
            group = answer_group(r.patterns.canonical) if name == "answer" else name
            rows.append(ReviewRow(name, r.id, _title(name, r), group, r.created_at, []))
    await _mark_conflicts(session, rows)
    rows.sort(key=lambda r: (r.created_at, str(r.id)))  # oldest first: the stale ones lead
    return rows


async def _mark_conflicts(session: AsyncSession, rows: list[ReviewRow]) -> None:
    """Pending answers that share a question with a different value, and duplicate fact texts."""
    pending_answers = {r.id: r for r in rows if r.entity == "answer"}
    if pending_answers:
        everything = (await session.scalars(select(Answer))).all()
        for a in everything:
            if a.id not in pending_answers:
                continue
            for b in everything:
                if b.id != a.id and _same(a.patterns.canonical, b.patterns.canonical) and b.value != a.value \
                        and a.conditions == b.conditions:
                    pending_answers[a.id].conflicts_with.append(b.id)
    pending_facts = {r.id: r for r in rows if r.entity == "fact"}
    if pending_facts:
        facts = (await session.scalars(select(Fact).where(Fact.status != FactStatus.retired))).all()
        for a in facts:
            if a.id not in pending_facts:
                continue
            for b in facts:
                if b.id != a.id and _same(a.text, b.text):
                    pending_facts[a.id].conflicts_with.append(b.id)
