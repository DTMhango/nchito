"""Shared plumbing for the mailbox implementations: MIME, parsing, injectable transports.

Everything that touches a network is behind a small Protocol (``HttpTransport``, ``SmtpTransport``,
``ImapTransport``) so tests inject fakes. Nothing here logs a token, a password or a message body.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Protocol

import httpx

from app.connect.mailbox import MailMessage, OutgoingMail
from app.sources.text import html_to_text

IDEMPOTENCY_HEADER = "X-Nchito-Idempotency-Key"
MESSAGE_ID_PREFIX = "nchito-"
KEPT_HEADERS = ("message-id", "in-reply-to", "references", "reply-to", "auto-submitted", "list-id", "return-path",
                "x-nchito-idempotency-key", "content-type")
_MSGID_KEY_RE = re.compile(r"nchito-([0-9a-fA-F-]{8,64})@")


class TransportTimeout(Exception):
    """A network call timed out. For a send this means the outcome is unknown."""


# ----- transports -------------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpResult:
    status: int
    data: Any  # parsed JSON when the body is JSON, else text


class HttpTransport(Protocol):
    async def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                      params: Mapping[str, Any] | None = None, json: Any = None,
                      form: Mapping[str, str] | None = None) -> HttpResult: ...


class HttpxTransport:
    """Production ``HttpTransport``. Raises ``TransportTimeout`` on any timeout."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout = timeout_seconds

    async def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                      params: Mapping[str, Any] | None = None, json: Any = None,
                      form: Mapping[str, str] | None = None) -> HttpResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.request(method, url, headers=dict(headers or {}), params=params, json=json,
                                         data=dict(form) if form else None)
        except httpx.TimeoutException as exc:
            raise TransportTimeout(type(exc).__name__) from exc
        try:
            data: Any = r.json()
        except ValueError:
            data = r.text
        return HttpResult(r.status_code, data)


class SmtpRejected(Exception):
    """The SMTP server refused the message before accepting it (nothing was sent)."""


class SmtpTransport(Protocol):
    async def send(self, raw: bytes, sender: str, recipients: Sequence[str]) -> None:
        """Hand the message to the server. ``SmtpRejected`` = definitely not sent; ``TransportTimeout`` =
        unknown (the server may have accepted it)."""
        ...


@dataclass(frozen=True)
class RawMail:
    uid: str
    raw: bytes


class ImapTransport(Protocol):
    async def fetch_since(self, folder: str, since: datetime, limit: int) -> list[RawMail]: ...

    async def find_by_header(self, folder: str, header: str, value: str) -> list[RawMail]: ...

    async def check(self, folder: str) -> bool: ...


# ----- building and parsing ---------------------------------------------------------------------


def message_id_for(key: str, from_address: str) -> str:
    """Deterministic Message-ID carrying the idempotency key, so sent items can be searched by it."""
    domain = from_address.rsplit("@", 1)[-1] or "localhost"
    return f"<{MESSAGE_ID_PREFIX}{key}@{domain}>"


def key_from_ids(*values: str) -> str | None:
    """The idempotency key inside a Message-ID or References header, if one of ours is present."""
    for value in values:
        m = _MSGID_KEY_RE.search(value or "")
        if m:
            return m.group(1)
    return None


def build_mime(mail: OutgoingMail, from_address: str, *, reply_to_message_id: str | None = None) -> EmailMessage:
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = from_address
    msg["To"] = ", ".join(mail.to)
    if mail.cc:
        msg["Cc"] = ", ".join(mail.cc)
    msg["Subject"] = mail.subject
    msg["Date"] = formatdate(localtime=False)
    if mail.idempotency_key:
        msg["Message-ID"] = message_id_for(mail.idempotency_key, from_address)
        msg[IDEMPOTENCY_HEADER] = mail.idempotency_key
    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id
    msg.set_content(mail.body_text)
    for att in mail.attachments:
        maintype, _, subtype = att.mime_type.partition("/")
        msg.add_attachment(att.content, maintype=maintype or "application", subtype=subtype or "octet-stream",
                           filename=att.file_name)
    return msg


def address_of(value: str) -> str:
    return parseaddr(value or "")[1].strip().lower()


def addresses_of(value: str) -> list[str]:
    return [a.strip().lower() for _, a in getaddresses([value or ""]) if a.strip()]


def _plain_body(msg: EmailMessage) -> tuple[str, str]:
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    html_text = _content(html)
    plain_text = _content(plain)
    return (plain_text or html_to_text(html_text)), html_text


def _content(part: Any) -> str:
    if part is None:
        return ""
    try:
        return str(part.get_content())
    except (LookupError, UnicodeDecodeError, AssertionError):
        return ""


def parse_rfc822(raw: bytes, *, provider_message_id: str | None = None, thread_id: str | None = None,
                 fallback_time: datetime | None = None) -> MailMessage:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert isinstance(msg, EmailMessage)
    headers = {k: str(msg[k]) for k in KEPT_HEADERS if msg[k] is not None}
    message_id = headers.get("message-id", "").strip()
    refs = headers.get("references", "").split()
    in_reply = headers.get("in-reply-to", "").strip()
    thread = thread_id or (refs[0] if refs else in_reply or message_id)
    try:
        received = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError):
        received = None
    if received is None:
        received = fallback_time or datetime.now(UTC)
    if received.tzinfo is None:
        received = received.replace(tzinfo=UTC)
    text, html = _plain_body(msg)
    return MailMessage(
        provider_message_id=provider_message_id or message_id, thread_id=thread,
        sender=address_of(str(msg["From"] or "")), to=addresses_of(str(msg["To"] or "")),
        subject=str(msg["Subject"] or ""), received_at=received, body_text=text, headers=headers, body_html=html)


def strip_brackets(message_id: str) -> str:
    return message_id.strip().strip("<>").strip()


def sender_matches(sender: str, patterns: Sequence[str]) -> bool:
    """``patterns`` hold addresses (``jobs@example.com``) or domains (``example.com`` or ``@example.com``)."""
    sender = sender.strip().lower()
    domain = sender.rsplit("@", 1)[-1]
    for raw in patterns:
        p = str(raw).strip().lower()
        if not p:
            continue
        if "@" in p and not p.startswith("@"):
            if sender == p:
                return True
        elif domain == p.lstrip("@") or domain.endswith("." + p.lstrip("@")):
            return True
    return False
