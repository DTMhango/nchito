"""Preference feedback and the rubric suggestions drawn from it (DESIGN.md 15 wave 4, F17).

Feedback is evidence only: nothing here changes a score. Suggestions are reviewable proposals; the
owner accepts (a new rubric version or a new rule/tag/view, audited), edits or dismisses them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity, PydanticJSON
from app.schemas.json_types import SuggestionBacktest, SuggestionChange, SuggestionEvidence

CHANGE_ADAPTER: TypeAdapter[Any] = TypeAdapter(SuggestionChange)


class PreferenceFeedback(Base, Entity):
    """The owner's thumbs on one match (job + campaign). One current row per pair; changes are audited."""

    __tablename__ = "preference_feedback"
    __table_args__ = (UniqueConstraint("job_id", "campaign_id", name="feedback_job_campaign"),
                      Index("ix_preference_feedback_campaign", "campaign_id"))

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(String(10), nullable=False, doc="up / down")
    reasons: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text, doc="The owner's words; data, never an instruction")
    score_at: Mapped[int | None] = mapped_column(Integer, doc="Effective score when the feedback was given")
    rubric_version: Mapped[int | None] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)


class PreferenceSuggestion(Base, Entity):
    """A concrete rubric/rule change proposed from feedback and outcomes, with its evidence and backtest."""

    __tablename__ = "preference_suggestion"
    __table_args__ = (UniqueConstraint("campaign_id", "evidence_key", name="suggestion_campaign_evidence"),
                      Index("ix_preference_suggestion_status", "campaign_id", "status"))

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(String(200), nullable=False, doc="What it is about, e.g. a facet value")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    change: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, doc="A SuggestionChange")
    evidence: Mapped[SuggestionEvidence] = mapped_column(PydanticJSON(SuggestionEvidence), nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False,
                                              doc="Hash of kind, target and evidence ids: never re-raised")
    backtest: Mapped[SuggestionBacktest | None] = mapped_column(PydanticJSON(SuggestionBacktest))
    rubric_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rubric.id", ondelete="SET NULL"),
                                                        doc="The rubric version the suggestion was drawn against")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                   doc="What accepting created (rubric version, rule, tag, view)")
