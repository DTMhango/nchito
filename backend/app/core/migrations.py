"""Alembic hooks shared by ``migrations/env.py`` and the migration tests."""

from __future__ import annotations

from typing import Any

from app.models.base import PydanticJSON


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    """The queue tables belong to Procrastinate, not to our models."""
    if type_ == "table" and name and name.startswith("procrastinate"):
        return False
    table = getattr(obj, "table", None)
    return not (table is not None and str(table.name).startswith("procrastinate"))


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Render validated JSON columns as plain JSONB in generated migrations."""
    if type_ == "type" and isinstance(obj, PydanticJSON):
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "postgresql.JSONB(astext_type=sa.Text())"
    return False
