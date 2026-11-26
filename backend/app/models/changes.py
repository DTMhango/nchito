"""Posting change tracking (DESIGN.md 18.4): the versions of a job we have seen, the field-level changes
between them, and when each watched job was last scanned. Written by ``app.pipeline.changes``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity


class JobVersion(Base, Entity):
    """The fields of a job that matter for change detection, as they were at ``captured_at``.
    The posting text itself is not stored (only its digest); the structured fields are."""

    __tablename__ = "job_version"
    __table_args__ = (UniqueConstraint("job_id", "snapshot_digest", name="job_snapshot"),)

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, doc="The job's content hash then")
    snapshot_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobChange(Base, Entity):
    """One detected change of a posting: ``changes`` is the field-level list (kind, field, before, after,
    material). ``material`` changes reassess the role and flag an approved packet; wording does not."""

    __tablename__ = "job_change"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True)
    from_hash: Mapped[str | None] = mapped_column(String(64))
    to_hash: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="recheck")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    effects: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        doc="What it did: invalidated packet ids, pending action ids, application ids touched")


class JobWatch(Base, Entity):
    """When a watched job was last scanned, and what came of it (``unknown`` when the fetch failed)."""

    __tablename__ = "job_watch"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), nullable=False, unique=True)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_result: Mapped[str] = mapped_column(String(20), nullable=False, default="unchanged",
                                             doc="unchanged, changed, closed or unknown")
    note: Mapped[str | None] = mapped_column(Text)
