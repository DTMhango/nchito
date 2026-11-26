"""Outlook ``Mailbox`` over Microsoft Graph (OAuth). DESIGN.md 12, 18.3, 18.5.

Delegated scopes are the narrowest that work: ``Mail.Send`` to send and ``Mail.Read`` to read (plus
``offline_access`` and ``User.Read`` to stay signed in and learn the address). Graph has no scope
limited to one folder, so the app itself reads only the configured folder (the Connections screen
states both) and searches Sent Items for the message id it sent.

Sending goes through a draft so the message carries our ``Message-ID`` and the
``X-Nchito-Idempotency-Key`` header: ``find_sent`` can then settle an unknown outcome from Sent Items.
``send`` never retries the send call: a timeout, a 429 or a 5xx on it returns ``None`` (unknown) and the
attempt is reconciled. Throttling (429 with ``Retry-After``) on every other call is waited out and the
call repeated; none of those calls can send mail.

Tokens live Fernet-encrypted on the ``Connection`` (``TokenStore``); the access token is refreshed when
about to expire or on a 401. Nothing here logs a token or a body.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from app.connect import msgraph_auth
from app.connect.gmail import MemoryTokenStore, TokenStore
from app.connect.mail_common import (
    IDEMPOTENCY_HEADER,
    KEPT_HEADERS,
    HttpResult,
    HttpTransport,
    TransportTimeout,
    message_id_for,
)
from app.connect.mailbox import MailAuthError, MailConfigError, MailError, MailMessage, MailSendError, OutgoingMail
from app.core.clock import utcnow
from app.sources.text import html_to_text

__all__ = ["MemoryTokenStore", "MsGraphConfig", "MsGraphMailbox", "TokenStore", "exchange_code", "mailbox_address"]

PAGE = 50
RECENT_SENT = 50
MAX_ATTACHMENT_BYTES = 3_000_000  # Graph takes attachments inline in the draft below about 3 MB
MAX_THROTTLE_RETRIES = 3
MAX_RETRY_WAIT_SECONDS = 30.0
DEFAULT_RETRY_WAIT_SECONDS = 2.0
WELL_KNOWN = {"inbox": "inbox", "archive": "archive", "junkemail": "junkemail", "junk": "junkemail",
              "drafts": "drafts", "sent items": "sentitems", "sentitems": "sentitems"}
SELECT = ("id,conversationId,subject,from,toRecipients,receivedDateTime,sentDateTime,body,internetMessageId,"
          "internetMessageHeaders")
_FRACTION = re.compile(r"(\.\d{6})\d+")

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class MsGraphConfig:
    from_address: str
    read_folder: str | None = None


async def exchange_code(http: HttpTransport, *, tenant: str, client_id: str, client_secret: str, redirect_uri: str,
                        code: str, scopes: tuple[str, ...] = msgraph_auth.MAIL_SCOPES,
                        now: datetime | None = None) -> dict[str, str]:
    """Trade an authorization code for tokens. Raises ``MailAuthError`` without echoing the answer."""
    try:
        r = await http.request("POST", msgraph_auth.token_url(tenant), form=msgraph_auth.code_form(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, code=code, scopes=scopes))
    except TransportTimeout as exc:
        raise MailError("Microsoft did not answer in time; try again") from exc
    try:
        return msgraph_auth.tokens_from_answer(r.status, r.data, now=now or utcnow(), need_scope=msgraph_auth.MAIL_SEND)
    except msgraph_auth.MsAuthError as exc:
        raise MailAuthError(str(exc)) from exc


async def mailbox_address(http: HttpTransport, access_token: str) -> str:
    """The signed-in account's mail address (``GET /me``)."""
    r = await http.request("GET", f"{msgraph_auth.GRAPH}/me", headers={"Authorization": f"Bearer {access_token}"},
                           params={"$select": "mail,userPrincipalName"})
    data = r.data if isinstance(r.data, dict) else {}
    address = str(data.get("mail") or data.get("userPrincipalName") or "")
    if r.status != 200 or "@" not in address:
        raise MailAuthError("could not read the Outlook address after signing in")
    return address


