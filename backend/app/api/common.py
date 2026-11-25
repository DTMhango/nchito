"""Shared API types and helpers.

Errors use FastAPI's shape: ``{"detail": ...}``. Endpoints whose logic belongs to a later
wave respond 501 with ``{"detail": {"code": "not_implemented", "wave": n, "area": ...}}``;
their request and response models are final and are the contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, NoReturn, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int | None = None
    next_cursor: str | None = Field(default=None, description="Opaque; pass back as ?cursor=")


class Timestamps(ApiModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class NotImplementedDetail(BaseModel):
    code: str = "not_implemented"
    wave: int
    area: str


class ErrorOut(BaseModel):
    detail: Any


NOT_IMPLEMENTED_RESPONSES: dict[int | str, dict[str, Any]] = {
    501: {"model": ErrorOut, "description": "Specified; implemented in a later wave"},
}


def not_implemented(wave: int, area: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=NotImplementedDetail(wave=wave, area=area).model_dump(),
    )


class Ok(BaseModel):
    ok: bool = True
