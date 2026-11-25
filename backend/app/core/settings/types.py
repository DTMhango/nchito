"""Setting definitions and value validators.

A setting is defined once in ``registry.py``. Its default lives only there. Each definition
carries an ``example``: a valid non-default value, used by the generated registry tests.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import TypeAdapter, ValidationError

SettingKind = Literal[
    "bool",
    "int",
    "float",
    "string",
    "enum",
    "time",
    "cron",
    "timezone",
    "currency",
    "color",
    "money_minor",
    "list",
    "uuid",
]


class SettingValueError(ValueError):
    """The value is not acceptable for this setting."""


Validator = Callable[[Any], None]


@dataclass(frozen=True)
class SettingDef:
    key: str
    kind: SettingKind
    group: str
    label: str
    description: str
    default: Any
    example: Any
    python_type: Any
    validators: tuple[Validator, ...] = ()
    choices: tuple[str, ...] | None = None
    nullable: bool = False
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    default_factory: Callable[[], Any] | None = None
    invalid_example: Any = None
    has_invalid_example: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def effective_default(self) -> Any:
        return self.default_factory() if self.default_factory is not None else self.default

    def coerce(self, value: Any) -> Any:
        """Validate and normalise ``value``; raise ``SettingValueError`` if it is not acceptable."""
        if value is None:
            if self.nullable:
                return None
            raise SettingValueError(f"{self.key}: a value is required")
        try:
            coerced = TypeAdapter(self.python_type).validate_python(value, strict=self.kind != "float")
        except ValidationError as exc:
            raise SettingValueError(f"{self.key}: {exc.errors()[0]['msg']}") from exc
        if self.choices is not None:
            items = coerced if isinstance(coerced, list) else [coerced]
            for item in items:
                if item not in self.choices:
                    raise SettingValueError(f"{self.key}: {item!r} is not one of {list(self.choices)}")
        if self.minimum is not None and coerced < self.minimum:
            raise SettingValueError(f"{self.key}: must be at least {self.minimum}")
        if self.maximum is not None and coerced > self.maximum:
            raise SettingValueError(f"{self.key}: must be at most {self.maximum}")
        for check in self.validators:
            check(coerced)
        return coerced


# ----- reusable validators ---------------------------------------------------------------

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{1,127}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _regex(pattern: re.Pattern[str], what: str) -> Validator:
    def check(value: Any) -> None:
        if not pattern.match(str(value)):
            raise SettingValueError(f"not a valid {what}: {value!r}")

    return check


time_of_day = _regex(_TIME_RE, "time (HH:MM)")
currency_code = _regex(_CURRENCY_RE, "ISO 4217 currency code")
hex_color = _regex(_COLOR_RE, "colour (#RRGGBB)")
model_name = _regex(_MODEL_RE, "model name")
slug = _regex(_SLUG_RE, "identifier")


def cron_expr(value: Any) -> None:
    if not isinstance(value, str) or not croniter.is_valid(value):
        raise SettingValueError(f"not a valid cron expression: {value!r}")


def timezone_name(value: Any) -> None:
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SettingValueError(f"unknown time zone: {value!r}") from exc


def non_empty(value: Any) -> None:
    if isinstance(value, str) and not value.strip():
        raise SettingValueError("must not be empty")


def max_length(limit: int) -> Validator:
    def check(value: Any) -> None:
        if isinstance(value, str) and len(value) > limit:
            raise SettingValueError(f"must be at most {limit} characters")

    return check


def unique_items(value: Sequence[Any]) -> None:
    if len(set(value)) != len(value):
        raise SettingValueError("items must be unique")
