"""Mail ``Connection`` records (Gmail, IMAP/SMTP): validation, encrypted secrets, mailbox factory, OAuth.

Secrets (tokens, app passwords, a client secret) are Fernet-encrypted in ``Connection.secrets_enc``,
returned only masked, and never logged or audited (audit detail lists secret *names* only).
Non-secret settings live in ``Connection.config``; the sync bookkeeping keys (``INTERNAL_KEYS``) are
written only by the server.
"""

from __future__ import annotations

import json
import secrets as pysecrets
import uuid
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import gmail, msgraph_auth, msgraph_mail
from app.connect.gmail import GmailConfig, GmailMailbox
from app.connect.imap_smtp import ImapSmtpConfig, ImapSmtpMailbox, ServerSettings, StdlibImap, StdlibSmtp
from app.connect.mail_common import HttpTransport, HttpxTransport, ImapTransport, SmtpTransport
from app.connect.mailbox import MailAuthError, Mailbox, MailConfigError
from app.connect.msgraph_mail import MsGraphConfig, MsGraphMailbox
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.crypto import decrypt, encrypt
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.platform import Connection, ConnectionProvider

MAIL_PROVIDERS = frozenset({"gmail", "imap_smtp", "msgraph"})
MAIL_ENUMS = (ConnectionProvider.gmail, ConnectionProvider.imap_smtp, ConnectionProvider.msgraph)
INTERNAL_KEYS = ("checkpoint_at", "last_sync_at", "last_error")
GMAIL_KEYS = ("from_address", "read_label", "read_query", "client_id")
MSGRAPH_KEYS = ("from_address", "read_folder")
IMAP_KEYS = ("from_address", "username", "imap_host", "imap_port", "imap_security", "read_folder", "sent_folder",
             "smtp_host", "smtp_port", "smtp_security")
SECURITY = ("ssl", "starttls", "none")
OAUTH_MAX_AGE_SECONDS = 600


def is_mail(provider: str) -> bool:
    return provider in MAIL_PROVIDERS


def read_secrets(conn: Connection) -> dict[str, str]:
    return json.loads(decrypt(conn.secrets_enc)) if conn.secrets_enc else {}


def _store_secrets(conn: Connection, values: dict[str, str]) -> None:
    conn.secrets_enc = encrypt(json.dumps(values)) if values else None


