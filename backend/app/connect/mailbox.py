"""Mailbox interface (Gmail, IMAP/SMTP, Microsoft Graph). DESIGN.md 8.2, 12, 18.3, 18.5.

Invariants:
- **Narrowest read.** ``list_messages`` reads only the label or query configured on the
  connection, even when the granted scope is wider; the Connections screen states both.
- **Send is called only by the email channel**, after a ``DispatchAttempt`` exists. ``send``
  returns the provider message id, which is the confirmation evidence. It never retries on
  its own: a timeout returns ``None`` and the attempt goes to reconciliation.
- **Threading.** Replies use ``thread_id`` so employer replies thread naturally.
- **Reconcile from sent items.** ``find_sent`` lets a restored instance or a crashed worker
  discover whether a message actually left (18.3).
- Message bodies are untrusted content.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


class MailError(RuntimeError):
    """A mailbox call failed. Messages never contain tokens, passwords or message bodies."""


class MailConfigError(MailError):
    """The connection is not configured for this call (for example no label or query to read)."""


class MailAuthError(MailError):
    """Credentials are missing, revoked or refused. The connection needs to be reconnected."""


class MailSendError(MailError):
    """The provider definitely refused the message before accepting it (safe to say nothing left).
    An outcome that is merely unknown is not an error: ``send`` returns ``None``."""


@dataclass(frozen=True)
class Attachment:
    file_name: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class OutgoingMail:
    to: Sequence[str]
    subject: str
    body_text: str
    cc: Sequence[str] = ()
    attachments: Sequence[Attachment] = ()
    thread_id: str | None = None
    idempotency_key: str | None = None  # the DispatchAttempt id; stored in a header


@dataclass(frozen=True)
class MailMessage:
    provider_message_id: str
    thread_id: str
    sender: str
    to: Sequence[str]
    subject: str
    received_at: datetime
    body_text: str
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names; Message-ID, References, ...
    body_html: str = ""
    calendars: tuple[bytes, ...] = ()  # calendar (.ics) parts, size-capped; untrusted, read only by the calendar


@runtime_checkable
class Mailbox(Protocol):
    async def send(self, mail: OutgoingMail) -> str | None:
        """Send and return the provider message id, or None when the outcome is unknown."""
        ...

    async def list_messages(self, since: datetime, *, limit: int = 200) -> list[MailMessage]:
        """The oldest ``limit`` messages received at or after ``since``, oldest first. A full page means
        there may be more: the caller asks again from the newest one it got."""
        ...

    async def find_sent(self, idempotency_key: str) -> MailMessage | None:
        ...

    async def check(self) -> bool:
        """Health check: credentials valid and the configured label/query readable."""
        ...
