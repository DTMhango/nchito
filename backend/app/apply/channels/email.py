"""The email channel: the server is the sender (DESIGN.md 8.2, 18.1, 18.3). Enforcement: ``server``.

What it enforces before one byte leaves:

- the ``DispatchAttempt`` exists, is for the email channel and has not already been sent or settled;
- the packet it was handed hashes to the attempt's ``packet_hash`` (nothing is re-read live);
- the single-use permit on the attempt was **consumed for this very packet hash** and application;
- the body, subject and recipients are exactly the packet's; every attachment is loaded and its sha256
  must equal the packet's (a file that changed is a packet change, so nothing is sent);
- the sending identity is the connected mailbox's address;
- sent items are searched for this attempt's idempotency key first, so a retried call after a crash
  returns the earlier send instead of sending again.

It never resends. A hand-off that gets no answer is reported ``unknown`` and ``reconcile`` settles it from
sent items. ``sent`` always carries evidence (provider message id, or the sent-items match). The channel
reads the attempt and permit but writes nothing: the apply layer records the outcome.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.apply.channels.base import ChannelName, DispatchOutcome, DispatchRequest, Enforcement
from app.connect import mail_connections
from app.connect.filestore import FileStore
from app.connect.mailbox import (
    Attachment,
    MailAuthError,
    Mailbox,
    MailConfigError,
    MailMessage,
    MailSendError,
    OutgoingMail,
)
from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.models.applications import ApplicationPacket, DispatchAttempt, DispatchStatus, SubmitPermit
from app.models.applications import Channel as ChannelEnum
from app.models.documents import ApplicationDocument
from app.models.kit import VaultDocument
from app.schemas.json_types import Evidence, PacketContents, PacketFile

ADDRESS_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
SENDABLE = (DispatchStatus.reserved, DispatchStatus.handed_off)

MailboxResolver = Callable[[AsyncSession, str], Awaitable[Mailbox | None]]
AttachmentLoader = Callable[[PacketFile], Awaitable[bytes]]
PacketHasher = Callable[[PacketContents], str]


def packet_hash(packet: PacketContents) -> str:
    """sha256 of the canonical JSON of the packet (CONTRACTS section 8: ``ApplicationPacket.content_hash``)."""
    canonical = json.dumps(packet.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def default_resolver(session: AsyncSession, sending_identity: str) -> Mailbox | None:
    conn = await mail_connections.resolve_for_identity(session, sending_identity)
    return mail_connections.build_mailbox(conn) if conn is not None else None


def _failed(error: str) -> DispatchOutcome:
    return DispatchOutcome(status="failed", error=error)


def _sent(message_id: str) -> DispatchOutcome:
    evidence = Evidence(kind="sent_mail_id", value=message_id, at=utcnow().isoformat())
    return DispatchOutcome(status="sent", provider_message_id=message_id, evidence=evidence)


class EmailChannel:
    name: ClassVar[ChannelName] = "email"
    enforcement: ClassVar[Enforcement] = "server"

    def __init__(self, *, attachments: AttachmentLoader, sessionmaker: async_sessionmaker[AsyncSession] | None = None,
                 resolver: MailboxResolver = default_resolver, hasher: PacketHasher = packet_hash) -> None:
        self._attachments = attachments
        self._sessionmaker = sessionmaker
        self._resolve = resolver
        self._hash = hasher
        self._handed_off: set[str] = set()

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker or get_sessionmaker()

    # ----- dispatch -----------------------------------------------------------------------------

    async def _gate(self, session: AsyncSession, request: DispatchRequest) -> DispatchAttempt | DispatchOutcome:
        try:
            attempt = await session.get(DispatchAttempt, uuid.UUID(request.attempt_id))
        except ValueError:
            attempt = None
        if attempt is None:
            return _failed("no dispatch attempt exists for this send")
        if attempt.channel != ChannelEnum.email:
            return _failed("the attempt is not for the email channel")
        if attempt.status not in SENDABLE:
            return _failed(f"the attempt is already {attempt.status.value}; an attempt is never sent twice")
        if str(attempt.application_id) != request.application_id:
            return _failed("the attempt belongs to a different application")
        if attempt.packet_hash != request.packet_hash or self._hash(request.packet) != request.packet_hash:
            return _failed("the packet does not match the hash on the attempt; nothing was sent")
        permit = await session.get(SubmitPermit, attempt.permit_id) if attempt.permit_id else None
        if (permit is None or permit.used_at is None or permit.packet_hash != request.packet_hash
                or permit.application_id != attempt.application_id):
            return _failed("no consumed permit for this packet; nothing was sent")
        return attempt

    async def _outgoing(self, request: DispatchRequest) -> OutgoingMail | DispatchOutcome:
        email = request.packet.email
        if email is None or not email.to:
            return _failed("the packet has no email to send")
        for address in [*email.to, *email.cc]:
            if not ADDRESS_RE.match(address):
                return _failed(f"{address!r} is not an email address")
        attachments: list[Attachment] = []
        for f in request.packet.files:
            if f.share_link:
                continue  # shared by link; the link is part of the hashed body, nothing is attached
            content = await self._attachments(f)
            if hashlib.sha256(content).hexdigest() != f.sha256:
                return _failed(f"attachment {f.name!r} changed since approval; nothing was sent")
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            attachments.append(Attachment(f.name, mime, content))
        return OutgoingMail(to=list(email.to), cc=list(email.cc), subject=email.subject, body_text=email.body,
                            attachments=attachments, idempotency_key=request.attempt_id,
                            thread_id=email.thread_ref)  # a message replies in its thread (hashed in the packet)

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        async with self._sm()() as session:
            gate = await self._gate(session, request)
            if isinstance(gate, DispatchOutcome):
                return gate
            mailbox = await self._resolve(session, request.packet.sending_identity)
        if mailbox is None:
            return _failed("no connected mailbox sends as this identity")
        identity = getattr(mailbox, "from_address", None)
        if identity is not None and str(identity).lower() != request.packet.sending_identity.strip().lower():
            return _failed("the connected mailbox is not the packet's sending identity")
        mail = await self._outgoing(request)
        if isinstance(mail, DispatchOutcome):
            return mail
        if request.attempt_id in self._handed_off:
            return DispatchOutcome(status="unknown", error="already handed to the mailbox; reconcile, never resend")
        try:
            earlier = await mailbox.find_sent(request.attempt_id)
        except (MailAuthError, MailConfigError) as exc:
            return _failed(str(exc))
        except Exception:
            return _failed("could not check sent items before sending; nothing was sent")
        if earlier is not None:
            return _sent(earlier.provider_message_id)
        self._handed_off.add(request.attempt_id)  # from here a cancel is too late and a second call is refused
        try:
            message_id = await mailbox.send(mail)
        except (MailSendError, MailAuthError, MailConfigError) as exc:
            return _failed(str(exc))
        except Exception:
            return DispatchOutcome(status="unknown",
                                   error="the send ended in an error after hand-off; check sent items")
        if message_id is None:
            return DispatchOutcome(status="unknown", error="no answer after hand-off; reconcile from sent items")
        return _sent(message_id)

    # ----- cancel and reconcile -----------------------------------------------------------------

    async def cancel(self, attempt_id: str) -> bool:
        """True only while nothing has been handed to the mailbox (the apply layer then marks it cancelled)."""
        if attempt_id in self._handed_off:
            return False
        async with self._sm()() as session:
            try:
                attempt = await session.get(DispatchAttempt, uuid.UUID(attempt_id))
            except ValueError:
                return False
            return attempt is not None and attempt.status in SENDABLE and attempt.channel == ChannelEnum.email

    async def reconcile(self, attempt_id: str) -> DispatchOutcome:
        """Settle an attempt with no outcome from the mailbox's sent items. Never sends."""
        async with self._sm()() as session:
            try:
                attempt = await session.get(DispatchAttempt, uuid.UUID(attempt_id))
            except ValueError:
                attempt = None
            if attempt is None:
                return _failed("no dispatch attempt exists for this id")
            packet = await session.get(ApplicationPacket, attempt.packet_id)
            if packet is None:
                return DispatchOutcome(status="unknown", error="the attempt's packet is missing")
            try:
                mailbox = await self._resolve(session, packet.contents.sending_identity)
            except (MailAuthError, MailConfigError) as exc:
                return DispatchOutcome(status="unknown", error=str(exc))
        if mailbox is None:
            return DispatchOutcome(status="unknown", error="no connected mailbox sends as this identity")
        try:
            found: MailMessage | None = await mailbox.find_sent(attempt_id)
        except Exception:
            return DispatchOutcome(status="unknown", error="sent items could not be read; try again")
        if found is None:
            return DispatchOutcome(status="unknown", error="not found in sent items (yet); it is not resent")
        return _sent(found.provider_message_id)


