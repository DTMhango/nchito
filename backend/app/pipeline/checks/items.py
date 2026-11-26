"""Walk a document spec into located items and guardrail documents, and hash it canonically."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from app.kit.guardrails import Document
from app.schemas.json_types import ApplicationSpec, DraftAnswer


@dataclass(frozen=True)
class Item:
    """One claim-bearing piece of text in the spec, with where it sits (shown in the Studio)."""

    path: str
    scope: str  # cv or letter
    text: str
    fact_ids: tuple[str, ...]
    experience_id: str | None = None


def content_hash(spec: ApplicationSpec) -> str:
    raw = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def items(spec: ApplicationSpec) -> list[Item]:
    out: list[Item] = []
    if spec.headline is not None:
        out.append(Item("headline", "cv", spec.headline.text, tuple(spec.headline.fact_ids)))
    if spec.summary is not None:
        out.append(Item("summary", "cv", spec.summary.text, tuple(spec.summary.fact_ids)))
    out += [Item(f"competencies[{i}]", "cv", c.text, tuple(c.fact_ids)) for i, c in enumerate(spec.competencies)]
    for i, exp in enumerate(spec.experience):
        out += [Item(f"experience[{i}].bullets[{j}]", "cv", b.text, tuple(b.fact_ids), exp.experience_id)
                for j, b in enumerate(exp.bullets)]
    out += [Item(f"letter[{i}]", "letter", p.text, tuple(p.fact_ids)) for i, p in enumerate(spec.letter)]
    return out


def cited_codes(spec: ApplicationSpec) -> set[str]:
    codes = {c for it in items(spec) for c in it.fact_ids}
    codes |= {c for m in spec.requirement_match for c in m.evidence_fact_ids}
    return codes


def cv_text(spec: ApplicationSpec) -> str:
    parts: list[str] = []
    if spec.headline is not None:
        parts.append(spec.headline.text)
    if spec.summary is not None:
        parts.append(spec.summary.text)
    parts += [c.text for c in spec.competencies]
    for exp in spec.experience:
        if exp.title:
            parts.append(exp.title)
        parts += [b.text for b in exp.bullets]
    if spec.skills:
        parts.append(", ".join(spec.skills))
    return "\n".join(parts)


def letter_text(spec: ApplicationSpec) -> str:
    return "\n\n".join(p.text for p in spec.letter)


def documents(spec: ApplicationSpec, answers: Sequence[DraftAnswer] = (),
              extra: Sequence[Document] = ()) -> list[Document]:
    """The outgoing set the guardrails run over: CV, letter, form answers, plus any ``extra`` (email
    body and the like, added by the packet check)."""
    cv_codes = {c for it in items(spec) if it.scope == "cv" for c in it.fact_ids}
    letter_codes = {c for it in items(spec) if it.scope == "letter" for c in it.fact_ids}
    docs = [Document(scope="cv", text=cv_text(spec), fact_codes=frozenset(cv_codes))]
    if spec.letter:
        docs.append(Document(scope="letter", text=letter_text(spec), fact_codes=frozenset(letter_codes)))
    given = [f"{a.question}\n{a.value}" for a in answers if a.outcome == "value" and a.value]
    if given:
        docs.append(Document(scope="form_answers", text="\n\n".join(given)))
    return [*docs, *extra]