def _port(config: dict[str, Any], key: str) -> None:
    if key in config:
        try:
            port = int(config[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"{key} must be between 1 and 65535")
        config[key] = port


def validate_config(provider: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return the cleaned non-secret config or raise ``ValueError`` (shown to the owner)."""
    allowed = {"gmail": GMAIL_KEYS, "msgraph": MSGRAPH_KEYS}.get(provider, IMAP_KEYS)
    unknown = set(config) - set(allowed) - set(INTERNAL_KEYS)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))} (secrets go in 'secrets')")
    out = {k: (v.strip() if isinstance(v, str) else v) for k, v in config.items() if k not in INTERNAL_KEYS}
    out = {k: v for k, v in out.items() if v not in ("", None)}
    if "from_address" in out and "@" not in str(out["from_address"]):
        raise ValueError("from_address must be an email address")
    if provider in ("gmail", "msgraph"):
        return out
    for key in ("imap_security", "smtp_security"):
        if key in out and out[key] not in SECURITY:
            raise ValueError(f"{key} must be one of {', '.join(SECURITY)}")
    _port(out, "imap_port")
    _port(out, "smtp_port")
    return out


def check_complete(provider: str, config: dict[str, Any], secrets: dict[str, str]) -> None:
    if provider in ("gmail", "msgraph"):
        return
    missing = [k for k in ("from_address", "imap_host", "smtp_host") if not config.get(k)]
    if missing:
        raise ValueError(f"missing: {', '.join(missing)}")
    if not secrets.get("password"):
        raise ValueError("the app password is required")


def reads_description(provider: str, config: dict[str, Any]) -> str:
    if provider == "gmail":
        scope = []
        if config.get("read_label"):
            scope.append(f'label "{config["read_label"]}"')
        if config.get("read_query"):
            scope.append(f'query "{config["read_query"]}"')
        target = " and ".join(scope) or "nothing yet (set a label or query)"
        return ("Granted: send mail, and read-only access to the whole mailbox (Google offers no narrower read "
                f"scope). This app reads only {target}, and searches sent items for the message ids it sent. "
                "A dedicated job-search mailbox is recommended.")
    if provider == "msgraph":
        target = f'the folder "{config["read_folder"]}"' if config.get("read_folder") else "nothing yet (set a folder)"
        return ("Granted: send mail, and read-only access to the whole mailbox (Microsoft offers no narrower read "
                f"permission). This app reads only {target}, and searches Sent Items for the message ids it sent. "
                "A dedicated job-search mailbox is recommended.")
    folder = config.get("read_folder") or "nothing yet (set a folder)"
    return (f"Sends through your SMTP server. Reads only the folder {folder!r}, plus the sent folder to confirm "
            "what it sent. Uses an app password stored encrypted.")


def _scopes(provider: str) -> list[str]:
    if provider == "msgraph":
        return list(msgraph_auth.MAIL_SCOPES)
    return list(gmail.GMAIL_SCOPES) if provider == "gmail" else []


async def create(session: AsyncSession, *, provider: str, label: str, config: dict[str, Any],
                 secrets: dict[str, str], actor: str) -> Connection:
    if provider == "gmail":
        raise ValueError("Gmail connects through Google sign-in; use the Connect Gmail button")
    if provider == "msgraph":
        raise ValueError("Outlook connects through Microsoft sign-in; use the Connect Outlook button")
    clean = validate_config(provider, config)
    given = {k: v for k, v in secrets.items() if v}
    check_complete(provider, clean, given)
    conn = Connection(provider=ConnectionProvider(provider), label=label, config=clean, scopes_granted=[],
                      reads_description=reads_description(provider, clean), health="unknown", enabled=True)
    _store_secrets(conn, given)
    session.add(conn)
    await session.flush()
    await audit.record(session, actor=actor, action="connection.created", subject_type="connection",
                       subject_id=conn.id, detail={"provider": provider, "label": label,
                                                   "secret_names": sorted(given)})
    return conn


async def update(session: AsyncSession, conn: Connection, *, label: str | None, config: dict[str, Any] | None,
                 secrets: dict[str, str] | None, enabled: bool | None, actor: str) -> Connection:
    provider = conn.provider.value
    changed: list[str] = []
    if label is not None and label != conn.label:
        conn.label = label
        changed.append("label")
    if config is not None:
        merged = {**conn.config, **validate_config(provider, config)}
        conn.config = merged
        conn.reads_description = reads_description(provider, merged)
        changed.append("config")
    if secrets is not None:
        merged_secrets = {**read_secrets(conn), **{k: v for k, v in secrets.items() if v}}
        _store_secrets(conn, merged_secrets)
        conn.health = "unknown"
        changed.append("secrets")
    if enabled is not None and enabled != conn.enabled:
        conn.enabled = enabled
        changed.append("enabled")
    if provider == "imap_smtp":
        check_complete(provider, conn.config, read_secrets(conn))
    await session.flush()
    if changed:
        await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                           subject_id=conn.id, detail={"provider": provider, "changed": changed})
    return conn


# ----- token persistence ------------------------------------------------------------------------


class ConnectionTokenStore:
    """Keeps refreshed Gmail tokens on the connection row, committed in its own transaction."""

    def __init__(self, connection_id: uuid.UUID) -> None:
        self.connection_id = connection_id

    async def load(self) -> dict[str, str]:
        async with get_sessionmaker()() as s:
            conn = await s.get(Connection, self.connection_id)
            return read_secrets(conn) if conn else {}

    async def save(self, tokens: dict[str, str]) -> None:
        async with get_sessionmaker()() as s:
            conn = await s.get(Connection, self.connection_id)
            if conn is not None:
                _store_secrets(conn, {**read_secrets(conn), **tokens})
                await s.commit()


# ----- building a mailbox -----------------------------------------------------------------------


def _client(conn: Connection, values: dict[str, str]) -> tuple[str, str]:
    cfg = get_config()
    client_id = conn.config.get("client_id") or cfg.google_oauth_client_id
    client_secret = values.get("client_secret") or cfg.google_oauth_client_secret
    if not client_id or not client_secret:
        raise MailConfigError("Gmail sign-in is not set up on this server (Google OAuth client id and secret)")
    return client_id, client_secret


def build_mailbox(conn: Connection, *, http: HttpTransport | None = None, smtp: SmtpTransport | None = None,
                  imap: ImapTransport | None = None) -> Mailbox:
    values = read_secrets(conn)
    c = conn.config
    if conn.provider == ConnectionProvider.gmail:
        client_id, client_secret = _client(conn, values)
        if not c.get("from_address"):
            raise MailConfigError("this Gmail connection has no sending address; reconnect it")
        return GmailMailbox(http=http or HttpxTransport(), tokens=ConnectionTokenStore(conn.id), client_id=client_id,
                            client_secret=client_secret,
                            config=GmailConfig(c["from_address"], c.get("read_label"), c.get("read_query")))
    if conn.provider == ConnectionProvider.imap_smtp:
        user = c.get("username") or c.get("from_address", "")
        password = values.get("password", "")
        if not password:
            raise MailAuthError("no app password stored")
        imap_server = ServerSettings(c["imap_host"], int(c.get("imap_port", 993)), c.get("imap_security", "ssl"),
                                     user, password)
        smtp_server = ServerSettings(c["smtp_host"], int(c.get("smtp_port", 465)), c.get("smtp_security", "ssl"),
                                     user, password)
        return ImapSmtpMailbox(
            smtp=smtp or StdlibSmtp(smtp_server), imap=imap or StdlibImap(imap_server),
            config=ImapSmtpConfig(c["from_address"], c.get("read_folder"), c.get("sent_folder", "Sent")))
    if conn.provider == ConnectionProvider.msgraph:
        cfg = get_config()
        if not cfg.ms_oauth_client_id or not cfg.ms_oauth_client_secret:
            raise MailConfigError("Outlook sign-in is not set up on this server (Microsoft client id and secret)")
        if not c.get("from_address"):
            raise MailConfigError("this Outlook connection has no sending address; reconnect it")
        return MsGraphMailbox(http=http or HttpxTransport(), tokens=ConnectionTokenStore(conn.id),
                              client_id=cfg.ms_oauth_client_id, client_secret=cfg.ms_oauth_client_secret,
                              tenant=cfg.ms_oauth_tenant, config=MsGraphConfig(c["from_address"], c.get("read_folder")))
    raise MailConfigError(f"{conn.provider.value} is not a mailbox provider")


async def mail_connections(session: AsyncSession) -> list[Connection]:
    """The enabled mailbox connections, oldest first, except that the owner's default mailbox
    (``mail.default_mailbox``) comes first; every "first mailbox" choice follows that."""
    rows = list(await session.scalars(select(Connection).where(
        Connection.provider.in_(MAIL_ENUMS), Connection.enabled.is_(True)).order_by(Connection.created_at)))
    default = await settings_service.get_value(session, "mail.default_mailbox")
    if default:
        rows.sort(key=lambda c: str(c.id) != str(default))  # stable: the rest keep their order
    return rows


async def resolve_for_identity(session: AsyncSession, sending_identity: str) -> Connection | None:
    """The enabled mailbox connection that sends as ``sending_identity`` (its from-address)."""
    wanted = sending_identity.strip().lower()
    for conn in await mail_connections(session):
        if str(conn.config.get("from_address", "")).lower() == wanted:
            return conn
    return None


async def test(conn: Connection, **transports: Any) -> tuple[bool, str]:
    """Health check without exposing any detail beyond a short, secret-free sentence."""
    try:
        ok = await build_mailbox(conn, **transports).check()
    except MailConfigError as exc:
        return False, str(exc)
    except MailAuthError as exc:
        return False, str(exc)
    except Exception:  # a transport failure: say so without echoing the library's message
        return False, "the mailbox could not be reached"
    return ok, "connected" if ok else "the mailbox refused the connection or the configured label/folder cannot be read"


# ----- Gmail OAuth ------------------------------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt="nchito-oauth-gmail")


def redirect_uri() -> str:
    return f"{get_config().base_origin}/api/connections/oauth/gmail/callback"


def oauth_start() -> str:
    cfg = get_config()
    if not cfg.google_oauth_client_id or not cfg.google_oauth_client_secret:
        raise MailConfigError("Gmail sign-in is not set up on this server (GOOGLE_OAUTH_CLIENT_ID and "
                              "GOOGLE_OAUTH_CLIENT_SECRET)")
    state = _serializer().dumps({"nonce": pysecrets.token_hex(8)})
    return gmail.authorize_url(cfg.google_oauth_client_id, redirect_uri(), state)


async def oauth_callback(session: AsyncSession, *, code: str, state: str, actor: str,
                         http: HttpTransport | None = None) -> Connection:
    try:
        _serializer().loads(state, max_age=OAUTH_MAX_AGE_SECONDS)
    except BadSignature as exc:
        raise MailAuthError("the sign-in link expired or was altered; start again") from exc
    cfg = get_config()
    assert cfg.google_oauth_client_id and cfg.google_oauth_client_secret
    transport = http or HttpxTransport()
    tokens = await gmail.exchange_code(transport, client_id=cfg.google_oauth_client_id,
                                       client_secret=cfg.google_oauth_client_secret, redirect_uri=redirect_uri(),
                                       code=code, now=utcnow())
    profile = await transport.request("GET", f"{gmail.API}/profile",
                                      headers={"Authorization": f"Bearer {tokens['access_token']}"})
    address = str(profile.data.get("emailAddress", "")) if isinstance(profile.data, dict) else ""
    if profile.status != 200 or not address:
        raise MailAuthError("could not read the Gmail address after signing in")
    granted = [s for s in tokens.get("scope", "").split() if s]
    conn = Connection(provider=ConnectionProvider.gmail, label=f"Gmail ({address})", config={"from_address": address},
                      scopes_granted=granted or _scopes("gmail"),
                      reads_description=reads_description("gmail", {}), health="unknown", enabled=True)
    _store_secrets(conn, {k: v for k, v in tokens.items() if k != "scope"})
    session.add(conn)
    await session.flush()
    await audit.record(session, actor=actor, action="connection.created", subject_type="connection",
                       subject_id=conn.id, detail={"provider": "gmail", "label": conn.label,
                                                   "secret_names": ["access_token", "expires_at", "refresh_token"]})
    return conn


# ----- Outlook (Microsoft Graph) OAuth ----------------------------------------------------------


def _ms_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt="nchito-oauth-msgraph")


def ms_redirect_uri() -> str:
    return f"{get_config().base_origin}/api/connections/oauth/msgraph/callback"


def msgraph_oauth_start() -> str:
    cfg = get_config()
    if not cfg.ms_oauth_client_id or not cfg.ms_oauth_client_secret:
        raise MailConfigError("Outlook sign-in is not set up on this server: set MS_OAUTH_CLIENT_ID and "
                              "MS_OAUTH_CLIENT_SECRET")
    state = _ms_serializer().dumps({"nonce": pysecrets.token_hex(8)})
    return msgraph_auth.authorize_url(tenant=cfg.ms_oauth_tenant, client_id=cfg.ms_oauth_client_id,
                                      redirect_uri=ms_redirect_uri(), state=state, scopes=msgraph_auth.MAIL_SCOPES)


async def msgraph_oauth_callback(session: AsyncSession, *, code: str, state: str, actor: str,
                                 http: HttpTransport | None = None) -> Connection:
    try:
        _ms_serializer().loads(state, max_age=OAUTH_MAX_AGE_SECONDS)
    except BadSignature as exc:
        raise MailAuthError("the sign-in link expired or was altered; start again") from exc
    cfg = get_config()
    if not cfg.ms_oauth_client_id or not cfg.ms_oauth_client_secret:
        raise MailConfigError("Outlook sign-in is not set up on this server")
    transport = http or HttpxTransport()
    tokens = await msgraph_mail.exchange_code(
        transport, tenant=cfg.ms_oauth_tenant, client_id=cfg.ms_oauth_client_id,
        client_secret=cfg.ms_oauth_client_secret, redirect_uri=ms_redirect_uri(), code=code, now=utcnow())
    address = (await msgraph_mail.mailbox_address(transport, tokens["access_token"])).lower()
    granted = msgraph_auth.scopes_granted(tokens.get("scope", ""), msgraph_auth.MAIL_SCOPES)
    secrets_now = {k: v for k, v in tokens.items() if k != "scope"}
    existing = next((c for c in await session.scalars(select(Connection).where(
        Connection.provider == ConnectionProvider.msgraph)) if c.config.get("from_address") == address), None)
    if existing is not None:  # signing in again as the same account refreshes it; the folder choice stays
        _store_secrets(existing, secrets_now)
        existing.scopes_granted, existing.health = granted, "unknown"
        await session.flush()
        await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                           subject_id=existing.id, detail={"provider": "msgraph", "changed": ["secrets"]})
        return existing
    config = {"from_address": address}
    conn = Connection(provider=ConnectionProvider.msgraph, label=f"Outlook ({address})", config=config,
                      scopes_granted=granted, reads_description=reads_description("msgraph", config),
                      health="unknown", enabled=True)
    _store_secrets(conn, secrets_now)
    session.add(conn)
    await session.flush()
    await audit.record(session, actor=actor, action="connection.created", subject_type="connection",
                       subject_id=conn.id, detail={"provider": "msgraph", "label": conn.label,
                                                   "secret_names": ["access_token", "expires_at", "refresh_token"]})
    return conn
