"""Theme storage: built-ins are seeded (and refreshed) from ``builtin_themes.json`` and are
read-only; owner themes are ordinary rows. The API id of a theme is its slug when it has one
(every built-in does), otherwise its UUID."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Theme
from app.schemas.json_types import ScoreRamp, ThemeFonts
from app.themes.ids import BUILTIN_SLUGS, builtin_theme_id
from app.themes.schema import ThemeBody, ThemeOut, builtin_theme_data


class BuiltinThemeError(PermissionError):
    pass


class ThemeIdTaken(ValueError):
    pass


def api_id(theme: Theme) -> str:
    return theme.slug or str(theme.id)


def to_out(theme: Theme) -> ThemeOut:
    return ThemeOut(
        id=api_id(theme), builtin=theme.builtin, name=theme.name, description=theme.description, fonts=theme.fonts,
        radius=theme.radius, density=theme.density, light=theme.light, dark=theme.dark,  # type: ignore[arg-type]
        chart=theme.chart, score=theme.score,
    )


def _apply(theme: Theme, body: ThemeBody) -> None:
    theme.name = body.name
    theme.description = body.description
    theme.fonts = ThemeFonts.model_validate(body.fonts.model_dump())
    theme.radius = body.radius
    theme.density = body.density
    theme.light = dict(body.light)
    theme.dark = dict(body.dark)
    theme.chart = list(body.chart)
    theme.score = ScoreRamp.model_validate(body.score.model_dump())


async def seed_builtin_themes(session: AsyncSession) -> int:
    """Insert or refresh the built-in themes. Idempotent."""
    count = 0
    for raw in builtin_theme_data():
        data = {k: v for k, v in raw.items() if k not in ("id", "builtin")}
        slug = raw["id"]
        body = ThemeBody.model_validate(data)
        theme_id = builtin_theme_id(slug)
        theme = await session.get(Theme, theme_id)
        if theme is None:
            theme = Theme(id=theme_id, slug=slug, builtin=True)
            session.add(theme)
        _apply(theme, body)
        count += 1
    await session.flush()
    return count


async def list_themes(session: AsyncSession) -> list[Theme]:
    """Built-ins first in their shipped order, then owner themes oldest first."""
    rows = list((await session.scalars(select(Theme).order_by(Theme.created_at, Theme.name))).all())
    order = {slug: i for i, slug in enumerate(BUILTIN_SLUGS)}
    return sorted(rows, key=lambda t: (0, order.get(t.slug or "", 99)) if t.builtin else (1, 0))


async def get_theme(session: AsyncSession, theme_id: str | uuid.UUID) -> Theme | None:
    """Look a theme up by its API id (slug or UUID)."""
    try:
        return await session.get(Theme, uuid.UUID(str(theme_id)))
    except ValueError:
        return await session.scalar(select(Theme).where(Theme.slug == str(theme_id)))


async def create_theme(session: AsyncSession, body: ThemeBody, slug: str | None = None) -> Theme:
    if slug is not None and await get_theme(session, slug) is not None:
        raise ThemeIdTaken(f"theme id {slug!r} is taken")
    theme = Theme(builtin=False, slug=slug)
    _apply(theme, body)
    session.add(theme)
    await session.flush()
    await session.refresh(theme)
    return theme


async def update_theme(session: AsyncSession, theme: Theme, body: ThemeBody) -> Theme:
    if theme.builtin:
        raise BuiltinThemeError("built-in themes are read-only; duplicate it instead")
    _apply(theme, body)
    await session.flush()
    await session.refresh(theme)
    return theme


async def delete_theme(session: AsyncSession, theme: Theme) -> None:
    if theme.builtin:
        raise BuiltinThemeError("built-in themes cannot be deleted")
    await session.delete(theme)
    await session.flush()
