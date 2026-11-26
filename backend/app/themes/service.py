"""Theme storage: built-ins are seeded (and refreshed) from ``builtin_themes.json`` and are
read-only; owner themes are ordinary rows with a revision history (undo/redo walks the edit path).
The API id of a theme is its slug when it has one (every built-in does), otherwise its UUID.

Rules (invariants, not settings): built-ins are immutable; the active and the default theme
cannot be deleted; body text below WCAG AA saves only with the owner's explicit acceptance,
which is recorded on the theme."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.platform import Theme, ThemeRevision
from app.schemas.json_types import ContrastWaiver, ContrastWaiverPair, ScoreRamp, ThemeFonts
from app.themes.ids import BUILTIN_SLUGS, builtin_theme_id
from app.themes.schema import EXPORT_FORMAT, ThemeBody, ThemeExport, ThemeOut, builtin_theme_data
from app.themes.tokens import PairResult, evaluate_contrast

# ThemeOut fields that an exported full theme may carry; import ignores them.
_OUT_ONLY = frozenset({"id", "builtin", "is_default", "revision", "can_undo", "can_redo", "contrast_waiver",
                       "needs_review"})


class BuiltinThemeError(PermissionError):
    pass


class ThemeIdTaken(ValueError):
    pass


class ThemeInUse(ValueError):
    pass


class LowContrast(ValueError):
    def __init__(self, failures: list[PairResult]):
        super().__init__("body text is below WCAG AA")
        self.failures = failures


class NoRevision(LookupError):
    pass


class ThemeFileError(ValueError):
    pass


def api_id(theme: Theme) -> str:
    return theme.slug or str(theme.id)


def body_of(theme: Theme) -> ThemeBody:
    return ThemeBody.model_validate({
        "name": theme.name, "description": theme.description,
        "fonts": theme.fonts.model_dump(exclude_none=True), "radius": theme.radius, "density": theme.density,
        "light": theme.light, "dark": theme.dark, "chart": theme.chart, "score": theme.score.model_dump()})


def _dump(body: ThemeBody) -> dict[str, Any]:
    data = body.model_dump()
    data["fonts"] = body.fonts.model_dump(exclude_none=True)
    return data


async def default_theme_id(session: AsyncSession) -> str:
    return str(await settings_service.get_value(session, "themes.default_theme_id"))


async def to_out(session: AsyncSession, theme: Theme, default_id: str | None = None) -> ThemeOut:
    if default_id is None:
        default_id = await default_theme_id(session)
    can_undo = can_redo = False
    if not theme.builtin and theme.current_revision is not None:
        can_undo = await _parent_of(session, theme) is not None
        can_redo = await _redo_target(session, theme) is not None
    return ThemeOut(
        id=api_id(theme), builtin=theme.builtin, name=theme.name, description=theme.description, fonts=theme.fonts,
        radius=theme.radius, density=theme.density, light=theme.light, dark=theme.dark,  # type: ignore[arg-type]
        chart=theme.chart, score=theme.score, is_default=api_id(theme) == default_id,
        revision=theme.current_revision, can_undo=can_undo, can_redo=can_redo, contrast_waiver=theme.contrast_waiver,
        needs_review=needs_review(theme),
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


def contrast_report(body: ThemeBody) -> list[PairResult]:
    score = body.score.model_dump()
    return [*evaluate_contrast(body.light, "light", body.chart, score),
            *evaluate_contrast(body.dark, "dark", body.chart, score)]


def blocking_pairs(body: ThemeBody) -> list[PairResult]:
    """Body-text pairs below WCAG AA: the studio's save block, also applied to themes arriving in a Kit."""
    return [r for r in contrast_report(body) if r.blocking]


def needs_review(theme: Theme) -> bool:
    """An owner theme whose body text fails AA and that the owner has not accepted (it arrived through a
    Kit import, which cannot carry an acceptance). It cannot be applied until reviewed in the studio."""
    return not theme.builtin and theme.contrast_waiver is None and bool(blocking_pairs(body_of(theme)))


class ThemeNeedsReview(ValueError):
    def __init__(self) -> None:
        super().__init__("this theme's body text is below WCAG AA and needs review in the theme studio first")


