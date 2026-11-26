"""The Google Calendar connection record and its OAuth flow. DESIGN.md 12.

Connecting stores tokens (Fernet-encrypted) but leaves the connection **disabled**: nothing is written to Google
until the owner switches it on, which creates the dedicated calendar. Disabling stops all writes.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import gcalendar
from app.connect.http_transport import HttpTransport, get_transport
from app.connect.records import OAuthNotConfigured
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.crypto import decrypt, encrypt
from app.core.settings import service as settings_service
from app.models.platform import Connection, ConnectionProvider

STATE_SALT = "nchito-oauth-state"
STATE_MAX_AGE_SECONDS = 600
PROVIDER = "gcalendar"


def is_calendar(provider: str) -> bool:
    return provider == PROVIDER


def redirect_uri() -> str:
    return f"{get_config().base_url.rstrip('/')}/api/connections/oauth/gcalendar/callback"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt=STATE_SALT)


def oauth_start_url() -> str:
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise OAuthNotConfigured(
            "Google sign-in is not set up: set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET")
    state = _serializer().dumps({"p": PROVIDER, "n": secrets.token_urlsafe(8)})
    return gcalendar.authorize_url(client_id=cfg.google_oauth_client_id, redirect_uri=redirect_uri(), state=state)


def check_state(state: str) -> bool:
    try:
        raw = _serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)
    except BadSignature:
        return False
    return isinstance(raw, dict) and raw.get("p") == PROVIDER


async def first(session: AsyncSession, *, enabled_only: bool = False) -> Connection | None:
    stmt = select(Connection).where(Connection.provider == ConnectionProvider.gcalendar)
    if enabled_only:
        stmt = stmt.where(Connection.enabled.is_(True))
    return await session.scalar(stmt.order_by(Connection.created_at).limit(1))


async def oauth_finish(session: AsyncSession, *, code: str, actor: str,
                       transport: HttpTransport | None = None) -> Connection:
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise OAuthNotConfigured("Google sign-in is not set up")
    tokens = await gcalendar.exchange_code(transport or get_transport(), client_id=cfg.google_oauth_client_id,
                                           client_secret=cfg.google_oauth_client_secret,
                                           redirect_uri=redirect_uri(), code=code)
    payload = encrypt(json.dumps({"tokens": tokens.to_json()}))
    conn = await first(session)
    if conn is None:
        conn = Connection(provider=ConnectionProvider.gcalendar, label="Google Calendar", secrets_enc=payload,
                          config={}, scopes_granted=[gcalendar.SCOPE], reads_description=gcalendar.READS_DESCRIPTION,
                          health="ok", enabled=False, last_checked_at=utcnow())
        session.add(conn)
        action = "connection.created"
    else:
        conn.secrets_enc, conn.scopes_granted, conn.health = payload, [gcalendar.SCOPE], "ok"
        conn.last_checked_at = utcnow()
        action = "connection.updated"
    await session.flush()
    await audit.record(session, actor=actor, action=action, subject_type="connection", subject_id=conn.id,
                       detail={"provider": PROVIDER, "scopes": [gcalendar.SCOPE], "secret_names": ["tokens"],
                               "enabled": conn.enabled})
    return conn


def client(session: AsyncSession, conn: Connection, *, transport: HttpTransport | None = None
           ) -> gcalendar.GoogleCalendarClient:
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise gcalendar.CalendarError("Google sign-in is not set up on this server")
    stored: dict[str, Any] = json.loads(decrypt(conn.secrets_enc)) if conn.secrets_enc else {}
    if "tokens" not in stored:
        raise gcalendar.CalendarError("Google Calendar needs to be reconnected")

    async def tokens_changed(tokens: gcalendar.CalendarTokens) -> None:
        conn.secrets_enc = encrypt(json.dumps({"tokens": tokens.to_json()}))
        await session.flush()

    async def calendar_created(calendar_id: str) -> None:
        conn.config = {**conn.config, "calendar_id": calendar_id}
        await session.flush()

    return gcalendar.GoogleCalendarClient(
        transport or get_transport(), gcalendar.CalendarTokens.from_json(stored["tokens"]),
        client_id=cfg.google_oauth_client_id, client_secret=cfg.google_oauth_client_secret,
        calendar_id=conn.config.get("calendar_id"), on_tokens_changed=tokens_changed,
        on_calendar_created=calendar_created, now=time.time)


async def set_enabled(session: AsyncSession, conn: Connection, enabled: bool, *, actor: str,
                      transport: HttpTransport | None = None) -> Connection:
    """Switch writing on (creating the dedicated calendar the first time) or off."""
    if enabled and not conn.config.get("calendar_id"):
        values = await settings_service.values(session)
        gclient = client(session, conn, transport=transport)
        await gclient.ensure_calendar(str(values["calendar.google_calendar_name"]), str(values["general.timezone"]))
    conn.enabled = enabled
    conn.health, conn.last_checked_at = "ok", utcnow()
    await session.flush()
    await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                       subject_id=conn.id, detail={"provider": PROVIDER, "changed": ["enabled"], "enabled": enabled})
    return conn


async def run_test(session: AsyncSession, conn: Connection, *, transport: HttpTransport | None = None
                   ) -> tuple[bool, str]:
    try:
        name = await client(session, conn, transport=transport).check()
    except gcalendar.CalendarError as exc:
        conn.health, conn.last_checked_at = "failing", utcnow()
        return False, str(exc)[:300]
    conn.health, conn.last_checked_at = "ok", utcnow()
    return True, f"Calendar '{name}' is reachable"
