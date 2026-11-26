"""Colour grammar and maths for theme tokens: strict parsing (the only colour syntaxes a theme may
store), OKLCH conversion, alpha compositing and WCAG 2 contrast. Mirrors
``frontend/src/themes/colour.ts``; both are tested against the same known pairs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

RGBA = tuple[float, float, float, float]  # sRGB channels 0..1, alpha 0..1

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_COMMA = re.compile(
    rf"^rgba?\(\s*({_NUM})(%?)\s*,\s*({_NUM})(%?)\s*,\s*({_NUM})(%?)\s*(?:,\s*({_NUM})(%?)\s*)?\)$", re.I)
_RGB_SPACE = re.compile(
    rf"^rgba?\(\s*({_NUM})(%?)\s+({_NUM})(%?)\s+({_NUM})(%?)\s*(?:/\s*({_NUM})(%?)\s*)?\)$", re.I)
_HSL = re.compile(
    rf"^hsla?\(\s*({_NUM})(?:deg)?\s*[,\s]\s*({_NUM})%\s*[,\s]\s*({_NUM})%\s*(?:[,/]\s*({_NUM})(%?)\s*)?\)$", re.I)
_OKLCH = re.compile(rf"^oklch\(\s*({_NUM})(%?)\s+({_NUM})\s+({_NUM})(?:deg)?\s*(?:/\s*({_NUM})(%?)\s*)?\)$", re.I)
_VAR = re.compile(r"^var\(--t-([a-z][a-z0-9-]{0,40})\)$")


class ColourError(ValueError):
    pass


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _alpha(raw: str | None, pct: str | None) -> float:
    if raw is None:
        return 1.0
    return _clamp(float(raw) / 100 if pct else float(raw))


def var_target(value: str) -> str | None:
    """The token a ``var(--t-<name>)`` value points at, else None."""
    m = _VAR.match(value.strip())
    return m.group(1) if m else None


def parse_literal(value: str) -> RGBA:
    """Parse a literal colour (not a ``var()``). Raises ColourError for anything else."""
    v = value.strip()
    if v.lower() == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if _HEX.match(v):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        chans = [int(h[i:i + 2], 16) / 255 for i in range(0, len(h), 2)]
        return (chans[0], chans[1], chans[2], chans[3] if len(chans) == 4 else 1.0)
    m = _RGB_COMMA.match(v) or _RGB_SPACE.match(v)
    if m:
        g = m.groups()
        rgb = [_clamp(float(g[i]) / 100 if g[i + 1] else float(g[i]) / 255) for i in (0, 2, 4)]
        return (rgb[0], rgb[1], rgb[2], _alpha(g[6], g[7]))
    m = _HSL.match(v)
    if m:
        h, s, light = float(m.group(1)) % 360, _clamp(float(m.group(2)) / 100), _clamp(float(m.group(3)) / 100)
        r, g_, b = _hsl_to_rgb(h, s, light)
        return (r, g_, b, _alpha(m.group(4), m.group(5)))
    m = _OKLCH.match(v)
    if m:
        lum = float(m.group(1)) / 100 if m.group(2) else float(m.group(1))
        r, g_, b = oklch_to_srgb(_clamp(lum), max(0.0, float(m.group(3))), float(m.group(4)))
        return (r, g_, b, _alpha(m.group(5), m.group(6)))
    raise ColourError(f"not a colour: {value!r}")


def is_colour(value: str, *, allow_var: bool = True) -> bool:
    if allow_var and var_target(value) is not None:
        return True
    try:
        parse_literal(value)
    except ColourError:
        return False
    return True


def resolve(value: str, tokens: Mapping[str, str], depth: int = 0) -> RGBA:
    """Parse a token value, following ``var(--t-x)`` through the mode map (at most 4 hops)."""
    target = var_target(value)
    if target is None:
        return parse_literal(value)
    if depth >= 4 or target not in tokens:
        raise ColourError(f"unresolvable reference {value!r}")
    return resolve(tokens[target], tokens, depth + 1)


def _hsl_to_rgb(h: float, s: float, light: float) -> tuple[float, float, float]:
    def f(n: float) -> float:
        k = (n + h / 30) % 12
        a = s * min(light, 1 - light)
        return light - a * max(-1, min(k - 3, 9 - k, 1))
    return f(0), f(8), f(4)


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def oklch_to_srgb(lum: float, chroma: float, hue: float) -> tuple[float, float, float]:
    """OKLCH to gamma-encoded sRGB, clamped to gamut."""
    a, b = chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue))
    l_ = lum + 0.3963377774 * a + 0.2158037573 * b
    m_ = lum - 0.1055613458 * a - 0.0638541728 * b
    s_ = lum - 0.0894841775 * a - 1.2914855480 * b
    lc, mc, sc = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc
    g = -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc
    bl = -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc
    return tuple(_clamp(_from_linear(_clamp(c))) for c in (r, g, bl))  # type: ignore[return-value]


def srgb_to_oklch(r: float, g: float, b: float) -> tuple[float, float, float]:
    lr, lg, lb = _to_linear(r), _to_linear(g), _to_linear(b)
    l_ = (0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb) ** (1 / 3)
    m_ = (0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb) ** (1 / 3)
    s_ = (0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb) ** (1 / 3)
    lum = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return lum, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def over(top: RGBA, under: RGBA) -> RGBA:
    """Composite ``top`` over ``under`` (source-over, straight alpha)."""
    a = top[3] + under[3] * (1 - top[3])
    if a == 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (*(  # type: ignore[return-value]
        (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a for i in range(3)), a)


def luminance(c: RGBA) -> float:
    return 0.2126 * _to_linear(c[0]) + 0.7152 * _to_linear(c[1]) + 0.0722 * _to_linear(c[2])


def contrast(fg: RGBA, bg: RGBA) -> float:
    """WCAG 2 contrast ratio. ``bg`` must be opaque; ``fg`` is composited over it."""
    top = over(fg, bg)
    la, lb = sorted((luminance(top), luminance(bg)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def to_hex(c: RGBA) -> str:
    return "#" + "".join(f"{round(_clamp(x) * 255):02X}" for x in c[:3])
