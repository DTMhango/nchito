"""Pending actions: the "Needs you" list and the Action centre. Wave 2 (apply stream); listing in wave 1."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Page, Timestamps, not_implemented
from app.api.deps import RequireOwner
from app.schemas.json_types import AgentTaskState

router = APIRouter(prefix="/api/pending-actions", tags=["pending_actions"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)

PendingType = Literal["approve", "sign_in", "create_account", "captcha", "unknown_question", "assessment",
                      "declaration", "confirm_submission", "review_import", "conflict_choice", "answer_review_due"]


class PendingActionOut(Timestamps):
    type: PendingType
    application_id: uuid.UUID | None
    agent_task_id: uuid.UUID | None
    group_key: str | None
    title: str
    detail: dict[str, Any]
    checkpoint: AgentTaskState | None
    deadline: datetime | None
    status: Literal["open", "resolved", "dismissed", "expired"]


class DecisionGroup(BaseModel):
    """Shared blockers grouped on Today (18.4): 'signing in here unlocks two applications'."""

    group_key: str
    title: str
    consequence: str
    nearest_deadline: datetime | None
    actions: list[PendingActionOut]


class ResolveIn(BaseModel):
    resolution: Literal["continue", "answered", "approved", "confirmed", "dismissed", "chosen"]
    answer_value: str | None = None
    answer_scope: Literal["this_application", "this_employer", "this_country", "all_matching"] | None = Field(
        default=None, description="Default from answers.routine_default_scope / material_default_scope")
    chosen_application_id: uuid.UUID | None = None
    note: str | None = None


@router.get("", response_model=Page[PendingActionOut], name="pending_actions_list")
async def list_pending(status: Literal["open", "resolved", "dismissed", "expired"] = "open",
                       type: PendingType | None = None, cursor: str | None = None) -> Page[PendingActionOut]:
    not_implemented(1, "today")


@router.get("/decisions", response_model=list[DecisionGroup], name="pending_actions_decisions")
async def decisions() -> list[DecisionGroup]:
    not_implemented(1, "today")


@router.get("/{action_id}", response_model=PendingActionOut, name="pending_actions_get")
async def get_pending(action_id: uuid.UUID) -> PendingActionOut:
    not_implemented(1, "today")


@router.post("/{action_id}/resolve", response_model=PendingActionOut, name="pending_actions_resolve")
async def resolve(action_id: uuid.UUID, body: ResolveIn) -> PendingActionOut:
    """'I've signed in, continue' returns the task to the same runner (8.4)."""
    not_implemented(2, "apply")
