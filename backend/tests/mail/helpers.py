"""Fakes and factories for the mail tests. Everything is invented (example.com); nothing touches a network."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply.channels.base import DispatchRequest
from app.apply.channels.email import packet_hash
from app.connect.mail_common import HttpResult, RawMail, SmtpRejected, TransportTimeout
from app.connect.mailbox import MailMessage, MailSendError, OutgoingMail
from app.core.clock import utcnow
from app.models.applications import (
    Application,
    ApplicationPacket,
    Channel,
    DispatchAttempt,
    DispatchStatus,
    Stage,
    SubmitPermit,
)
from app.models.search import Job
from app.schemas.json_types import PacketContents, PacketDestination, PacketEmail, PacketFile

ME = "me@example.com"
EMPLOYER_ADDRESS = "hr@acme.example.com"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


class FakeHttp:
    """Scripted HTTP transport: ``handler(method, url, params, json, form, headers)`` returns (status, data)."""

    def __init__(self, handler: Callable[..., tuple[int, Any]]) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                      params: Mapping[str, Any] | None = None, json: Any = None,
                      form: Mapping[str, str] | None = None) -> HttpResult:
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "params": dict(params or {}),
                           "json": json, "form": dict(form or {})})
        status, data = self.handler(method, url, params or {}, json, form or {}, headers or {})
        return HttpResult(status, data)


class FakeSmtp:
    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode  # ok | reject | timeout_after_accept | timeout_before
        self.sent: list[bytes] = []

    async def send(self, raw: bytes, sender: str, recipients: Sequence[str]) -> None:
        if self.mode == "reject":
            raise SmtpRejected("refused")
        if self.mode == "timeout_before":
            raise TransportTimeout("TimeoutError")
        self.sent.append(raw)
        if self.mode == "timeout_after_accept":
            raise TransportTimeout("TimeoutError")  # the server took it, the answer was lost


class FakeImap:
    def __init__(self, inbox: list[bytes] | None = None, sent: list[bytes] | None = None) -> None:
        self.inbox = inbox if inbox is not None else []
        self.sent = sent if sent is not None else []
        self.folders_read: list[str] = []
        self.ok = True

    async def fetch_since(self, folder: str, since: datetime, limit: int) -> list[RawMail]:
        self.folders_read.append(folder)
        return [RawMail(str(i), raw) for i, raw in enumerate(self.inbox)][:limit]

    async def find_by_header(self, folder: str, header: str, value: str) -> list[RawMail]:
        self.folders_read.append(folder)
        return [RawMail(str(i), raw) for i, raw in enumerate(self.sent) if value.encode() in raw]

    async def check(self, folder: str) -> bool:
        return self.ok


class FakeMailbox:
    """A ``Mailbox`` with a sent-items store. ``mode``: ok | timeout (accepted, answer lost) | refuse."""

    def __init__(self, mode: str = "ok", from_address: str = ME) -> None:
        self.mode = mode
        self.from_address = from_address
        self.sent: list[OutgoingMail] = []
        self.sent_ids: dict[str, str] = {}
        self.inbox: list[MailMessage] = []
        self.list_calls = 0

    async def send(self, mail: OutgoingMail) -> str | None:
        if self.mode == "refuse":
            raise MailSendError("refused")
        self.sent.append(mail)
        message_id = f"gm-{len(self.sent)}"
        if mail.idempotency_key:
            self.sent_ids[mail.idempotency_key] = message_id
        return None if self.mode == "timeout" else message_id

    async def list_messages(self, since: datetime, *, limit: int = 200) -> list[MailMessage]:
        self.list_calls += 1
        return [m for m in self.inbox if m.received_at >= since][:limit]

    async def find_sent(self, idempotency_key: str) -> MailMessage | None:
        message_id = self.sent_ids.get(idempotency_key)
        if message_id is None:
            return None
        return MailMessage(message_id, "t", self.from_address, ["x@example.com"], "s", NOW, "b",
                           {"x-nchito-idempotency-key": idempotency_key})

    async def check(self) -> bool:
        return True


def raw_mail(*, sender: str, to: str = ME, subject: str = "Hello", body: str = "Body", message_id: str | None = None,
             references: str | None = None, in_reply_to: str | None = None,
             date: str = "Thu, 26 Nov 2026 10:00:00 +0000", html: str | None = None) -> bytes:
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, to, subject, date
    m["Message-ID"] = message_id or f"<{uuid.uuid4().hex}@mail.example.com>"
    if references:
        m["References"] = references
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


def inbound(*, sender: str = EMPLOYER_ADDRESS, subject: str = "Re: your application", body: str = "Hello",
            message_id: str | None = None, thread_id: str = "thread-1", headers: dict[str, str] | None = None,
            received: datetime = NOW, html: str = "") -> MailMessage:
    return MailMessage(provider_message_id=message_id or uuid.uuid4().hex, thread_id=thread_id, sender=sender,
                       to=[ME], subject=subject, received_at=received, body_text=body, headers=headers or {},
                       body_html=html)


def make_packet(*, to: Sequence[str] = (EMPLOYER_ADDRESS,), files: Sequence[PacketFile] = (),
                requisition: str | None = "REQ-77", identity: str = ME,
                body: str = "Dear team, I apply.") -> PacketContents:
    return PacketContents(
        requisition=requisition,
        destination=PacketDestination(url=f"mailto:{to[0]}", domain=to[0].split("@")[1], verified=True),
        sending_identity=identity, email=PacketEmail(to=list(to), subject="Application: Data Analyst", body=body),
        files=list(files))


def file_for(content: bytes, name: str = "cv.pdf", kind: str = "cv") -> PacketFile:
    return PacketFile(name=name, kind=kind, sha256=hashlib.sha256(content).hexdigest())  # type: ignore[arg-type]


class Setup:
    def __init__(self, app: Application, packet_row: ApplicationPacket, attempt: DispatchAttempt,
                 permit: SubmitPermit | None, contents: PacketContents) -> None:
        self.app, self.packet_row, self.attempt, self.permit, self.contents = app, packet_row, attempt, permit, contents

    def request(self, **over: Any) -> DispatchRequest:
        return DispatchRequest(attempt_id=str(self.attempt.id), application_id=str(self.app.id),
                               packet_hash=over.pop("packet_hash", self.packet_row.content_hash),
                               packet=over.pop("packet", self.contents))


async def make_setup(session: AsyncSession, *, contents: PacketContents | None = None, permit_used: bool = True,
                     with_permit: bool = True, status: DispatchStatus = DispatchStatus.reserved,
                     stage: Stage = Stage.applying, employer: str = "Acme Ltd", applied: bool = False) -> Setup:
    contents = contents or make_packet()
    job = Job(title="Data Analyst", employer=employer, canonical_employer=employer,
              content_hash=uuid.uuid4().hex.ljust(64, "0"))
    session.add(job)
    await session.flush()
    app = Application(job_id=job.id, stage=stage, applied_at=NOW if applied else None)
    session.add(app)
    await session.flush()
    digest = packet_hash(contents)
    packet = ApplicationPacket(application_id=app.id, version=1, content_hash=digest, contents=contents,
                               approved_at=utcnow(), approved_by="owner")
    session.add(packet)
    await session.flush()
    app.approved_packet_id = packet.id
    permit = None
    if with_permit:
        permit = SubmitPermit(application_id=app.id, packet_id=packet.id, packet_hash=digest, issued_at=utcnow(),
                              expires_at=utcnow(), used_at=utcnow() if permit_used else None)
        session.add(permit)
        await session.flush()
    attempt = DispatchAttempt(application_id=app.id, packet_id=packet.id, packet_hash=digest, channel=Channel.email,
                              permit_id=permit.id if permit else None, status=status)
    session.add(attempt)
    await session.flush()
    await session.commit()
    return Setup(app, packet, attempt, permit, contents)