def _odata(value: str) -> str:
    return value.replace("'", "''")


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(_FRACTION.sub(r"\1", str(value)).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _address(entry: Any) -> str:
    box = entry.get("emailAddress") if isinstance(entry, dict) else None
    return str(box.get("address", "")).strip().lower() if isinstance(box, dict) else ""


def to_message(item: Mapping[str, Any]) -> MailMessage:
    """A Graph message resource as a ``MailMessage`` (the body is untrusted content)."""
    headers: dict[str, str] = {}
    for h in item.get("internetMessageHeaders") or []:
        name = str(h.get("name", "")).lower()
        if name in KEPT_HEADERS:
            headers[name] = str(h.get("value", ""))
    if item.get("internetMessageId"):
        headers["message-id"] = str(item["internetMessageId"])
    body = item.get("body") or {}
    content = str(body.get("content") or "")
    is_html = str(body.get("contentType", "")).lower() == "html"
    message_id = headers.get("message-id", "")
    return MailMessage(
        provider_message_id=str(item.get("id", "")),
        thread_id=str(item.get("conversationId") or message_id or item.get("id", "")),
        sender=_address(item.get("from")), to=[a for a in (_address(r) for r in item.get("toRecipients") or []) if a],
        subject=str(item.get("subject") or ""),
        received_at=_when(item.get("receivedDateTime")) or _when(item.get("sentDateTime")) or utcnow(),
        body_text=html_to_text(content) if is_html else content, headers=headers,
        body_html=content if is_html else "")


class MsGraphMailbox:
    def __init__(self, *, http: HttpTransport, tokens: TokenStore, client_id: str, client_secret: str, tenant: str,
                 config: MsGraphConfig, clock: Callable[[], datetime] = utcnow, sleep: Sleep = asyncio.sleep) -> None:
        self._http = http
        self._tokens = tokens
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant = tenant
        self.config = config
        self.from_address = config.from_address
        self._clock = clock
        self._sleep = sleep
        self._folder: str | None = None

    # ----- tokens -------------------------------------------------------------------------------

    async def _refresh(self, tokens: dict[str, str]) -> dict[str, str]:
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise MailAuthError("no refresh token stored; reconnect Outlook")
        r = await self._http.request("POST", msgraph_auth.token_url(self._tenant), form=msgraph_auth.refresh_form(
            client_id=self._client_id, client_secret=self._client_secret, refresh_token=refresh,
            scopes=msgraph_auth.MAIL_SCOPES))
        try:
            fresh = msgraph_auth.tokens_from_answer(r.status, r.data, now=self._clock(), previous=tokens)
        except msgraph_auth.MsAuthError as exc:
            raise MailAuthError("Microsoft refused the stored sign-in; reconnect Outlook") from exc
        await self._tokens.save(fresh)
        return fresh

    async def _access_token(self, *, force: bool = False) -> str:
        tokens = await self._tokens.load()
        if force or msgraph_auth.is_stale(tokens, self._clock()):
            tokens = await self._refresh(tokens)
        return tokens["access_token"]

    async def _call(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json_body: Any = None,
                    throttle_retries: int = MAX_THROTTLE_RETRIES) -> HttpResult:
        """One Graph call. A 401 refreshes once and repeats (nothing was done). A 429 waits ``Retry-After``
        and repeats up to ``throttle_retries`` times; pass 0 for the call that sends mail."""
        url = path if path.startswith("https://") else f"{msgraph_auth.GRAPH}{path}"
        if not url.startswith(msgraph_auth.GRAPH + "/"):
            raise MailError("Outlook returned a link outside Microsoft Graph")
        refreshed = False
        waits = 0
        while True:
            token = await self._access_token(force=refreshed)
            r = await self._http.request(method, url, headers={"Authorization": f"Bearer {token}"}, params=params,
                                         json=json_body)
            if r.status == 401:
                if refreshed:
                    raise MailAuthError("Outlook rejected the credentials; reconnect Outlook")
                refreshed = True
                continue
            if r.status == 429 and waits < throttle_retries:
                wait = _retry_after(r)
                if wait <= MAX_RETRY_WAIT_SECONDS:
                    waits += 1
                    await self._sleep(wait)
                    continue
            return r

    # ----- Mailbox ------------------------------------------------------------------------------

    async def send(self, mail: OutgoingMail) -> str | None:
        if sum(len(a.content) for a in mail.attachments) > MAX_ATTACHMENT_BYTES:
            raise MailSendError("the attachments are too large to send through Outlook (3 MB together)")
        message_id = message_id_for(mail.idempotency_key, self.from_address) if mail.idempotency_key else None
        try:
            await self._access_token()  # a token problem is a refusal, not an unknown outcome
        except TransportTimeout as exc:
            raise MailSendError("could not reach Microsoft to refresh the sign-in") from exc
        # Step 1: a draft. Nothing leaves the mailbox yet, so every failure here is a clean refusal.
        try:
            draft = await self._call("POST", "/me/messages", json_body=self._draft(mail, message_id))
        except TransportTimeout as exc:
            raise MailSendError("Outlook did not answer while preparing the message; nothing was sent") from exc
        data = draft.data if isinstance(draft.data, dict) else {}
        if draft.status != 201 or not data.get("id"):
            raise MailSendError(f"Outlook refused to prepare the message (HTTP {draft.status}); nothing was sent")
        draft_id = str(data["id"])
        sent_id = str(data.get("internetMessageId") or message_id or draft_id)
        # Step 2: the one send call, never repeated.
        try:
            r = await self._call("POST", f"/me/messages/{draft_id}/send", throttle_retries=0)
        except TransportTimeout:
            return None  # handed off, no answer: unknown, reconciled from Sent Items, never retried
        if r.status == 202:
            return sent_id
        if 400 <= r.status < 500 and r.status != 429:
            await self._discard(draft_id)
            raise MailSendError(f"Outlook refused the message (HTTP {r.status})")
        return None  # 429, 5xx or anything unreadable: unknown

    async def list_messages(self, since: datetime, *, limit: int = 200) -> list[MailMessage]:
        """The oldest ``limit`` messages of the configured folder since ``since``, oldest first."""
        folder = await self._folder_id()
        stamp = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        found: list[MailMessage] = []
        next_path: str | None = f"/me/mailFolders/{folder}/messages"
        params: Mapping[str, Any] | None = {
            "$filter": f"receivedDateTime ge {stamp}", "$orderby": "receivedDateTime asc",
            "$top": min(limit, PAGE), "$select": SELECT}
        while next_path and len(found) < limit:
            data = self._ok(await self._call("GET", next_path, params=params), "list messages")
            found.extend(to_message(item) for item in data.get("value", []))
            next_path, params = data.get("@odata.nextLink"), None  # the link carries its own query
        return sorted(found[:limit], key=lambda m: m.received_at)

    async def find_sent(self, idempotency_key: str) -> MailMessage | None:
        wanted = message_id_for(idempotency_key, self.from_address)
        sent = "/me/mailFolders/sentitems/messages"
        data = self._ok(await self._call("GET", sent, params={
            "$filter": f"internetMessageId eq '{_odata(wanted)}'", "$top": 5, "$select": SELECT}), "search sent items")
        for item in data.get("value", []):
            message = to_message(item)
            if message.headers.get("message-id") == wanted or _key_of(message) == idempotency_key:
                return _as_sent(message)
        # Exchange may rewrite the Message-ID: fall back to the key header on the most recent sent items.
        data = self._ok(await self._call("GET", sent, params={
            "$orderby": "sentDateTime desc", "$top": RECENT_SENT, "$select": SELECT}), "search sent items")
        for item in data.get("value", []):
            message = to_message(item)
            if _key_of(message) == idempotency_key:
                return _as_sent(message)
        return None

    async def check(self) -> bool:
        try:
            r = await self._call("GET", "/me", params={"$select": "mail,userPrincipalName"})
            if r.status != 200:
                return False
            if self.config.read_folder:
                listing = await self._call("GET", f"/me/mailFolders/{await self._folder_id()}/messages",
                                           params={"$top": 1, "$select": "id"})
                return listing.status == 200
            return True
        except (MailError, TransportTimeout):
            return False

    # ----- helpers ------------------------------------------------------------------------------

    def _draft(self, mail: OutgoingMail, message_id: str | None) -> dict[str, Any]:
        def recipients(values: Any) -> list[dict[str, Any]]:
            return [{"emailAddress": {"address": a}} for a in values]

        body: dict[str, Any] = {"subject": mail.subject, "body": {"contentType": "Text", "content": mail.body_text},
                                "toRecipients": recipients(mail.to)}
        if mail.cc:
            body["ccRecipients"] = recipients(mail.cc)
        if message_id and mail.idempotency_key:
            body["internetMessageId"] = message_id
            body["internetMessageHeaders"] = [{"name": IDEMPOTENCY_HEADER, "value": mail.idempotency_key}]
        if mail.attachments:
            body["attachments"] = [{"@odata.type": "#microsoft.graph.fileAttachment", "name": a.file_name,
                                    "contentType": a.mime_type,
                                    "contentBytes": base64.b64encode(a.content).decode()} for a in mail.attachments]
        return body

    async def _discard(self, draft_id: str) -> None:
        with contextlib.suppress(MailError, TransportTimeout):  # an orphan draft is harmless
            await self._call("DELETE", f"/me/messages/{draft_id}")

    async def _folder_id(self) -> str:
        """The one folder this connection may read: a well-known name or a folder name, resolved once."""
        name = (self.config.read_folder or "").strip()
        if not name:
            raise MailConfigError("set the folder this connection may read")
        if self._folder:
            return self._folder
        well_known = WELL_KNOWN.get(name.lower())
        if well_known:
            self._folder = well_known
            return well_known
        for path in ("/me/mailFolders", "/me/mailFolders/inbox/childFolders"):
            data = self._ok(await self._call("GET", path, params={
                "$filter": f"displayName eq '{_odata(name)}'", "$top": 2, "$select": "id,displayName"}),
                "look up the folder")
            for folder in data.get("value", []):
                if folder.get("id"):
                    self._folder = str(folder["id"])
                    return self._folder
        raise MailConfigError(f"the Outlook folder {name!r} was not found")

    @staticmethod
    def _ok(r: HttpResult, what: str) -> dict[str, Any]:
        if r.status == 429:
            raise MailError(f"Outlook is throttling requests; could not {what}, try again later")
        if r.status != 200 or not isinstance(r.data, dict):
            raise MailError(f"Outlook could not {what} (HTTP {r.status})")
        return r.data


def _as_sent(message: MailMessage) -> MailMessage:
    """Identify a sent item by its Message-ID, the same value ``send`` returned as the evidence."""
    mid = message.headers.get("message-id")
    return replace(message, provider_message_id=mid) if mid else message


def _key_of(message: MailMessage) -> str | None:
    return message.headers.get(IDEMPOTENCY_HEADER.lower())


def _retry_after(r: HttpResult) -> float:
    raw = next((v for k, v in r.headers.items() if k.lower() == "retry-after"), None)
    try:
        return max(float(str(raw)), 0.0)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_WAIT_SECONDS
