"""Connections (LLM providers, mailboxes, storage, chat), model routing tests, runner tokens. Waves 1-2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Timestamps, not_implemented
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.connect import mail_connections
from app.connect import records as ops_records
from app.connect.mailbox import MailError
from app.core import audit
from app.core.clock import utcnow
from app.core.crypto import mask
from app.gateway import auth as gateway_auth
from app.llm import checks, provider_records
from app.llm.deps import llm_service
from app.llm.money import micros_to_minor
from app.llm.service import LLMService
from app.models.platform import ApiToken, Connection

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
                         secrets_masked=_masked(conn), scopes_granted=list(conn.scopes_granted),
                         reads_description=conn.reads_description,
                         health=conn.health if conn.health in ("ok", "failing") else "unknown",
                         last_checked_at=conn.last_checked_at, enabled=conn.enabled)


def _masked(conn: Connection) -> dict[str, str]:
    if conn.provider.value == "gdrive":  # OAuth tokens: a nested record, never shown
        return {"tokens": mask("x" * 8)} if conn.secrets_enc else {}
    return provider_records.masked_secrets(conn)


async def _get_llm(session: AsyncSession, connection_id: uuid.UUID) -> Connection:
    """A record this build manages: an LLM provider, a mailbox, or a Drive, Telegram or webhook record."""
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="connection not found")
    if not (provider_records.is_llm(conn.provider.value) or mail_connections.is_mail(conn.provider.value)
            or ops_records.is_ops(conn.provider.value)):
        not_implemented(2, "connect")
    return conn


@connections_router.get("", response_model=list[ConnectionOut], name="connections_list")
async def list_connections(session: SessionDep) -> list[ConnectionOut]:
    rows = await session.scalars(select(Connection).order_by(Connection.provider, Connection.created_at))
    return [_out(c) for c in rows.all()]


@connections_router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED,
                         name="connections_create")
async def create_connection(body: ConnectionCreate, session: SessionDep, principal: PrincipalDep) -> ConnectionOut:
    """LLM providers, IMAP/SMTP mailboxes (Gmail connects through OAuth), Telegram and webhook records. Secrets are
    encrypted at rest and only ever returned masked."""
    if ops_records.is_ops(body.provider):
        try:
            conn = await ops_records.create(session, provider=body.provider, label=body.label, config=body.config,
                                            secrets_in=body.secrets, actor=principal.actor)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        await session.refresh(conn)
        return _out(conn)
    is_mail = mail_connections.is_mail(body.provider)
    if not (provider_records.is_llm(body.provider) or is_mail):
        not_implemented(2, "connect")
    creator = mail_connections.create if is_mail else provider_records.create
    try:
        conn = await creator(session, provider=body.provider, label=body.label, config=body.config,
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
    if ops_records.is_ops(conn.provider.value):
        try:
            await ops_records.update(session, conn, label=body.label, config=body.config, secrets_in=body.secrets,
                                     enabled=body.enabled, actor=principal.actor)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        await session.refresh(conn)
        return _out(conn)
    updater = mail_connections.update if mail_connections.is_mail(conn.provider.value) else provider_records.update
    try:
        await updater(session, conn, label=body.label, config=body.config, secrets=body.secrets,
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
    if ops_records.is_ops(conn.provider.value):
        ok, detail = await ops_records.run_test(session, conn)
        return ConnectionTestOut(ok=ok, detail=detail)
    if mail_connections.is_mail(conn.provider.value):
        ok, detail = await mail_connections.test(conn)
        conn.health = "ok" if ok else "failing"
        conn.last_checked_at = utcnow()
        await audit.record(session, actor=principal.actor, action="connection.tested", subject_type="connection",
                           subject_id=conn.id, detail={"provider": conn.provider.value, "ok": ok})
        return ConnectionTestOut(ok=ok, detail=detail)
    result = await checks.run_test(service, stage="extract", model=conn.config.get("test_model"),
                                   provider=conn.provider.value, credentials=provider_records.credentials_of(conn))
    await checks.record(session, result, actor=principal.actor)
    conn.health = "ok" if result.ok else "failing"
    conn.last_checked_at = utcnow()
    return ConnectionTestOut(ok=result.ok, detail=result.detail, cost_minor=micros_to_minor(result.cost_micros),
                             cost_micros=result.cost_micros)


@connections_router.post("/oauth/{provider}/start", response_model=OAuthStartOut, name="connections_oauth_start")
async def oauth_start(provider: Literal["gmail", "gdrive", "msgraph", "onedrive"]) -> OAuthStartOut:
    try:
        if provider == "gdrive":
            return OAuthStartOut(authorize_url=ops_records.oauth_start_url())
        if provider == "gmail":
            return OAuthStartOut(authorize_url=mail_connections.oauth_start())
    except (ops_records.OAuthNotConfigured, MailError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    not_implemented(2, "connect")


@connections_router.get("/oauth/{provider}/callback", name="connections_oauth_callback",
                        responses={307: {"description": "Back to the Connections screen"}})
async def oauth_callback(provider: Literal["gmail", "gdrive", "msgraph", "onedrive"], code: str, state: str,
                         session: SessionDep, principal: PrincipalDep) -> Response:
    if provider == "gdrive":
        if not ops_records.check_state(state):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="the sign-in link expired; start again")
        try:
            await ops_records.oauth_finish(session, code=code, actor=principal.actor)
        except (ops_records.OAuthNotConfigured, ops_records.gdrive.DriveError) as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        return RedirectResponse("/settings/connections?connected=gdrive",
                                status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    if provider == "gmail":
        try:
            await mail_connections.oauth_callback(session, code=code, state=state, actor=principal.actor)
        except MailError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return RedirectResponse("/settings/connections?connected=gmail",
                                status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    not_implemented(2, "connect")


def _token_out(t: ApiToken) -> TokenOut:
    return TokenOut(id=t.id, created_at=t.created_at, updated_at=t.updated_at, name=t.name, prefix=t.prefix,
                    scopes=list(t.scopes), runner_kind=t.runner_kind,  # type: ignore[arg-type]
                    last_used_at=t.last_used_at, revoked_at=t.revoked_at, suspended_at=t.suspended_at,
                    suspended_reason=t.suspended_reason)


async def _token(session: AsyncSession, token_id: uuid.UUID) -> ApiToken:
    token = await session.get(ApiToken, token_id, with_for_update=True)
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="token not found")
    return token


@tokens_router.get("", response_model=list[TokenOut], name="tokens_list")
async def list_tokens(session: SessionDep) -> list[TokenOut]:
    rows = await session.scalars(select(ApiToken).order_by(ApiToken.revoked_at.is_not(None), ApiToken.created_at))
    return [_token_out(t) for t in rows.all()]


@tokens_router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED, name="tokens_create")
async def create_token(body: TokenCreate, session: SessionDep, principal: PrincipalDep) -> TokenCreated:
    """A runner token: one runner identity of a declared kind. The token itself is shown only in this reply."""
    try:
        made = await gateway_auth.create(session, name=body.name, runner_kind=body.runner_kind,
                                         scopes=list(body.scopes), by=principal.actor)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await session.refresh(made.row)
    return TokenCreated(**_token_out(made.row).model_dump(), token=made.secret)


@tokens_router.post("/{token_id}/revoke", response_model=TokenOut, name="tokens_revoke")
async def revoke_token(token_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> TokenOut:
    """Revoke at once: the token is refused from now on and the tasks it held go back to the queue."""
    token = await _token(session, token_id)
    await gateway_auth.revoke(session, token, by=principal.actor, now=utcnow())
    await session.refresh(token)
    return _token_out(token)


@tokens_router.post("/{token_id}/reinstate", response_model=TokenOut, name="tokens_reinstate")
async def reinstate_token(token_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> TokenOut:
    """Lift a suspension (after a submission without a permit was detected)."""
    token = await _token(session, token_id)
    try:
        await gateway_auth.reinstate(session, token, by=principal.actor)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.refresh(token)
    return _token_out(token)


@tokens_router.get("/runners", response_model=list[RunnerStatus], name="tokens_runner_status")
async def runner_status(session: SessionDep) -> list[RunnerStatus]:
    """Each live runner: last seen (its last gateway call), online within ``runners.stale_after_minutes``,
    and the task it holds."""
    from datetime import timedelta

    from app.core.settings import service as settings_service
    from app.models.applications import AgentTask, AgentTaskStatus

    stale = int(await settings_service.get_value(session, "runners.stale_after_minutes"))
    now = utcnow()
    out = []
    for t in (await session.scalars(select(ApiToken).where(ApiToken.revoked_at.is_(None))
                                    .order_by(ApiToken.created_at))).all():
        current = await session.scalar(select(AgentTask.id).where(
            AgentTask.claimed_by_token_id == t.id, AgentTask.status == AgentTaskStatus.claimed)
            .order_by(AgentTask.claimed_at).limit(1))
        seen = t.last_used_at
        out.append(RunnerStatus(token_id=t.id, name=t.name, runner_kind=t.runner_kind,  # type: ignore[arg-type]
                                last_seen_at=seen, online=bool(seen and seen > now - timedelta(minutes=stale)
                                                                and t.suspended_at is None),
                                current_task_id=current))
    return out
