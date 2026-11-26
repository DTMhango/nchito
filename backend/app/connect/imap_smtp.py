"""Generic IMAP + SMTP ``Mailbox`` (app password). DESIGN.md 12, 18.3.

Reads only the configured folder (``read_folder``); sent items are searched by the idempotency header.
The real transports use the standard library (``smtplib``, ``imaplib``) in worker threads; tests inject
fakes through the ``SmtpTransport`` / ``ImapTransport`` Protocols. The password never leaves the
transport objects and is never logged.
"""

from __future__ import annotations

import asyncio
import imaplib
import smtplib
import ssl
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.connect.mail_common import (
    IDEMPOTENCY_HEADER,
    ImapTransport,
    RawMail,
    SmtpRejected,
    SmtpTransport,
    TransportTimeout,
    build_mime,
    message_id_for,
    parse_rfc822,
)
from app.connect.mailbox import MailAuthError, MailConfigError, MailError, MailMessage, MailSendError, OutgoingMail

IMAP_DATE = "%d-%b-%Y"


@dataclass(frozen=True)
class ImapSmtpConfig:
    from_address: str
    read_folder: str | None = None
    sent_folder: str = "Sent"


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    security: Literal["ssl", "starttls", "none"]
    username: str
    password: str
    timeout_seconds: float = 30.0


class ImapSmtpMailbox:
    def __init__(self, *, smtp: SmtpTransport, imap: ImapTransport, config: ImapSmtpConfig) -> None:
        self._smtp = smtp
        self._imap = imap
        self.config = config
        self.from_address = config.from_address

    async def send(self, mail: OutgoingMail) -> str | None:
        message_id = message_id_for(mail.idempotency_key, self.from_address) if mail.idempotency_key else None
        msg = build_mime(mail, self.from_address, reply_to_message_id=mail.thread_id)
        recipients = [*mail.to, *mail.cc]
        try:
            await self._smtp.send(msg.as_bytes(), self.from_address, recipients)
        except SmtpRejected as exc:
            raise MailSendError(str(exc)) from exc
        except TransportTimeout:
            return None
        return message_id or str(msg["Message-ID"] or "")

    async def list_messages(self, since: datetime, *, limit: int = 200) -> list[MailMessage]:
        if not self.config.read_folder:
            raise MailConfigError("set the folder this connection may read")
        raws = await self._imap.fetch_since(self.config.read_folder, since, limit)
        return [parse_rfc822(r.raw) for r in raws]

    async def find_sent(self, idempotency_key: str) -> MailMessage | None:
        for raw in await self._imap.find_by_header(self.config.sent_folder, IDEMPOTENCY_HEADER, idempotency_key):
            message = parse_rfc822(raw.raw)
            if message.headers.get(IDEMPOTENCY_HEADER.lower()) == idempotency_key:
                return message
        return None

    async def check(self) -> bool:
        try:
            return await self._imap.check(self.config.read_folder or self.config.sent_folder)
        except (MailError, TransportTimeout, OSError):
            return False


# ----- real transports ------------------------------------------------------------------------


class StdlibSmtp:
    def __init__(self, server: ServerSettings) -> None:
        self.server = server

    async def send(self, raw: bytes, sender: str, recipients: Sequence[str]) -> None:
        await asyncio.to_thread(self._send, raw, sender, list(recipients))

    def _send(self, raw: bytes, sender: str, recipients: list[str]) -> None:
        s = self.server
        try:
            if s.security == "ssl":
                client: smtplib.SMTP = smtplib.SMTP_SSL(s.host, s.port, timeout=s.timeout_seconds,
                                                         context=ssl.create_default_context())
            else:
                client = smtplib.SMTP(s.host, s.port, timeout=s.timeout_seconds)
            with client:
                if s.security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                client.login(s.username, s.password)
                refused = client.sendmail(sender, recipients, raw)
        except smtplib.SMTPAuthenticationError as exc:
            raise SmtpRejected("the mail server refused the username or password") from exc
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPHeloError,
                smtplib.SMTPConnectError) as exc:
            raise SmtpRejected(f"the mail server refused the message ({type(exc).__name__})") from exc
        except (TimeoutError, smtplib.SMTPServerDisconnected) as exc:
            raise TransportTimeout(type(exc).__name__) from exc  # may have been accepted: unknown
        except smtplib.SMTPResponseException as exc:
            raise SmtpRejected(f"the mail server refused the message (code {exc.smtp_code})") from exc
        if refused:
            raise SmtpRejected("the mail server refused some recipients")


class StdlibImap:
    def __init__(self, server: ServerSettings) -> None:
        self.server = server

    def _connect(self, folder: str) -> imaplib.IMAP4:
        s = self.server
        try:
            if s.security == "ssl":
                client: imaplib.IMAP4 = imaplib.IMAP4_SSL(s.host, s.port, timeout=s.timeout_seconds,
                                                          ssl_context=ssl.create_default_context())
            else:
                client = imaplib.IMAP4(s.host, s.port, timeout=s.timeout_seconds)
                if s.security == "starttls":
                    client.starttls(ssl.create_default_context())
            client.login(s.username, s.password)
        except imaplib.IMAP4.error as exc:
            raise MailAuthError("the mail server refused the username or password") from exc
        except TimeoutError as exc:
            raise TransportTimeout(type(exc).__name__) from exc
        status, _ = client.select(f'"{folder}"', readonly=True)
        if status != "OK":
            client.logout()
            raise MailConfigError(f"folder {folder!r} cannot be opened")
        return client

    @staticmethod
    def _fetch(client: imaplib.IMAP4, uids: list[bytes], limit: int) -> list[RawMail]:
        out: list[RawMail] = []
        for uid in uids[-limit:]:
            status, data = client.uid("FETCH", uid.decode(), "(BODY.PEEK[])")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue
            out.append(RawMail(uid.decode(), bytes(data[0][1])))
        return out

    async def fetch_since(self, folder: str, since: datetime, limit: int) -> list[RawMail]:
        return await asyncio.to_thread(self._fetch_since, folder, since, limit)

    def _fetch_since(self, folder: str, since: datetime, limit: int) -> list[RawMail]:
        client = self._connect(folder)
        try:
            day = (since - timedelta(days=1)).astimezone(UTC).strftime(IMAP_DATE)  # SINCE has day precision
            status, data = client.uid("SEARCH", None, "SINCE", day)
            uids = data[0].split() if status == "OK" and data and data[0] else []
            mails = self._fetch(client, uids, limit)
        finally:
            client.logout()
        return [m for m in mails if parse_rfc822(m.raw).received_at >= since]

    async def find_by_header(self, folder: str, header: str, value: str) -> list[RawMail]:
        return await asyncio.to_thread(self._find_by_header, folder, header, value)

    def _find_by_header(self, folder: str, header: str, value: str) -> list[RawMail]:
        client = self._connect(folder)
        try:
            status, data = client.uid("SEARCH", None, "HEADER", header, f'"{value}"')
            uids = data[0].split() if status == "OK" and data and data[0] else []
            return self._fetch(client, uids, 5)
        finally:
            client.logout()

    async def check(self, folder: str) -> bool:
        def run() -> bool:
            self._connect(folder).logout()
            return True

        return await asyncio.to_thread(run)
