"""Template data: layout, section order, labels, limits (DESIGN.md 9).

The built-in templates are data, not code paths: one ``TemplateLayout`` per template drives the
PDF, DOCX, plain-text and HTML emitters. An owner's ``Template`` row with the same key overrides
the section order, limits, accent, name and HTML; a row with a new key starts from the built-in
base of its kind. Page and paragraph limits left empty fall back to the ``documents.*`` settings.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.kit import Template
from app.schemas.json_types import TemplateLimits

TEMPLATE_DIR = Path(__file__).parent / "templates"

DocKind = Literal["cv", "letter"]
ModelKind = Literal["cv", "letter", "pack"]  # pack: the interview pack export (not an application document)
Fmt = Literal["pdf", "docx", "txt", "html"]
FontFamily = Literal["sans", "serif"]
CV_SECTIONS = ("summary", "competencies", "experience", "skills", "education")


class TemplateLayout(BaseModel):
    """Everything visual about a template. Single column, real text, no images."""

    model_config = ConfigDict(frozen=True)

    font: FontFamily = "sans"
    base_pt: float = Field(default=10.5, ge=7, le=14)
    name_pt: float = Field(default=20, ge=10, le=36)
    heading_pt: float = Field(default=11.5, ge=8, le=18)
    margin_mm: float = Field(default=18, ge=10, le=35)
    line_height: float = Field(default=1.25, ge=1.0, le=1.8)
    paragraph_gap_pt: float = Field(default=4, ge=0, le=16)
    section_gap_pt: float = Field(default=10, ge=0, le=30)
    upper_headings: bool = True
    heading_rule: bool = False
    centered_header: bool = False
    accent: str = Field(default="#222222", pattern=r"^#[0-9a-fA-F]{6}$")
    bullet: str = "-"
    labels: dict[str, str] = Field(default_factory=dict)
    present_label: str = "Present"
    date_joiner: str = "to"


class TemplateDef(BaseModel):
    """A template ready to render: built-in data merged with the owner's row, if any."""

    model_config = ConfigDict(frozen=True)

    key: str
    kind: ModelKind
    name: str
    layout: TemplateLayout
    section_order: list[str]
    limits: TemplateLimits
    html: str
    builtin: bool = True


_CV_LABELS = {"summary": "Profile", "competencies": "Core competencies", "experience": "Experience",
              "skills": "Skills", "education": "Education"}

_BUILTINS: dict[str, tuple[DocKind, str, TemplateLayout, list[str]]] = {
    "classic": ("cv", "Classic", TemplateLayout(
        font="serif", base_pt=11, name_pt=22, heading_pt=12, margin_mm=20, line_height=1.25,
        centered_header=True, heading_rule=True, labels=_CV_LABELS), list(CV_SECTIONS)),
    "compact": ("cv", "Compact", TemplateLayout(
        font="sans", base_pt=9.5, name_pt=17, heading_pt=10, margin_mm=14, line_height=1.18,
        paragraph_gap_pt=2.5, section_gap_pt=6, labels=_CV_LABELS), list(CV_SECTIONS)),
    "modern": ("cv", "Modern", TemplateLayout(
        font="sans", base_pt=10.5, name_pt=24, heading_pt=11.5, margin_mm=18, accent="#1F4E79",
        upper_headings=False, heading_rule=True, labels=_CV_LABELS), list(CV_SECTIONS)),
    "letter-plain": ("letter", "Plain letter", TemplateLayout(
        font="serif", base_pt=11, name_pt=16, margin_mm=25, line_height=1.35, paragraph_gap_pt=9,
        upper_headings=False), []),
}

BASE_FOR_KIND: dict[str, str] = {"cv": "classic", "letter": "letter-plain"}


@cache
def _html_source(kind: str) -> str:
    return (TEMPLATE_DIR / f"{kind}.html.j2").read_text(encoding="utf-8")


def builtin_keys(kind: str | None = None) -> list[str]:
    return [k for k, (kd, *_rest) in _BUILTINS.items() if kind in (None, kd)]


def resolve_template(key: str, kind: DocKind, row: Template | None = None) -> TemplateDef | None:
    """Merge the built-in (or the kind's base) with the owner's row. None when the key is unknown."""
    if key in _BUILTINS:
        base_kind, name, layout, order = _BUILTINS[key]
        builtin = True
    elif row is not None:
        base_kind, name, layout, order = _BUILTINS[BASE_FOR_KIND[row.kind.value]]
        name = row.name
        builtin = False
    else:
        return None
    if base_kind != kind:
        return None
    limits = _BUILTIN_LIMITS.get(key, TemplateLimits())
    html = _html_source(kind)
    if row is not None:
        if row.section_order:
            order = list(row.section_order)
        limits = TemplateLimits(**{**limits.model_dump(), **row.limits.model_dump(exclude_none=True)})
        if row.accent:
            layout = layout.model_copy(update={"accent": row.accent})
        if row.html.strip() and not row.builtin:
            html = row.html
        name = row.name or name
    return TemplateDef(key=key, kind=kind, name=name, layout=layout, section_order=order, limits=limits,
                       html=html, builtin=builtin)


# Built-in templates leave limits empty so the documents.* settings apply; only the per-role bullet
# cap has no setting, and no built-in imposes one.
_BUILTIN_LIMITS: dict[str, TemplateLimits] = {}


# The interview pack export: a plain, readable layout with no page limit. Not an application
# document, so it is not offered as a CV or letter template and has no owner override.
PACK_KEY = "pack"
_PACK_LAYOUT = TemplateLayout(font="sans", base_pt=10.5, name_pt=18, heading_pt=12.5, margin_mm=18,
                              line_height=1.3, upper_headings=False, heading_rule=True, accent="#1F4E79")


def pack_template() -> TemplateDef:
    return TemplateDef(key=PACK_KEY, kind="pack", name="Interview pack", layout=_PACK_LAYOUT, section_order=[],
                       limits=TemplateLimits(), html=_html_source("pack"))
