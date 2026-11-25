"""Stable ids for the built-in themes (UUIDv5, so every install agrees)."""

from __future__ import annotations

import uuid

THEME_NAMESPACE = uuid.UUID("6f1b8c2e-3a7d-5e10-9c4b-2d8f0a1e7b33")

BUILTIN_SLUGS: tuple[str, ...] = (
    "copperbelt",
    "midnight-ledger",
    "savanna-dusk",
    "paper",
    "workshop",
    "high-contrast",
)


def builtin_theme_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(THEME_NAMESPACE, f"builtin-theme:{slug}")
