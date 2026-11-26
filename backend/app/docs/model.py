"""Format-free document model: what a CV or letter says, before any layout.

Built from the spec plus the Kit rows the spec points at. Every emitter (PDF, DOCX, text, HTML)
reads this one structure, so the formats cannot drift apart and the model's canonical JSON is
what the idempotency hash covers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from app.docs.layouts import TemplateDef, TemplateLayout
from app.schemas.json_types import ApplicationSpec, PersonField, TitleSpan


class RenderWarning(BaseModel):
    code: str
    message: str
    detail: dict[str, int | str] = Field(default_factory=dict)
    severity: Literal["warn"] = "warn"


class PersonView(BaseModel):
    """The person fields that may appear on a document (``show_on_cv`` only)."""

    name: str | None = None
    contact: list[str] = Field(default_factory=list)


class ExperienceView(BaseModel):
    id: str
    org: str
    location: str | None = None
    start: str | None = None
    end: str | None = None
    titles: list[TitleSpan] = Field(default_factory=list)


class Entry(BaseModel):
    title: str
    subtitle: str | None = None
    bullets: list[str] = Field(default_factory=list)


class Section(BaseModel):
    key: str
    title: str
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    entries: list[Entry] = Field(default_factory=list)


class DocModel(BaseModel):
    kind: Literal["cv", "letter", "pack"]
    name: str = ""
    contact: list[str] = Field(default_factory=list)
    headline: str | None = None
    sections: list[Section] = Field(default_factory=list)
    salutation: str | None = None
    paragraphs: list[str] = Field(default_factory=list)
    signoff: str | None = None


def person_view(name: PersonField | None, contact: Sequence[PersonField | None]) -> PersonView:
    def shown(f: PersonField | None) -> str | None:
        return f.value.strip() if f and f.visibility == "show_on_cv" and f.value.strip() else None

    return PersonView(name=shown(name), contact=[v for v in map(shown, contact) if v])


def _month(value: str | None, layout: TemplateLayout) -> str | None:
    if not value:
        return None
    names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    parts = value.split("-")
    try:
        year, month = parts[0], int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return value
    return f"{names[month - 1]} {year}" if 1 <= month <= 12 else year


def _span(exp: ExperienceView, layout: TemplateLayout) -> str | None:
    start = _month(exp.start, layout)
    if not start:
        return None
    end = _month(exp.end, layout) or layout.present_label
    return f"{start} {layout.date_joiner} {end}"


def build_cv(spec: ApplicationSpec, person: PersonView, experiences: dict[str, ExperienceView],
             education: Sequence[str], template: TemplateDef) -> tuple[DocModel, list[RenderWarning]]:
    layout, warnings = template.layout, []
    present: dict[str, Section] = {}

    def title_of(key: str) -> str:
        return layout.labels.get(key, key.replace("_", " ").title())

    if spec.summary and spec.summary.text.strip():
        present["summary"] = Section(key="summary", title=title_of("summary"), paragraphs=[spec.summary.text.strip()])
    if (comp := [c.text.strip() for c in spec.competencies if c.text.strip()]):
        present["competencies"] = Section(key="competencies", title=title_of("competencies"), bullets=comp)
    entries: list[Entry] = []
    cap = template.limits.bullets_per_role
    for item in spec.experience:
        exp = experiences.get(item.experience_id)
        bullets = [b.text.strip() for b in item.bullets if b.text.strip()]
        if exp is None:
            warnings.append(RenderWarning(
                code="unknown_experience", message="An experience in the spec is not in the library; "
                "its details are left out.", detail={"experience_id": item.experience_id}))
        title = item.title or (exp.titles[0].title if exp and exp.titles else "")
        sub = None
        if exp:
            sub = " | ".join(p for p in (exp.org, exp.location, _span(exp, layout)) if p)
        if cap and len(bullets) > cap:
            warnings.append(RenderWarning(
                code="bullets_per_role", message=f"{exp.org if exp else title} has {len(bullets)} bullets; "
                f"the template allows {cap}.", detail={"count": len(bullets), "limit": cap}))
        entries.append(Entry(title=title or (exp.org if exp else ""), subtitle=sub, bullets=bullets))
    if entries:
        present["experience"] = Section(key="experience", title=title_of("experience"), entries=entries)
    if (skills := [s.strip() for s in spec.skills if s.strip()]):
        present["skills"] = Section(key="skills", title=title_of("skills"), paragraphs=[", ".join(skills)])
    if education:
        present["education"] = Section(key="education", title=title_of("education"), bullets=list(education))

    order = [k for k in template.section_order if k in present]
    for key in present:
        if key not in order:
            warnings.append(RenderWarning(
                code="section_omitted", message=f"The spec has a {key} section the template does not place.",
                detail={"section": key}))
    if not person.name:
        warnings.append(RenderWarning(code="no_name", message="No name is marked to show on documents."))
    model = DocModel(kind="cv", name=person.name or "", contact=person.contact,
                     headline=spec.headline.text.strip() if spec.headline and spec.headline.text.strip() else None,
                     sections=[present[k] for k in order])
    return model, warnings


def build_letter(spec: ApplicationSpec, person: PersonView, salutation: str, signoff: str,
                 template: TemplateDef) -> tuple[DocModel, list[RenderWarning]]:
    paragraphs = [p.text.strip() for p in spec.letter if p.text.strip()]
    warnings: list[RenderWarning] = []
    limit = template.limits.paragraphs
    if limit and len(paragraphs) > limit:
        warnings.append(RenderWarning(
            code="paragraph_limit", message=f"The letter has {len(paragraphs)} paragraphs; the limit is {limit}.",
            detail={"count": len(paragraphs), "limit": limit}))
    if not paragraphs:
        warnings.append(RenderWarning(code="empty", message="The spec has no letter paragraphs."))
    if not person.name:
        warnings.append(RenderWarning(code="no_name", message="No name is marked to show on documents."))
    return DocModel(kind="letter", name=person.name or "", contact=person.contact, salutation=salutation,
                    paragraphs=paragraphs, signoff=signoff), warnings
