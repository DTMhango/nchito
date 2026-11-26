"""Theme schema (DESIGN.md 10.4), matching ``frontend/src/themes/schema.ts``.

Token names are the CSS custom properties of ``design/ui-preview.html`` without the leading
``--``. Every mode map must define the colour tokens (``COLOR_TOKENS``); character tokens
(``score-*``, ``chart-1..5``, ``shadow*``, ``display-*``, ``label-*``, ``space-k``,
``data-font``, ``label-font``, ``elev-top*``, ``panel-border``, ``shadow-pop``) are optional
and the frontend engine supplies defaults. Top-level ``score`` and ``chart`` hold the light
values and are the fallback when a mode map omits ``score-*`` / ``chart-n``.

Every value is checked against the strict grammar of its type in ``tokens.py`` (colours,
lengths, numbers, enumerated words; ``var(--t-<colour token>)`` only), fonts against the
bundled Fontsource families. A theme can therefore never carry CSS, a URL or script.

Built-in themes are the frontend's ``src/themes/builtin/*.json`` files verbatim, collected in
``builtin_themes.json``; their ``id`` is the slug (``copperbelt``...).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.json_types import ContrastWaiver, ScoreRamp, ThemeFonts, ThemeModeName
from app.themes.tokens import check_mode_map, check_plain_text, font_families, limits, required_tokens, valid_colour

COLOR_TOKENS: tuple[str, ...] = required_tokens()

THEME_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

EXPORT_FORMAT = "nchito-theme"
EXPORT_VERSION = 1


@lru_cache
def builtin_theme_data() -> list[dict[str, Any]]:
    text = resources.files("app.themes").joinpath("builtin_themes.json").read_text(encoding="utf-8")
    return json.loads(text)


def _colour(value: str) -> str:
    if not isinstance(value, str) or len(value) > limits()["value_length"] or not valid_colour(value.strip()):
        raise ValueError("not an allowed colour")
    return value


class ThemeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    fonts: ThemeFonts
    radius: int = Field(ge=0, le=32, description="Base radius in px; small/large derive from it")
    density: Literal["comfortable", "compact"]
    light: dict[str, str]
    dark: dict[str, str]
    chart: list[str] = Field(min_length=1, max_length=12, description="Light-mode palette; fallback for chart-n")
    score: ScoreRamp = Field(description="Light-mode ramp; fallback for score-*")

    @field_validator("name", "description")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return None if v is None else check_plain_text(v)

    @field_validator("light")
    @classmethod
    def _light(cls, v: dict[str, str]) -> dict[str, str]:
        return check_mode_map(v, "light")

    @field_validator("dark")
    @classmethod
    def _dark(cls, v: dict[str, str]) -> dict[str, str]:
        return check_mode_map(v, "dark")

    @field_validator("chart")
    @classmethod
    def _chart(cls, v: list[str]) -> list[str]:
        if any("var(" in c for c in v):
            raise ValueError("chart colours must be literal colours")
        return [_colour(c) for c in v]

    @model_validator(mode="after")
    def _fonts_and_score(self) -> ThemeBody:
        allowed = font_families()
        for slot, value in self.fonts.model_dump(exclude_none=True).items():
            if value not in allowed:
                raise ValueError(f"font {slot}: {value!r} is not a bundled family")
        for value in self.score.model_dump().values():
            if "var(" in value:
                raise ValueError("score colours must be literal colours")
            _colour(value)
        return self


class ThemeIn(ThemeBody):
    """Create/update body. ``id`` is an optional slug for a new theme; ignored on update."""

    id: str | None = Field(default=None, pattern=THEME_SLUG.pattern)
    accept_low_contrast: bool = Field(
        default=False, description="Save even though body text is below WCAG AA; recorded on the theme and audited")


class ThemeOut(ThemeBody):
    id: str = Field(description="Slug for built-ins (and owner themes created with one), else a UUID")
    builtin: bool
    is_default: bool = Field(default=False, description="The default theme (setting themes.default_theme_id)")
    revision: int | None = Field(default=None, description="Current revision number (owner themes)")
    can_undo: bool = False
    can_redo: bool = False
    contrast_waiver: ContrastWaiver | None = None


class ThemeDuplicateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80,
                             description="Name of the copy; default '<name> copy'")


class ThemeRevisionOut(BaseModel):
    number: int
    parent: int | None
    note: str
    actor: str
    created_at: datetime
    current: bool
    body: ThemeBody


class ThemeExport(BaseModel):
    """The theme file (``<name>.theme.json``). Import accepts this or a bare theme object."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["nchito-theme"] = EXPORT_FORMAT
    version: Literal[1] = EXPORT_VERSION
    theme: ThemeBody


class ContrastPairOut(BaseModel):
    mode: ThemeModeName
    fg: str
    bg: str
    use: Literal["body", "text", "ui", "graphic"]
    ratio: float
    aa: bool
    aaa: bool | None
    blocking: bool
