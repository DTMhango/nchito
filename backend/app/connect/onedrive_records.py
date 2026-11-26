"""The OneDrive ``Connection`` record: Microsoft sign-in, encrypted tokens, the live ``FileStore``.

Tokens are Fernet-encrypted in ``Connection.secrets_enc`` (``{"tokens": {...}}``), returned only masked,
and never logged or audited (the audit lists secret *names*). Mirrors the Google Drive record.
"""

from __future__ import annotations

import json
import secrets
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import msgraph_auth, onedrive
from app.connect.http_transport import HttpTransport, get_transport
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.crypto import decrypt, encrypt
from app.models.platform import Connection, ConnectionProvider

STATE_SALT = "nchito-oauth-state-onedrive"
STATE_MAX_AGE_SECONDS = 600
NOT_SET_UP = "OneDrive sign-in is not set up: set MS_OAUTH_CLIENT_ID and MS_OAUTH_CLIENT_SECRET"


class OAuthNotConfigured(RuntimeError):
    pass


def redirect_uri() -> str:
    return f"{get_config().base_origin}/api/connections/oauth/onedrive/callback"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt=STATE_SALT)


def oauth_start_url() -> str:
    cfg = get_config()
    if not cfg.ms_oauth_client_id or not cfg.ms_oauth_client_secret:
        raise OAuthNotConfigured(NOT_SET_UP)
    state = _serializer().dumps({"p": "onedrive", "n": secrets.token_urlsafe(8)})
    return onedrive.authorize_url(tenant=cfg.ms_oauth_tenant, client_id=cfg.ms_oauth_client_id,
                                  redirect_uri=redirect_uri(), state=state)


def check_state(state: str) -> bool:
    try:
        raw = _serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)
    except BadSignature:
        return False
    return isinstance(raw, dict) and raw.get("p") == "onedrive"


async def _first(session: AsyncSession) -> Connection | None:
    return await session.scalar(select(Connection).where(
        Connection.provider == ConnectionProvider.onedrive, Connection.enabled.is_(True)
    ).order_by(Connection.created_at).limit(1))


async def oauth_finish(session: AsyncSession, *, code: str, actor: str,
                       transport: HttpTransport | None = None) -> Connection:
    cfg = get_config()
    if not cfg.ms_oauth_client_id or not cfg.ms_oauth_client_secret:
        raise OAuthNotConfigured(NOT_SET_UP)
    tokens = await onedrive.exchange_code(transport or get_transport(), tenant=cfg.ms_oauth_tenant,
                                          client_id=cfg.ms_oauth_client_id, client_secret=cfg.ms_oauth_client_secret,
                                          redirect_uri=redirect_uri(), code=code)
    scopes = list(msgraph_auth.ONEDRIVE_SCOPES)
    payload = encrypt(json.dumps({"tokens": tokens.to_json()}))
    conn = await _first(session)
    if conn is None:
        conn = Connection(provider=ConnectionProvider.onedrive, label="OneDrive", secrets_enc=payload, config={},
                          scopes_granted=scopes, reads_description=onedrive.READS_DESCRIPTION, health="unknown",
                          enabled=True)
        session.add(conn)
        action = "connection.created"
    else:
        conn.secrets_enc, conn.scopes_granted, conn.health = payload, scopes, "unknown"
        action = "connection.updated"
    await session.flush()
    await audit.record(session, actor=actor, action=action, subject_type="connection", subject_id=conn.id,
                       detail={"provider": "onedrive", "scopes": scopes, "secret_names": ["tokens"]})
    return conn


async def onedrive_store(session: AsyncSession, conn: Connection | None = None, *,
                         transport: HttpTransport | None = None) -> onedrive.OneDriveStore:
    """The ``FileStore`` for the (first enabled) OneDrive connection. Token refreshes are written back through
    ``session`` (the caller commits); share links are recorded in the audit."""
    conn = conn or await _first(session)
    if conn is None:
        raise onedrive.OneDriveError("OneDrive is not connected")
    cfg = get_config()
    if not cfg.ms_oauth_client_id or not cfg.ms_oauth_client_secret:
        raise onedrive.OneDriveError("OneDrive sign-in is not set up on this server")
    stored = json.loads(decrypt(conn.secrets_enc)) if conn.secrets_enc else {}
    if "tokens" not in stored:
        raise onedrive.OneDriveError("OneDrive needs to be reconnected")

    async def tokens_changed(tokens: onedrive.OneDriveTokens) -> None:
        conn.secrets_enc = encrypt(json.dumps({"tokens": tokens.to_json()}))
        await session.flush()

    async def recorder(record: onedrive.ShareRecord) -> None:
        await audit.record(session, actor="system", action="filestore.share_link_created",
                           subject_type="connection", subject_id=conn.id,
                           detail={"key": record.key, "file_id": record.file_id, "audience": record.audience,
                                   "role": record.role, "url": record.url})

    return onedrive.OneDriveStore(
        transport or get_transport(), onedrive.OneDriveTokens.from_json(stored["tokens"]),
        client_id=cfg.ms_oauth_client_id, client_secret=cfg.ms_oauth_client_secret, tenant=cfg.ms_oauth_tenant,
        on_tokens_changed=tokens_changed, recorder=recorder, now=time.time)


async def run_test(session: AsyncSession, conn: Connection, *, transport: HttpTransport | None = None
                   ) -> tuple[bool, str]:
    """Test the connection: the app folder is reachable. Records health on the connection."""
    try:
        store = await onedrive_store(session, conn, transport=transport)
        name = await store.check()
    except (onedrive.OneDriveError, KeyError, ValueError) as exc:
        conn.health, conn.last_checked_at = "failing", utcnow()
        return False, str(exc)[:300]
    conn.health, conn.last_checked_at = "ok", utcnow()
    return True, f"OneDrive folder '{name}' is reachable"


async def update(session: AsyncSession, conn: Connection, *, label: str | None, config: dict[str, object] | None,
                 secrets_in: dict[str, str] | None, enabled: bool | None, actor: str) -> Connection:
    """OneDrive has nothing to type in: only its label and enabled switch change (tokens come from sign-in)."""
    if config or secrets_in:
        raise ValueError("OneDrive has no settings to change here; connect it again to sign in afresh")
    changed: list[str] = []
    if label is not None and label != conn.label:
        conn.label = label
        changed.append("label")
    if enabled is not None and enabled != conn.enabled:
        conn.enabled = enabled
        changed.append("enabled")
    await session.flush()
    if changed:
        await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                           subject_id=conn.id, detail={"provider": "onedrive", "changed": changed})
    return conn
