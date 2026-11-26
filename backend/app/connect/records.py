"""Connection records for Google Drive, Telegram and the signed webhook.

Secrets (bot token, signing secret, Drive tokens) are Fernet-encrypted in ``Connection.secrets_enc``,
returned only masked, and never logged or audited (the audit lists secret *names*). This module
also builds the live ``Notifier`` and ``FileStore`` objects from those records.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import gdrive
from app.connect.http_transport import HttpTransport, get_transport
from app.connect.notifier import (
    DeliveryError,
    Notifier,
    OutboundMessage,
    register_notifier_factory,
)
from app.connect.telegram import TelegramNotifier
from app.connect.webhook import MIN_SECRET_LENGTH, WebhookNotifier, validate_url
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.crypto import decrypt, encrypt
from app.core.settings import service as settings_service
from app.llm.provider_records import read_secrets
from app.models.platform import Connection, ConnectionProvider

OPS_PROVIDERS = frozenset({"gdrive", "telegram", "webhook"})
CONFIG_KEYS = {"telegram": ("chat_id",), "webhook": ("url",), "gdrive": ("root_folder_name", "root_folder_id")}
SECRET_KEYS = {"telegram": ("bot_token",), "webhook": ("signing_secret",), "gdrive": ()}
READS = {
    "telegram": "Sends messages to one chat. Reads nothing: no messages, contacts or chats.",
    "webhook": "Sends signed JSON messages to one address. Reads nothing.",
    "gdrive": gdrive.READS_DESCRIPTION,
}
STATE_SALT = "nchito-oauth-state"
STATE_MAX_AGE_SECONDS = 600
_CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{4,64})$")
_TOKEN_RE = re.compile(r"^\d{3,}:[A-Za-z0-9_-]{16,}$")


def is_ops(provider: str) -> bool:
    return provider in OPS_PROVIDERS


def validate(provider: str, config: dict[str, Any], secrets_in: dict[str, str], *, creating: bool) -> None:
    unknown = set(config) - set(CONFIG_KEYS[provider])
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))} (secrets go in 'secrets')")
    extra = set(secrets_in) - set(SECRET_KEYS[provider])
    if extra:
        raise ValueError(f"unknown secrets: {', '.join(sorted(extra))}")
    if provider == "telegram":
        if (creating or "chat_id" in config) and not _CHAT_RE.match(str(config.get("chat_id", ""))):
            raise ValueError("chat_id must be a number (or @channelname)")
        token = secrets_in.get("bot_token", "")
        if (creating or token) and not _TOKEN_RE.match(token):
            raise ValueError("bot_token looks wrong; paste the whole token from BotFather")
    elif provider == "webhook":
        if creating or "url" in config:
            validate_url(str(config.get("url", "")))
        secret = secrets_in.get("signing_secret", "")
        if (creating or secret) and len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"signing_secret must be at least {MIN_SECRET_LENGTH} characters")


async def create(session: AsyncSession, *, provider: str, label: str, config: dict[str, Any],
                 secrets_in: dict[str, str], actor: str) -> Connection:
    if provider == "gdrive":
        raise ValueError("connect Google Drive with the Connect button, not by pasting keys")
    validate(provider, config, secrets_in, creating=True)
    conn = Connection(provider=ConnectionProvider(provider), label=label, config=dict(config),
                      secrets_enc=encrypt(json.dumps(secrets_in)), scopes_granted=[],
                      reads_description=READS[provider], health="unknown", enabled=True)
    session.add(conn)
    await session.flush()
    await audit.record(session, actor=actor, action="connection.created", subject_type="connection",
                       subject_id=conn.id, detail={"provider": provider, "label": label,
                                                   "secret_names": sorted(secrets_in)})
    return conn


async def update(session: AsyncSession, conn: Connection, *, label: str | None, config: dict[str, Any] | None,
                 secrets_in: dict[str, str] | None, enabled: bool | None, actor: str) -> Connection:
    provider = conn.provider.value
    changed: list[str] = []
    if label is not None and label != conn.label:
        conn.label = label
        changed.append("label")
    if config is not None:
        merged = {**conn.config, **config} if provider == "gdrive" else dict(config)
        validate(provider, merged, {}, creating=provider != "gdrive")
        conn.config = merged
        changed.append("config")
    if secrets_in is not None and provider != "gdrive":
        provided = {k: v for k, v in secrets_in.items() if v}
        validate(provider, {}, provided, creating=False)
        conn.secrets_enc = encrypt(json.dumps({**read_secrets(conn), **provided}))
        conn.health = "unknown"
        changed.append("secrets")
    if enabled is not None and enabled != conn.enabled:
        conn.enabled = enabled
        changed.append("enabled")
    await session.flush()
    await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                       subject_id=conn.id, detail={"changed": changed, "secret_names": sorted(secrets_in or {})})
    return conn


# ----- Telegram and webhook notifiers ---------------------------------------------------------


async def _first(session: AsyncSession, provider: str) -> Connection | None:
    return await session.scalar(select(Connection).where(
        Connection.provider == ConnectionProvider(provider), Connection.enabled.is_(True)
    ).order_by(Connection.created_at).limit(1))


def build_notifier(conn: Connection, transport: HttpTransport) -> Notifier:
    secrets_in = read_secrets(conn)
    if conn.provider == ConnectionProvider.telegram:
        return TelegramNotifier(transport, bot_token=secrets_in["bot_token"], chat_id=str(conn.config["chat_id"]))
    return WebhookNotifier(transport, url=str(conn.config["url"]), secret=secrets_in["signing_secret"])


async def _factory(session: AsyncSession, provider: str) -> Notifier | None:
    conn = await _first(session, provider)
    if conn is None:
        return None
    try:
        return build_notifier(conn, get_transport())
    except (KeyError, ValueError):
        return None


async def telegram_factory(session: AsyncSession) -> Notifier | None:
    return await _factory(session, "telegram")


async def webhook_factory(session: AsyncSession) -> Notifier | None:
    return await _factory(session, "webhook")


register_notifier_factory("telegram", telegram_factory)
register_notifier_factory("webhook", webhook_factory)
import app.connect.mail_notifier  # noqa: E402, F401  (registers the email notifier)


async def mark_health(session: AsyncSession, provider: str, ok: bool) -> None:
    conn = await _first(session, provider)
    if conn is not None:
        conn.health = "ok" if ok else "failing"
        conn.last_checked_at = utcnow()


async def run_test(session: AsyncSession, conn: Connection, *, transport: HttpTransport | None = None
                   ) -> tuple[bool, str]:
    """Test one connection. Telegram and webhook send a one-line test message; Drive checks its folder."""
    transport = transport or get_transport()
    provider = conn.provider.value
    try:
        if provider == "gdrive":
            store = await drive_store(session, conn, transport=transport)
            name = await store.check()
            detail = f"Drive folder '{name}' is reachable"
        else:
            notifier = build_notifier(conn, transport)
            if isinstance(notifier, TelegramNotifier):
                bot = await notifier.check()
                detail = f"bot @{bot} accepted a test message"
            else:
                detail = "webhook accepted a test message"
            await notifier.send(OutboundMessage(
                event_id=f"test-{uuid.uuid4()}", kind="test", title="Test message", created_at=utcnow(),
                body="If you can read this, the connection works."))
    except (DeliveryError, gdrive.DriveError, KeyError, ValueError) as exc:
        conn.health, conn.last_checked_at = "failing", utcnow()
        return False, str(exc)[:300]
    conn.health, conn.last_checked_at = "ok", utcnow()
    return True, detail


# ----- Google Drive ---------------------------------------------------------------------------


def redirect_uri() -> str:
    return f"{get_config().base_url.rstrip('/')}/api/connections/oauth/gdrive/callback"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt=STATE_SALT)


class OAuthNotConfigured(RuntimeError):
    pass


def oauth_start_url() -> str:
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise OAuthNotConfigured(
            "Google sign-in is not set up: set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET")
    state = _serializer().dumps({"p": "gdrive", "n": secrets.token_urlsafe(8)})
    return gdrive.authorize_url(client_id=cfg.google_oauth_client_id, redirect_uri=redirect_uri(), state=state)


def check_state(state: str) -> bool:
    try:
        raw = _serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)
    except BadSignature:
        return False
    return isinstance(raw, dict) and raw.get("p") == "gdrive"


async def oauth_finish(session: AsyncSession, *, code: str, actor: str,
                       transport: HttpTransport | None = None) -> Connection:
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise OAuthNotConfigured("Google sign-in is not set up")
    tokens = await gdrive.exchange_code(transport or get_transport(), client_id=cfg.google_oauth_client_id,
                                        client_secret=cfg.google_oauth_client_secret, redirect_uri=redirect_uri(),
                                        code=code)
    app_name = await settings_service.get_value(session, "general.app_name")
    conn = await _first(session, "gdrive")
    payload = encrypt(json.dumps({"tokens": tokens.to_json()}))
    if conn is None:
        conn = Connection(provider=ConnectionProvider.gdrive, label="Google Drive", secrets_enc=payload,
                          config={"root_folder_name": str(app_name)}, scopes_granted=[gdrive.SCOPE],
                          reads_description=READS["gdrive"], health="ok", enabled=True, last_checked_at=utcnow())
        session.add(conn)
        action = "connection.created"
    else:
        conn.secrets_enc, conn.scopes_granted, conn.health = payload, [gdrive.SCOPE], "ok"
        conn.last_checked_at = utcnow()
        action = "connection.updated"
    await session.flush()
    await audit.record(session, actor=actor, action=action, subject_type="connection", subject_id=conn.id,
                       detail={"provider": "gdrive", "scopes": [gdrive.SCOPE], "secret_names": ["tokens"]})
    return conn


async def drive_store(session: AsyncSession, conn: Connection | None = None, *,
                      transport: HttpTransport | None = None) -> gdrive.GoogleDriveStore:
    """The ``FileStore`` for the (first enabled) Drive connection. Token refreshes and the root folder id
    are written back to the connection through ``session`` (the caller commits)."""
    conn = conn or await _first(session, "gdrive")
    if conn is None:
        raise gdrive.DriveError("Google Drive is not connected")
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise gdrive.DriveError("Google sign-in is not set up on this server")
    stored = json.loads(decrypt(conn.secrets_enc)) if conn.secrets_enc else {}
    if "tokens" not in stored:
        raise gdrive.DriveError("Google Drive needs to be reconnected")

    async def tokens_changed(tokens: gdrive.DriveTokens) -> None:
        conn.secrets_enc = encrypt(json.dumps({"tokens": tokens.to_json()}))
        await session.flush()

    async def root_created(folder_id: str) -> None:
        conn.config = {**conn.config, "root_folder_id": folder_id}
        await session.flush()

    async def recorder(record: gdrive.ShareRecord) -> None:
        await audit.record(session, actor="system", action="filestore.share_link_created",
                           subject_type="connection", subject_id=conn.id,
                           detail={"key": record.key, "file_id": record.file_id, "audience": record.audience,
                                   "role": record.role, "url": record.url})

    return gdrive.GoogleDriveStore(
        transport or get_transport(), gdrive.DriveTokens.from_json(stored["tokens"]),
        client_id=cfg.google_oauth_client_id, client_secret=cfg.google_oauth_client_secret,
        root_folder_name=str(conn.config.get("root_folder_name") or "Nchito"),
        root_folder_id=conn.config.get("root_folder_id"), on_tokens_changed=tokens_changed,
        on_root_created=root_created, recorder=recorder, now=time.time)
