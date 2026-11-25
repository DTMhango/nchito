"""Declarative base, common columns and column types.

Every table: UUID ``id``, ``created_at``, ``updated_at`` (UTC). Money is integer minor units
plus an ISO currency. JSON columns are JSONB validated by a Pydantic shape.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import DateTime, Enum, MetaData, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Entity(IdMixin, TimestampMixin):
    """Mixin for ordinary tables."""


class PydanticJSON(TypeDecorator[Any]):
    """JSONB validated by a Pydantic type on write; loads back as that type."""

    impl = JSONB
    cache_ok = True

    def __init__(self, shape: Any) -> None:
        super().__init__()
        self.shape = shape
        self._adapter: TypeAdapter[Any] = TypeAdapter(shape)

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self._adapter.dump_python(self._adapter.validate_python(value), mode="json")

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self._adapter.validate_python(value)

    def __repr__(self) -> str:
        return "JSONB()"


def str_enum(cls: type[enum.Enum], name: str | None = None) -> Enum:
    """Store a Python enum as a short varchar with a CHECK constraint (no native PG enum)."""
    return Enum(
        cls,
        name=name or cls.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        length=40,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def money_currency() -> Mapped[str | None]:
    return mapped_column(String(3), nullable=True)


class ReviewState(enum.StrEnum):
    needs_review = "needs_review"
    confirmed = "confirmed"


class Origin(enum.StrEnum):
    imported = "import"
    owner = "owner"
    system = "system"
