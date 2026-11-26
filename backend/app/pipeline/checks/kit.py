"""A read-only view of the Kit that the checks and the tailor stage share.

``KitView`` is plain data, so every check over it is pure. A fact is **usable** (may be sent to a
model and cited) only when it is approved, confirmed by the owner and not marked "keep out of AI
prompts". Keep-out facts stay in the view so the checks can make sure they never appear.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kit.guardrails import Rule, never_skill_rules
from app.models.base import ReviewState
from app.models.kit import Experience, Fact, FactStatus, Guardrail, Skill, SkillClaim, Track
from app.models.search import SkillAlias


@dataclass(frozen=True)
class FactView:
    code: str
    text: str
    kind: str
    experience_id: str | None
    approved: bool
    confirmed: bool
    keep_out: bool
    hash: str
    tags: tuple[str, ...] = ()
    tracks: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.approved and self.confirmed and not self.keep_out


@dataclass(frozen=True)
class ExperienceView:
    id: str
    org: str
    titles: tuple[str, ...]
    dates: tuple[str, ...]
    title_variants: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    forbidden_titles: tuple[str, ...] = ()

    def allowed_titles(self, track: str | None) -> tuple[str, ...]:
        extra = self.title_variants.get(track, ()) if track else ()
        return (*self.titles, *extra)


@dataclass(frozen=True)
class SkillView:
    name: str
    claim: str  # yes, no, never
    confirmed: bool


@dataclass(frozen=True)
class TrackView:
    key: str
    name: str
    lead_fact_codes: tuple[str, ...] = ()
    summary_fact_code: str | None = None
    tone_notes: str | None = None


@dataclass(frozen=True)
class KitView:
    facts: Mapping[str, FactView]
    experiences: Mapping[str, ExperienceView] = field(default_factory=dict)
    skills: Mapping[str, SkillView] = field(default_factory=dict)  # casefolded name -> skill
    rules: tuple[Rule, ...] = ()
    track: TrackView | None = None
    skill_aliases: Mapping[str, str] = field(default_factory=dict)  # casefolded alias -> canonical skill name

    def usable_facts(self) -> list[FactView]:
        return [f for f in self.facts.values() if f.usable]

    def keep_out_facts(self) -> list[FactView]:
        return [f for f in self.facts.values() if f.keep_out]

    def fact_hashes(self, codes: Iterable[str]) -> dict[str, str]:
        """Current hash of each code; a code no longer in the Kit maps to ``"missing"``."""
        return {c: (self.facts[c].hash if c in self.facts else "missing") for c in sorted(set(codes))}

    def digest(self) -> str:
        """One hash over every usable fact: changes whenever what a draft could rest on changes."""
        raw = json.dumps(sorted((f.code, f.hash) for f in self.usable_facts()))
        return hashlib.sha256(raw.encode()).hexdigest()


def fact_hash(f: Fact) -> str:
    raw = json.dumps([f.code, f.text, f.status.value, f.review_state.value, bool(f.keep_out_of_prompts),
                      str(f.experience_id) if f.experience_id else None], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def rule_from_row(g: Guardrail) -> Rule:
    return Rule(id=str(g.id), name=g.name, params=g.params, scope=tuple(g.scope) or ("everywhere",),
                severity=g.severity.value, strictness=g.strictness.value, enabled=bool(g.enabled), reason=g.reason)


async def load(session: AsyncSession, *, track_id: object | None = None) -> KitView:
    """Facts (except retired), experiences, skills, confirmed guardrails and the track."""
    facts = (await session.scalars(select(Fact).where(Fact.status != FactStatus.retired).order_by(Fact.code))).all()
    exps = (await session.scalars(select(Experience).order_by(Experience.sort_order))).all()
    skills = (await session.scalars(select(Skill))).all()
    # A guardrail still awaiting review is enforced anyway: a stricter check never hurts.
    guards = (await session.scalars(select(Guardrail).order_by(Guardrail.created_at))).all()
    track = await session.get(Track, track_id) if track_id is not None else None
    aliases = (await session.scalars(select(SkillAlias))).all()

    rules = [rule_from_row(g) for g in guards]
    rules += never_skill_rules(s.name for s in skills if s.claim == SkillClaim.never)
    return KitView(
        facts={f.code: FactView(code=f.code, text=f.text, kind=f.kind.value,
                                experience_id=str(f.experience_id) if f.experience_id else None,
                                approved=f.status == FactStatus.approved,
                                confirmed=f.review_state == ReviewState.confirmed,
                                keep_out=bool(f.keep_out_of_prompts), hash=fact_hash(f),
                                tags=tuple(f.tags or ()), tracks=tuple(f.tracks or ())) for f in facts},
        experiences={str(e.id): ExperienceView(
            id=str(e.id), org=e.org, titles=tuple(t.title for t in e.titles),
            dates=tuple(d for d in (e.start_date, e.end_date, *(x for t in e.titles for x in (t.start, t.end))) if d),
            title_variants={k: tuple(v) for k, v in (e.title_variants or {}).items()},
            forbidden_titles=tuple(e.forbidden_titles or ())) for e in exps},
        skills={s.name.casefold(): SkillView(name=s.name, claim=s.claim.value,
                                             confirmed=s.review_state == ReviewState.confirmed) for s in skills},
        rules=tuple(rules),
        track=TrackView(key=track.key, name=track.name, lead_fact_codes=tuple(track.lead_fact_codes or ()),
                        summary_fact_code=track.summary_fact_code, tone_notes=track.tone_notes) if track else None,
        skill_aliases={a.alias.strip().casefold(): a.canonical.strip() for a in aliases},
    )