def check_applicable(theme: Theme) -> None:
    """Raise ThemeNeedsReview for a theme that may not be made active or default yet."""
    if needs_review(theme):
        raise ThemeNeedsReview()


def _waiver(body: ThemeBody, accept: bool, actor: str) -> ContrastWaiver | None:
    """None when body text passes AA; the recorded waiver when the owner accepted; else LowContrast."""
    failures = blocking_pairs(body)
    if not failures:
        return None
    if not accept:
        raise LowContrast(failures)
    return ContrastWaiver(
        pairs=[ContrastWaiverPair(mode=r.mode, fg=r.fg, bg=r.bg, ratio=r.ratio) for r in failures],  # type: ignore[arg-type]
        accepted_at=utcnow().isoformat(), accepted_by=actor)


# ---- seeding and reads ----

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


# ---- revisions ----

async def _revision(session: AsyncSession, theme: Theme, number: int | None) -> ThemeRevision | None:
    if number is None:
        return None
    return await session.scalar(select(ThemeRevision).where(ThemeRevision.theme_id == theme.id,
                                                            ThemeRevision.number == number))


async def _parent_of(session: AsyncSession, theme: Theme) -> ThemeRevision | None:
    current = await _revision(session, theme, theme.current_revision)
    return await _revision(session, theme, current.parent) if current else None


async def _redo_target(session: AsyncSession, theme: Theme) -> ThemeRevision | None:
    """The most recent revision edited from the current one."""
    return await session.scalar(
        select(ThemeRevision).where(ThemeRevision.theme_id == theme.id, ThemeRevision.parent == theme.current_revision)
        .order_by(ThemeRevision.number.desc()).limit(1))


async def _record_revision(session: AsyncSession, theme: Theme, body: ThemeBody, note: str, actor: str) -> None:
    top = await session.scalar(select(func.max(ThemeRevision.number)).where(ThemeRevision.theme_id == theme.id))
    number = (top or 0) + 1
    session.add(ThemeRevision(theme_id=theme.id, number=number, parent=theme.current_revision, body=_dump(body),
                              note=note[:120], actor=actor[:120]))
    theme.current_revision = number
    keep = int(await settings_service.get_value(session, "themes.revisions_kept"))
    await session.flush()
    await session.execute(delete(ThemeRevision).where(ThemeRevision.theme_id == theme.id,
                                                      ThemeRevision.number <= number - keep))


async def list_revisions(session: AsyncSession, theme: Theme) -> list[ThemeRevision]:
    return list((await session.scalars(select(ThemeRevision).where(ThemeRevision.theme_id == theme.id)
                                       .order_by(ThemeRevision.number.desc()))).all())


async def _move_to(session: AsyncSession, theme: Theme, rev: ThemeRevision | None) -> Theme:
    if theme.builtin:
        raise BuiltinThemeError("built-in themes have no revisions")
    if rev is None:
        raise NoRevision("nothing to go back or forward to")
    body = ThemeBody.model_validate(rev.body)
    _apply(theme, body)
    theme.current_revision = rev.number
    # A restored state keeps the waiver only if it still needs one (it was accepted when saved).
    if not any(r.blocking for r in contrast_report(body)):
        theme.contrast_waiver = None
    await session.flush()
    await session.refresh(theme)
    return theme


async def undo(session: AsyncSession, theme: Theme) -> Theme:
    return await _move_to(session, theme, await _parent_of(session, theme))


async def redo(session: AsyncSession, theme: Theme) -> Theme:
    return await _move_to(session, theme, await _redo_target(session, theme))


async def restore(session: AsyncSession, theme: Theme, number: int) -> Theme:
    return await _move_to(session, theme, await _revision(session, theme, number))


# ---- writes ----

async def create_theme(session: AsyncSession, body: ThemeBody, slug: str | None = None, *, actor: str = "system",
                       accept_low_contrast: bool = False, check_contrast: bool = False,
                       note: str = "Created") -> Theme:
    if slug is not None and await get_theme(session, slug) is not None:
        raise ThemeIdTaken(f"theme id {slug!r} is taken")
    waiver = _waiver(body, accept_low_contrast, actor) if check_contrast else None
    theme = Theme(builtin=False, slug=slug)
    _apply(theme, body)
    theme.contrast_waiver = waiver
    session.add(theme)
    await session.flush()
    await _record_revision(session, theme, body, note, actor)
    await session.refresh(theme)
    return theme


