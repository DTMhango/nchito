"""Gmail ``Mailbox`` (OAuth). DESIGN.md 12, 18.3, 18.5.

Scopes are the narrowest that work: ``gmail.send`` to send and ``gmail.readonly`` to read. Google has
no scope limited to one label, so the app itself reads only the configured label or query (the
Connections screen states both). ``find_sent`` searches sent items for one message-id only.

Tokens live Fernet-encrypted on the ``Connection`` (see ``TokenStore``); the access token is
refreshed when it is about to expire or Gmail answers 401. Nothing here logs a token or a body.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

from app.connect.mail_common import (
    IDEMPOTENCY_HEADER,
    HttpResult,
    HttpTransport,
    TransportTimeout,
    build_mime,
    message_id_for,
    parse_rfc822,
    strip_brackets,
)
from app.connect.mailbox import MailAuthError, MailConfigError, MailError, MailMessage, MailSendError, OutgoingMail
from app.core.clock import utcnow

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SCOPES = (GMAIL_SEND_SCOPE, GMAIL_READ_SCOPE)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
REFRESH_MARGIN = timedelta(seconds=60)
LIST_PAGE = 100


class TokenStore(Protocol):
    """Where the (decrypted) token dict lives. Keys: access_token, refresh_token, expires_at (ISO)."""

    async def load(self) -> dict[str, str]: ...

    async def save(self, tokens: dict[str, str]) -> None: ...


@dataclass
class MemoryTokenStore:
    tokens: dict[str, str]

    async def load(self) -> dict[str, str]:
        return dict(self.tokens)

    async def save(self, tokens: dict[str, str]) -> None:
        self.tokens = dict(tokens)


@dataclass(frozen=True)
class GmailConfig:
    from_address: str
    read_label: str | None = None
    read_query: str | None = None


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "state": state,
        "scope": " ".join(GMAIL_SCOPES), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "false"})


def _expiry(seconds: Any, now: datetime) -> str:
    return (now + timedelta(seconds=int(seconds or 3600))).isoformat()


async def exchange_code(http: HttpTransport, *, client_id: str, client_secret: str, redirect_uri: str, code: str,
                        now: datetime | None = None) -> dict[str, str]:
    """Trade an authorization code for tokens. Raises ``MailAuthError`` without echoing the response."""
    try:
        r = await http.request("POST", TOKEN_URL, form={
            "code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"})
    except TransportTimeout as exc:
        raise MailError("Google did not answer in time; try again") from exc
    data = r.data if isinstance(r.data, dict) else {}
    if r.status != 200 or not data.get("access_token"):
        raise MailAuthError("Google refused the authorization code")
    if not data.get("refresh_token"):
        raise MailAuthError("Google returned no refresh token; remove the app's access in your Google account "
                            "and reconnect")
    return {"access_token": data["access_token"], "refresh_token": data["refresh_token"],
            "expires_at": _expiry(data.get("expires_in"), now or utcnow()), "scope": str(data.get("scope", ""))}


class GmailMailbox:
    def __init__(self, *, http: HttpTransport, tokens: TokenStore, client_id: str, client_secret: str,
                 config: GmailConfig, clock: Callable[[], datetime] = utcnow) -> None:
        self._http = http
        self._tokens = tokens
        self._client_id = client_id
        self._client_secret = client_secret
        self.config = config
        self.from_address = config.from_address
        self._clock = clock

    # ----- tokens -------------------------------------------------------------------------------

    async def _refresh(self, tokens: dict[str, str]) -> dict[str, str]:
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise MailAuthError("no refresh token stored; reconnect Gmail")
        r = await self._http.request("POST", TOKEN_URL, form={
            "client_id": self._client_id, "client_secret": self._client_secret, "refresh_token": refresh,
            "grant_type": "refresh_token"})
        data = r.data if isinstance(r.data, dict) else {}
        if r.status != 200 or not data.get("access_token"):
            raise MailAuthError("Google refused the stored refresh token; reconnect Gmail")
        fresh = {**tokens, "access_token": data["access_token"], "expires_at": _expiry(data.get("expires_in"),
                                                                                      self._clock())}
        await self._tokens.save(fresh)
        return fresh

    async def _access_token(self, *, force: bool = False) -> str:
        tokens = await self._tokens.load()
        expires = tokens.get("expires_at")
        stale = True
        if tokens.get("access_token") and expires and not force:
            stale = datetime.fromisoformat(expires).astimezone(UTC) - self._clock() <= REFRESH_MARGIN
        if stale:
            tokens = await self._refresh(tokens)
        return tokens["access_token"]

    async def _call(self, method: str, path: str, *, params: Mapping[str, Any] | None = None,
                    json_body: Any = None) -> HttpResult:
        """One API call; on 401 refresh once and repeat (a 401 means Gmail did nothing)."""
        for attempt in (0, 1):
            token = await self._access_token(force=attempt == 1)
            r = await self._http.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {token}"},
                                         params=params, json=json_body)
            if r.status != 401 or attempt == 1:
                if r.status == 401:
                    raise MailAuthError("Gmail rejected the credentials; reconnect Gmail")
                return r
        raise AssertionError("unreachable")

    # ----- Mailbox ------------------------------------------------------------------------------

    async def send(self, mail: OutgoingMail) -> str | None:
        msg = build_mime(mail, self.from_address)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body: dict[str, Any] = {"raw": raw}
        if mail.thread_id:
            body["threadId"] = mail.thread_id
        try:
            await self._access_token()  # a token problem is a refusal, not an unknown outcome
        except TransportTimeout as exc:
            raise MailSendError("could not reach Google to refresh the sign-in") from exc
        try:
            r = await self._call("POST", "/messages/send", json_body=body)
        except TransportTimeout:
            return None  # handed off, no answer: the outcome is unknown and is reconciled, never retried
        if r.status == 200 and isinstance(r.data, dict) and r.data.get("id"):
            return str(r.data["id"])
        if 400 <= r.status < 500:
            raise MailSendError(f"Gmail refused the message (HTTP {r.status})")
        return None  # 5xx or an unreadable answer: unknown

    async def list_messages(self, since: datetime, *, limit: int = 200) -> list[MailMessage]:
        """The oldest ``limit`` messages since ``since``, oldest first (the sync pages forward from them).

        Gmail lists newest first, so every id in the window is listed (ids only, cheap) and the oldest
        ``limit`` are fetched."""
        query = self._read_query(since)
        ids: list[str] = []
        token: str | None = None
        while True:
            params: dict[str, Any] = {"q": query, "maxResults": LIST_PAGE}
            if token:
                params["pageToken"] = token
            r = await self._call("GET", "/messages", params=params)
            data = self._ok(r, "list messages")
            ids.extend(str(ref["id"]) for ref in data.get("messages", []))
            token = data.get("nextPageToken")
            if not token:
                break
        found: list[MailMessage] = []
        for message_id in reversed(ids):
            if len(found) >= limit:
                break
            message = await self._get(message_id)
            if message is not None:
                found.append(message)
        return sorted(found, key=lambda m: m.received_at)

    async def find_sent(self, idempotency_key: str) -> MailMessage | None:
        wanted = strip_brackets(message_id_for(idempotency_key, self.from_address))
        r = await self._call("GET", "/messages", params={"q": f"in:sent rfc822msgid:{wanted}", "maxResults": 5})
        for ref in self._ok(r, "search sent items").get("messages", []):
            message = await self._get(str(ref["id"]))
            if message is not None and message.headers.get(IDEMPOTENCY_HEADER.lower()) == idempotency_key:
                return message
        return None

    async def check(self) -> bool:
        try:
            r = await self._call("GET", "/profile")
            if r.status != 200:
                return False
            if self.config.read_label or self.config.read_query:
                listing = await self._call("GET", "/messages", params={"q": self._read_query(None), "maxResults": 1})
                return listing.status == 200
            return True
        except (MailError, TransportTimeout):
            return False

    # ----- helpers ------------------------------------------------------------------------------

    def _read_query(self, since: datetime | None) -> str:
        """Only the configured label and/or query, however wide the granted scope is."""
        parts: list[str] = []
        if self.config.read_label:
            label = self.config.read_label.replace('"', "")
            parts.append(f'label:"{label}"')
        if self.config.read_query:
            parts.append(f"({self.config.read_query})")
        if not parts:
            raise MailConfigError("set the label or query this connection may read")
        if since is not None:
            parts.append(f"after:{int(since.timestamp())}")
        return " ".join(parts)

    @staticmethod
    def _ok(r: HttpResult, what: str) -> dict[str, Any]:
        if r.status != 200 or not isinstance(r.data, dict):
            raise MailError(f"Gmail could not {what} (HTTP {r.status})")
        return r.data

    async def _get(self, message_id: str) -> MailMessage | None:
        r = await self._call("GET", f"/messages/{message_id}", params={"format": "raw"})
        if r.status == 404:
            return None
        data = self._ok(r, "read a message")
        raw = base64.urlsafe_b64decode(str(data.get("raw", "")) + "=" * (-len(str(data.get("raw", ""))) % 4))
        internal = data.get("internalDate")
        fallback = datetime.fromtimestamp(int(internal) / 1000, tz=UTC) if internal else None
        return parse_rfc822(raw, provider_message_id=str(data.get("id", message_id)),
                            thread_id=str(data["threadId"]) if data.get("threadId") else None, fallback_time=fallback)

