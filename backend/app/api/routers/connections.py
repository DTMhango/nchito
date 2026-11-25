"""Connections (LLM providers, mailboxes, storage, chat), model routing tests, runner tokens. Waves 1-2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Timestamps, not_implemented
from app.api.deps import RequireOwner

connections_router = APIRouter(prefix="/api/connections", tags=["connections"], dependencies=[RequireOwner],
                               responses=NOT_IMPLEMENTED_RESPONSES)
tokens_router = APIRouter(prefix="/api/tokens", tags=["tokens"], dependencies=[RequireOwner],
                          responses=NOT_IMPLEMENTED_RESPONSES)

ProviderT = Literal["anthropic", "openai_compatible", "gmail", "imap_smtp", "gdrive", "msgraph", "onedrive",
                    "telegram", "webhook", "s3"]


class ConnectionOut(Timestamps):
    provider: ProviderT
    label: str
    config: dict[str, Any] = Field(description="Non-secret settings only")
    secrets_masked: dict[str, str] = Field(description="Secrets shown masked, never in full")
    scopes_granted: list[str]
    reads_description: str | None = Field(description="What the app actually reads (18.5)")
    health: Literal["ok", "failing", "unknown"]
    last_checked_at: datetime | None
    enabled: bool


class ConnectionCreate(BaseModel):
    provider: ProviderT
    label: str
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict, description="Encrypted at rest; never returned")


class ConnectionUpdate(BaseModel):
    label: str | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    enabled: bool | None = None


class ConnectionTestOut(BaseModel):
    ok: bool
    detail: str | None = None
    cost_minor: int = 0


class OAuthStartOut(BaseModel):
    authorize_url: str


class TokenOut(Timestamps):
    name: str
    prefix: str
    scopes: list[str]
    runner_kind: Literal["pc", "server"]
    last_used_at: datetime | None
    revoked_at: datetime | None
    suspended_at: datetime | None
    suspended_reason: str | None


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    runner_kind: Literal["pc", "server"] = "pc"
    scopes: list[Literal["gateway:tasks", "gateway:packets", "gateway:permits", "gateway:sweep"]] = Field(
        default_factory=lambda: ["gateway:tasks", "gateway:packets", "gateway:permits"])


class TokenCreated(TokenOut):
    token: str = Field(description="Shown once")


class RunnerStatus(BaseModel):
    token_id: uuid.UUID
    name: str
    runner_kind: Literal["pc", "server"]
    last_seen_at: datetime | None
    online: bool
    current_task_id: uuid.UUID | None


@connections_router.get("", response_model=list[ConnectionOut], name="connections_list")
async def list_connections() -> list[ConnectionOut]:
    not_implemented(1, "llm")


@connections_router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED,
                         name="connections_create")
async def create_connection(body: ConnectionCreate) -> ConnectionOut:
    not_implemented(1, "llm")


@connections_router.put("/{connection_id}", response_model=ConnectionOut, name="connections_update")
async def update_connection(connection_id: uuid.UUID, body: ConnectionUpdate) -> ConnectionOut:
    not_implemented(1, "llm")


@connections_router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT,
                           response_class=Response, name="connections_delete")
async def delete_connection(connection_id: uuid.UUID) -> None:
    not_implemented(1, "llm")


@connections_router.post("/{connection_id}/test", response_model=ConnectionTestOut, name="connections_test")
async def test_connection(connection_id: uuid.UUID) -> ConnectionTestOut:
    not_implemented(1, "llm")


@connections_router.post("/oauth/{provider}/start", response_model=OAuthStartOut, name="connections_oauth_start")
async def oauth_start(provider: Literal["gmail", "gdrive", "msgraph", "onedrive"]) -> OAuthStartOut:
    not_implemented(2, "connect")


@connections_router.get("/oauth/{provider}/callback", name="connections_oauth_callback",
                        responses={307: {"description": "Back to the Connections screen"}})
async def oauth_callback(provider: Literal["gmail", "gdrive", "msgraph", "onedrive"], code: str,
                         state: str) -> None:
    not_implemented(2, "connect")


@tokens_router.get("", response_model=list[TokenOut], name="tokens_list")
async def list_tokens() -> list[TokenOut]:
    not_implemented(3, "gateway")


@tokens_router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED, name="tokens_create")
async def create_token(body: TokenCreate) -> TokenCreated:
    not_implemented(3, "gateway")


@tokens_router.post("/{token_id}/revoke", response_model=TokenOut, name="tokens_revoke")
async def revoke_token(token_id: uuid.UUID) -> TokenOut:
    not_implemented(3, "gateway")


@tokens_router.post("/{token_id}/reinstate", response_model=TokenOut, name="tokens_reinstate")
async def reinstate_token(token_id: uuid.UUID) -> TokenOut:
    """Lift a suspension (after a submission without a permit was detected)."""
    not_implemented(3, "gateway")


@tokens_router.get("/runners", response_model=list[RunnerStatus], name="tokens_runner_status")
async def runner_status() -> list[RunnerStatus]:
    not_implemented(3, "gateway")
