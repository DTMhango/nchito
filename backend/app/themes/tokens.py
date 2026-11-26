"""The token spec (``token_spec.json``, a verbatim copy of ``frontend/src/themes/token-spec.json``):
every token's group, value type and contrast use, the bundled font families and the WCAG levels.

Every theme value is checked against a strict grammar for its type, so a stored theme can only
ever hold colours, lengths, numbers and enumerated words: never arbitrary CSS, URLs or script.
The contrast pairs are derived from the spec (``use`` + ``on``), not listed by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from app.themes.colour import ColourError, contrast, is_colour, over, parse_literal, resolve, var_target

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_LENGTH = re.compile(rf"^({_NUM})(px)?$")
_TRACK = re.compile(rf"^({_NUM})em$")
_FACTOR = re.compile(rf"^({_NUM})$")
_WEIGHT = re.compile(r"^[1-9]\d{2}$")
_SHADOW_LEN = re.compile(rf"^{_NUM}(?:px|em|rem)?$")
TOKEN_NAME = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@lru_cache
def spec() -> dict[str, Any]:
    return json.loads(resources.files("app.themes").joinpath("token_spec.json").read_text(encoding="utf-8"))


def token_specs() -> dict[str, dict[str, Any]]:
    return spec()["tokens"]


def required_tokens() -> tuple[str, ...]:
    return tuple(k for k, v in token_specs().items() if v.get("required"))


def colour_token_names() -> frozenset[str]:
    return frozenset(k for k, v in token_specs().items() if v["type"] == "colour")


def font_families() -> tuple[str, ...]:
    return tuple(spec()["fonts"])


def limits() -> dict[str, int]:
    return spec()["limits"]


def _in_range(raw: str, lo: float, hi: float) -> bool:
    try:
        x = float(raw)
    except ValueError:
        return False
    return lo <= x <= hi


def _is_ref_ok(value: str) -> bool:
    """``var(--t-x)`` may only point at a known colour token: no fallbacks, no other properties."""
    target = var_target(value)
    return target is not None and target in colour_token_names()


def valid_colour(value: str) -> bool:
    if "var(" in value:
        return _is_ref_ok(value)
    return is_colour(value, allow_var=False)


def valid_shadow(value: str) -> bool:
    v = value.strip()
    if v == "none":
        return True
    layers = _split_layers(v)
    if not layers or len(layers) > 4:
        return False
    for layer in layers:
        parts = layer.split()
        if parts and parts[0] == "inset":
            parts = parts[1:]
        if not parts:
            return False
        lengths, colour_parts = [], []
        for i, p in enumerate(parts):
            if _SHADOW_LEN.match(p) and not colour_parts:
                lengths.append(p)
            else:
                colour_parts = parts[i:]
                break
        if not 2 <= len(lengths) <= 4 or not colour_parts:
            return False
        if not valid_colour(" ".join(colour_parts)):
            return False
    return True


def _split_layers(value: str) -> list[str]:
    """Split a shadow list on top-level commas (colour functions contain commas too)."""
    out, depth, cur = [], 0, ""
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return []
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return [x for x in out if x]


def valid_value(name: str, value: Any) -> bool:
    """Is ``value`` allowed for token ``name``? Unknown token names accept a colour or a plain length."""
    if not isinstance(value, str) or not value.strip() or len(value) > limits()["value_length"]:
        return False
    if _CONTROL.search(value):
        return False
    v = value.strip()
    s = token_specs().get(name)
    if s is None:
        return valid_colour(v) or bool(_LENGTH.match(v))
    kind = s["type"]
    if kind == "colour":
        return valid_colour(v)
    if kind == "shadow":
        return valid_shadow(v)
    if kind == "enum":
        return v in s["values"]
    if kind == "weight":
        return bool(_WEIGHT.match(v)) and _in_range(v, s["min"], s["max"])
    if kind == "track":
        m = _TRACK.match(v)
        return bool(m) and _in_range(m.group(1), s["min"], s["max"])
    if kind == "factor":
        return bool(_FACTOR.match(v)) and _in_range(v, s["min"], s["max"])
    if kind == "length":
        m = _LENGTH.match(v)
        return bool(m) and _in_range(m.group(1), s["min"], s["max"])
    return False


def check_mode_map(tokens: Any, mode: str) -> dict[str, str]:
    if not isinstance(tokens, dict):
        raise ValueError(f"{mode}: must be an object of tokens")
    if len(tokens) > limits()["tokens_per_mode"]:
        raise ValueError(f"{mode}: too many tokens")
    missing = set(required_tokens()) - tokens.keys()
    if missing:
        raise ValueError(f"{mode}: missing tokens {sorted(missing)}")
    for name, value in tokens.items():
        if not isinstance(name, str) or not TOKEN_NAME.match(name):
            raise ValueError(f"{mode}: invalid token name {name!r}")
        if not valid_value(name, value):
            raise ValueError(f"{mode}: value not allowed for {name!r}")
    for name, value in tokens.items():
        if var_target(value) is not None:
            try:
                resolve(value, {**_STYLE_COLOUR_DEFAULTS, **tokens})
            except ColourError as exc:
                raise ValueError(f"{mode}: {name!r} refers to a token that does not resolve") from exc
    return tokens


def check_plain_text(value: str) -> str:
    if _CONTROL.search(value):
        raise ValueError("control characters are not allowed")
    return value


# The engine's defaults for optional colour tokens that may be referenced (frontend STYLE_TOKEN_DEFAULTS).
_STYLE_COLOUR_DEFAULTS = {"panel-border": "var(--t-border)", "elev-top-color": "var(--t-panel-border)"}


# ---- contrast ----

@dataclass(frozen=True)
class PairResult:
    mode: str
    fg: str
    bg: str
    use: str
    ratio: float
    aa: bool
    aaa: bool | None
    blocking: bool  # below AA where the level blocks


def contrast_pairs() -> list[tuple[str, str, str]]:
    """(fg, bg, use) for every pair the spec declares; ``@ground`` expands to the ground tokens."""
    specs = token_specs()
    grounds = [k for k, v in specs.items() if v.get("ground")]
    pairs: list[tuple[str, str, str]] = []
    for name, s in specs.items():
        if "use" not in s:
            continue
        for target in s.get("on", []):
            for bg in grounds if target == "@ground" else [target]:
                pairs.append((name, bg, s["use"]))
    return pairs


def evaluate_contrast(tokens: dict[str, str], mode: str, chart: list[str] | None = None,
                      score: dict[str, str] | None = None) -> list[PairResult]:
    levels = spec()["levels"]
    env: dict[str, str] = dict(_STYLE_COLOUR_DEFAULTS)
    for i, c in enumerate((chart or [])[:5]):
        env[f"chart-{i + 1}"] = c
    for k, v in (score or {}).items():
        env[f"score-{k}"] = v
    env.update(tokens)
    page_base = parse_literal("#FFFFFF" if mode == "light" else "#000000")
    out: list[PairResult] = []
    for fg, bg, use in contrast_pairs():
        if fg not in env or bg not in env:
            continue
        try:
            page = over(resolve(env["bg"], env), page_base)
            ground = over(resolve(env[bg], env), page)
            ratio = contrast(resolve(env[fg], env), ground)
        except ColourError:
            continue
        lvl = levels[use]
        aa = ratio >= lvl["aa"]
        aaa = None if lvl["aaa"] is None else ratio >= lvl["aaa"]
        out.append(PairResult(mode, fg, bg, use, round(ratio, 2), aa, aaa, bool(lvl["blocking"]) and not aa))
    return out
