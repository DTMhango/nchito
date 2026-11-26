"""Connections (LLM providers, mailboxes, storage, chat), model routing tests, runner tokens. Waves 1-2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Timestamps, not_implemented
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.llm import checks, provider_records
from app.llm.deps import llm_service
from app.llm.money import micros_to_minor
from app.llm.service import LLMService
from app.models.platform import Connection

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
    cost_micros: int = 0


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


def _out(conn: Connection) -> ConnectionOut:
    return ConnectionOut(id=conn.id, created_at=conn.created_at, updated_at=conn.updated_at,
                         provider=conn.provider.value, label=conn.label, config=dict(conn.config),
                         secrets_masked=provider_records.masked_secrets(conn), scopes_granted=list(conn.scopes_granted),
                         reads_description=conn.reads_description,
                         health=conn.health if conn.health in ("ok", "failing") else "unknown",
                         last_checked_at=conn.last_checked_at, enabled=conn.enabled)


async def _get_llm(session: AsyncSession, connection_id: uuid.UUID) -> Connection:
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="connection not found")
    if not provider_records.is_llm(conn.provider.value):
        not_implemented(2, "connect")
    return conn


@connections_router.get("", response_model=list[ConnectionOut], name="connections_list")
async def list_connections(session: SessionDep) -> list[ConnectionOut]:
    rows = await session.scalars(select(Connection).order_by(Connection.provider, Connection.created_at))
    return [_out(c) for c in rows.all()]


@connections_router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED,
                         name="connections_create")
async def create_connection(body: ConnectionCreate, session: SessionDep, principal: PrincipalDep) -> ConnectionOut:
    """LLM providers (wave 1). Keys are encrypted at rest and only ever returned masked."""
    if not provider_records.is_llm(body.provider):
        not_implemented(2, "connect")
    try:
        conn = await provider_records.create(session, provider=body.provider, label=body.label, config=body.config,
                                             secrets=body.secrets, actor=principal.actor)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await session.refresh(conn)
    return _out(conn)


@connections_router.put("/{connection_id}", response_model=ConnectionOut, name="connections_update")
async def update_connection(connection_id: uuid.UUID, body: ConnectionUpdate, session: SessionDep,
                            principal: PrincipalDep) -> ConnectionOut:
    """Omitted fields stay; a blank secret value keeps the stored one."""
    conn = await _get_llm(session, connection_id)
    try:
        await provider_records.update(session, conn, label=body.label, config=body.config, secrets=body.secrets,
                                      enabled=body.enabled, actor=principal.actor)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await session.refresh(conn)
    return _out(conn)


@connections_router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT,
                           response_class=Response, name="connections_delete")
async def delete_connection(connection_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> None:
    conn = await _get_llm(session, connection_id)
    await audit.record(session, actor=principal.actor, action="connection.deleted", subject_type="connection",
                       subject_id=conn.id, detail={"provider": conn.provider.value, "label": conn.label})
    await session.delete(conn)


@connections_router.post("/{connection_id}/test", response_model=ConnectionTestOut, name="connections_test")
async def test_connection(connection_id: uuid.UUID, session: SessionDep, principal: PrincipalDep,
                          service: Annotated[LLMService, Depends(llm_service)]) -> ConnectionTestOut:
    """One tiny budgeted request with this provider record (model: config ``test_model`` or the extract model)."""
    conn = await _get_llm(session, connection_id)
    result = await checks.run_test(service, stage="extract", model=conn.config.get("test_model"),
                                   provider=conn.provider.value, credentials=provider_records.credentials_of(conn))
    await checks.record(session, result, actor=principal.actor)
    conn.health = "ok" if result.ok else "failing"
    conn.last_checked_at = utcnow()
    return ConnectionTestOut(ok=result.ok, detail=result.detail, cost_minor=micros_to_minor(result.cost_micros),
                             cost_micros=result.cost_micros)


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
