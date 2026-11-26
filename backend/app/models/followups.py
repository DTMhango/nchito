"""Follow-ups, outbound messages and the wind-down (DESIGN.md 8.2, 18.2, 18.4; wave 4).

A message about an existing application is drafted here and sent as a *message packet*: an
``application_packet`` row whose contents carry ``message_kind``. Approval, the single-use permit and the
dispatch attempt are the same rows and code paths as the application's own packet. What was sent is never
stored here: the send state is read from the dispatch attempts of the message's packet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity, PydanticJSON
from app.schemas.json_types import CheckResult, SpecItem


class OutboundMessage(Base, Entity):
    """A drafted message (follow-up, thank-you, reply, slot answer, withdrawal, offer decline)."""

    __tablename__ = "outbound_message"
    __table_args__ = (Index("ix_outbound_message_app", "application_id", "created_at"),)

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False, doc="MessageKind")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", doc="MessageStatus")
    thread_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mail_thread.id", ondelete="SET NULL"))
    thread_ref: Mapped[str | None] = mapped_column(String(300), doc="Provider thread (or Message-ID) replied in")
    to: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    known_recipients: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, doc="Addresses the application went to or the employer wrote from")
    confirmed_recipients: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, doc="Other addresses the owner confirmed for this message")
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    paragraphs: Mapped[list[SpecItem]] = mapped_column(PydanticJSON(list[SpecItem]), nullable=False, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                    doc="Owner notes, slot, request excerpt, interview round")
    questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list,
                                                 doc="What the owner must decide before this can go")
    check_results: Mapped[list[CheckResult]] = mapped_column(PydanticJSON(list[CheckResult]), nullable=False,
                                                             default=list)
    checked_hash: Mapped[str | None] = mapped_column(String(64), doc="Content hash the checks ran on")
    packet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("application_packet.id", ondelete="SET NULL"))
    sequence: Mapped[int | None] = mapped_column(Integer, doc="Follow-up number (1 = first follow-up)")
    automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                            doc="Drafted by the automatic follow-up path")
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="generated", doc="generated or owner")
    model: Mapped[str | None] = mapped_column(String(128))
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="owner")


class FollowupDue(Base, Entity):
    """One follow-up due for one application (the n-th), with the owner's snooze or "not needed"."""

    __tablename__ = "followup_due"
    __table_args__ = (UniqueConstraint("application_id", "sequence", name="followup_due_sequence"),
                      Index("ix_followup_due_status", "status", "due_at"))

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, doc="Application stage when it fell due")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="due", doc="FollowupDueStatus")
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outbound_message.id", ondelete="SET NULL"))
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pending_action.id",
                                                                           ondelete="SET NULL"))
    decided_by: Mapped[str | None] = mapped_column(String(120))


class WindDown(Base, Entity):
    """"I've accepted an offer": the master pause, the owner's keep / pause / withdraw choices, and what to
    restore (paused, never deleted) when the search is reopened."""

    __tablename__ = "wind_down"

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", doc="active or reopened")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    started_by: Mapped[str] = mapped_column(String(120), nullable=False)
    accepted_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"))
    was_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                             doc="The master pause was already on before the wind-down")
    pause_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    choices: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, doc="item key -> {choice, at, by, effect, restore}")
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_by: Mapped[str | None] = mapped_column(String(120))
