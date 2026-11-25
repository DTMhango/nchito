"""Theme schema (DESIGN.md 10.4), matching ``frontend/src/themes/schema.ts``.

Token names are the CSS custom properties of ``design/ui-preview.html`` without the leading
``--``. Every mode map must define the colour tokens (``COLOR_TOKENS``); character tokens
(``score-*``, ``chart-1..5``, ``shadow*``, ``display-*``, ``label-*``, ``space-k``,
``data-font``, ``label-font``, ``elev-top*``, ``panel-border``, ``shadow-pop``) are optional
and the frontend engine supplies defaults. Top-level ``score`` and ``chart`` hold the light
values and are the fallback when a mode map omits ``score-*`` / ``chart-n``.

Built-in themes are the frontend's ``src/themes/builtin/*.json`` files verbatim, collected in
``builtin_themes.json``; their ``id`` is the slug (``copperbelt``...).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.json_types import ScoreRamp, ThemeFonts

COLOR_TOKENS: tuple[str, ...] = (
    "bg", "bg-sunken", "surface", "surface-2", "border", "border-strong", "text", "text-muted", "text-faint",
    "primary", "primary-ink", "primary-fg", "primary-soft", "accent", "accent-ink", "accent-soft", "good",
    "good-soft", "warn", "warn-soft", "danger", "danger-soft", "info", "info-soft", "ring", "overlay",
)

THEME_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_TOKEN_NAME = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_UNSAFE = re.compile(r"[;{}<>\\]|url\s*\(|expression\s*\(|@import", re.I)


@lru_cache
def builtin_theme_data() -> list[dict[str, Any]]:
    text = resources.files("app.themes").joinpath("builtin_themes.json").read_text(encoding="utf-8")
    return json.loads(text)


def required_tokens() -> frozenset[str]:
    return frozenset(COLOR_TOKENS)


def _check_tokens(tokens: dict[str, str], mode: str) -> dict[str, str]:
    missing = required_tokens() - tokens.keys()
    if missing:
        raise ValueError(f"{mode}: missing tokens {sorted(missing)}")
    for name, value in tokens.items():
        if not _TOKEN_NAME.match(name):
            raise ValueError(f"{mode}: invalid token name {name!r}")
        if not isinstance(value, str) or not value.strip() or len(value) > 200 or _UNSAFE.search(value):
            raise ValueError(f"{mode}: unsafe or empty value for {name!r}")
    return tokens


def _check_css_value(value: str) -> str:
    if len(value) > 200 or _UNSAFE.search(value):
        raise ValueError("unsafe CSS value")
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

    @field_validator("light")
    @classmethod
    def _light(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_tokens(v, "light")

    @field_validator("dark")
    @classmethod
    def _dark(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_tokens(v, "dark")

    @field_validator("chart")
    @classmethod
    def _chart(cls, v: list[str]) -> list[str]:
        return [_check_css_value(c) for c in v]

    @model_validator(mode="after")
    def _fonts_and_score(self) -> ThemeBody:
        for value in self.fonts.model_dump(exclude_none=True).values():
            _check_css_value(value)
        for value in self.score.model_dump().values():
            _check_css_value(value)
        return self


class ThemeIn(ThemeBody):
    """Create/update body. ``id`` is an optional slug for a new theme; ignored on update."""

    id: str | None = Field(default=None, pattern=THEME_SLUG.pattern)


class ThemeOut(ThemeBody):
    id: str = Field(description="Slug for built-ins (and owner themes created with one), else a UUID")
    builtin: bool