# ----- the registered channel ---------------------------------------------------------------------


def attachment_loader(store: FileStore, sessionmaker: async_sessionmaker[AsyncSession] | None = None
                      ) -> AttachmentLoader:
    """Load a packet file's bytes: a rendered document by its ``application_document`` row, a vault file by
    its ``vault_document`` row. The channel then checks the sha256 against the packet."""

    async def load(f: PacketFile) -> bytes:
        if not f.document_id:
            raise MailConfigError(f"attachment {f.name!r} names no stored document")
        async with (sessionmaker or get_sessionmaker())() as session:
            if f.kind == "vault":
                vault = await session.get(VaultDocument, uuid.UUID(f.document_id))
                key = vault.file_path if vault is not None else None
            else:
                doc = await session.get(ApplicationDocument, uuid.UUID(f.document_id))
                key = doc.file_key if doc is not None else None
        if key is None:
            raise MailConfigError(f"attachment {f.name!r} is not stored")
        return await store.get(key)

    return load


async def factory(session: AsyncSession) -> EmailChannel:
    """The email channel for ``app.apply.channels.registry``: the connected mailbox that sends as the packet's
    identity, attachments from the default file store, the one packet hash."""
    from app.apply.channels.registry import packet_hash as registry_hash
    from app.connect.local_store import default_file_store

    return EmailChannel(attachments=attachment_loader(default_file_store()), hasher=registry_hash)