async def update_theme(session: AsyncSession, theme: Theme, body: ThemeBody, *, actor: str = "system",
                       accept_low_contrast: bool = False, check_contrast: bool = False,
                       note: str = "Saved") -> Theme:
    if theme.builtin:
        raise BuiltinThemeError("built-in themes are read-only; duplicate it instead")
    waiver = _waiver(body, accept_low_contrast, actor) if check_contrast else theme.contrast_waiver
    _apply(theme, body)
    theme.contrast_waiver = waiver
    await session.flush()
    await _record_revision(session, theme, body, note, actor)
    await session.refresh(theme)
    return theme


async def _free_name(session: AsyncSession, wanted: str) -> str:
    names = set((await session.scalars(select(Theme.name))).all())
    if wanted not in names:
        return wanted
    for i in range(2, 1000):
        candidate = f"{wanted[:72]} ({i})"
        if candidate not in names:
            return candidate
    return f"{wanted[:40]} {uuid.uuid4().hex[:8]}"


async def duplicate_theme(session: AsyncSession, source: Theme, name: str | None, *, actor: str) -> Theme:
    body = body_of(source).model_copy(update={"name": await _free_name(session, name or f"{source.name} copy")})
    # A copy of a theme that already carries a waiver keeps it; built-ins pass AA.
    # A copy of a theme that needs review needs review too (no acceptance is invented for it).
    accept = source.contrast_waiver is not None
    return await create_theme(session, body, actor=actor, accept_low_contrast=accept,
                              check_contrast=not needs_review(source),
                              note=f"Duplicated from {source.name}")


async def delete_theme(session: AsyncSession, theme: Theme) -> None:
    if theme.builtin:
        raise BuiltinThemeError("built-in themes cannot be deleted")
    tid = api_id(theme)
    if tid == str(await settings_service.get_value(session, "appearance.theme_id")):
        raise ThemeInUse("this theme is in use; switch to another theme first")
    if tid == await default_theme_id(session):
        raise ThemeInUse("this is the default theme; make another theme the default first")
    await session.delete(theme)
    await session.flush()


async def set_default(session: AsyncSession, theme: Theme, *, actor: str) -> None:
    check_applicable(theme)
    await settings_service.set_value(session, "themes.default_theme_id", api_id(theme), actor=actor,
                                     reason="set from the theme studio")


# ---- files ----

def export_file(theme: Theme) -> ThemeExport:
    return ThemeExport(theme=body_of(theme))


def parse_theme_file(raw: bytes, max_bytes: int) -> ThemeBody:
    """Validate an untrusted theme file strictly: size, JSON, then the theme schema (which admits only
    colours, lengths, numbers, enumerated words and bundled fonts). Raises ThemeFileError."""
    if len(raw) > max_bytes:
        raise ThemeFileError(f"theme file is larger than {max_bytes} bytes")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThemeFileError("not a JSON file") from exc
    if not isinstance(data, dict):
        raise ThemeFileError("a theme file is a JSON object")
    if data.get("format") == EXPORT_FORMAT:
        try:
            return ThemeExport.model_validate(data).theme
        except ValueError as exc:
            raise ThemeFileError(_first_error(exc)) from exc
    try:
        return ThemeBody.model_validate({k: v for k, v in data.items() if k not in _OUT_ONLY})
    except ValueError as exc:
        raise ThemeFileError(_first_error(exc)) from exc


def _first_error(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        first = errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        return f"{where}: {first.get('msg')}" if where else str(first.get("msg"))
    return str(exc)


async def import_theme(session: AsyncSession, body: ThemeBody, *, actor: str, accept_low_contrast: bool) -> Theme:
    body = body.model_copy(update={"name": await _free_name(session, body.name)})
    return await create_theme(session, body, actor=actor, accept_low_contrast=accept_low_contrast,
                              check_contrast=True, note="Imported")
