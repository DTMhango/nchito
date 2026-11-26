"""Bulk operations (DESIGN 10.3) and per-employer overrides (7.1, 8.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity


class EmployerPolicy(Base, Entity):
    """The owner's overrides for one canonical employer.

    ``employer_key`` is the casefolded canonical employer. A row exists only once the owner sets
    something. ``cooldown_days`` overrides ``matching.employer_cooldown_days`` (and a watched
    employer's own); ``always_ask_first`` adds to the watched-employer flag; ``never_apply`` is a hard
    exclusion with a reason; ``cooldown_released_at`` ends the running cooldown early (applications
    that ended or were sent before it no longer count).
    """

    __tablename__ = "employer_policy"

    employer_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    cooldown_days: Mapped[int | None] = mapped_column(Integer)
    always_ask_first: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    never_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    never_reason: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    watched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text)
    cooldown_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_released_reason: Mapped[str | None] = mapped_column(Text)
    cooldown_released_by: Mapped[str | None] = mapped_column(String(120))


class BulkOperation(Base, Entity):
    """One bulk action over a selection: previewed, confirmed, run in the background, maybe undone."""

    __tablename__ = "bulk_operation"
    __table_args__ = (Index("ix_bulk_operation_status", "status"),)

    subject: Mapped[str] = mapped_column(String(20), nullable=False, doc="jobs or applications")
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                      doc="ids, or the view/filter it was resolved from")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="previewed",
                                        doc="previewed, queued, running, done, partial, failed, undone")
    selected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undo_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class BulkItem(Base, Entity):
    """One subject in an operation. ``planned`` is the preview's verdict; ``outcome`` what the run did."""

    __tablename__ = "bulk_item"
    __table_args__ = (UniqueConstraint("operation_id", "subject_id", name="bulk_item_subject"),
                      Index("ix_bulk_item_operation", "operation_id"))

    operation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bulk_operation.id", ondelete="CASCADE"))
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    planned: Mapped[str] = mapped_column(String(20), nullable=False, doc="change, unchanged or refused")
    planned_code: Mapped[str | None] = mapped_column(String(60))
    planned_reason: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="pending",
                                         doc="pending, changed, unchanged, refused, failed, undone, undo_skipped")
    code: Mapped[str | None] = mapped_column(String(60))
    reason: Mapped[str | None] = mapped_column(Text)
    undo: Mapped[dict[str, Any] | None] = mapped_column(JSONB, doc="before/after values, for reversible actions")
