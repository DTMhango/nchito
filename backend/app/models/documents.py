"""Rendered application documents (DESIGN.md 9, 18.2). One row per (application, kind, format, render input)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity


class ApplicationDocument(Base, Entity):
    """A stored file rendered from an application's spec.

    ``input_hash`` covers everything the file depends on (spec content, the person's header,
    the experience rows, the resolved template and the renderer version), so rendering the same
    input again finds this row instead of creating another. ``spec_hash`` names the spec the file
    came from; ``content_hash`` is the sha256 of the stored bytes (what a packet binds to).
    Rows are never updated: a new spec or template makes a new row.
    """

    __tablename__ = "application_document"
    __table_args__ = (
        UniqueConstraint("application_id", "kind", "fmt", "input_hash", name="application_kind_fmt_input"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, doc="cv or letter")
    fmt: Mapped[str] = mapped_column(String(10), nullable=False, doc="pdf, docx, txt or html")
    template_key: Mapped[str] = mapped_column(String(60), nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False, doc="sha256 of the canonical spec JSON")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, doc="sha256 of the stored file")
    file_key: Mapped[str] = mapped_column(String(300), nullable=False, doc="FileStore key")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list,
                                                           server_default="[]")
