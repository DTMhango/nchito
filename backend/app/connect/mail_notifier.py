"""The ``email`` notifier: notifications and the digest are mailed to the owner's own connected mailbox.

The message goes from the mailbox to its own address (no other recipient is possible), carries only
the title, short body and links of the ``OutboundMessage``, and uses the event id as its idempotency
key, so a retried delivery that already reached sent items is not mailed twice.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import mail_connections
from app.connect.mailbox import Mailbox, MailError, OutgoingMail
from app.connect.notifier import DeliveryError, Notifier, OutboundMessage, register_notifier_factory
from app.core.config import get_config


def _absolute(link: str) -> str:
    return link if link.startswith(("http://", "https://")) else f"{get_config().base_origin}{link}"


class EmailNotifier:
    channel = "email"

    def __init__(self, mailbox: Mailbox, address: str) -> None:
        self._mailbox = mailbox
        self._address = address

    async def send(self, message: OutboundMessage) -> None:
        lines = [message.body or ""]
        if message.link:
            lines.append(_absolute(message.link))
        lines += [f"{b.label}: {_absolute(b.url)}" for b in message.buttons]
        mail = OutgoingMail(to=[self._address], subject=message.title, body_text="\n\n".join(x for x in lines if x),
                            idempotency_key=f"notify-{message.event_id}")
        try:
            if await self._mailbox.find_sent(mail.idempotency_key or "") is not None:
                return
            await self._mailbox.send(mail)
        except MailError as exc:
            raise DeliveryError(f"the mailbox did not accept the message ({type(exc).__name__})") from exc


async def email_factory(session: AsyncSession) -> Notifier | None:
    for conn in await mail_connections.mail_connections(session):
        address = str(conn.config.get("from_address") or "").strip()
        if address:
            try:
                return EmailNotifier(mail_connections.build_mailbox(conn), address)
            except (MailError, KeyError, ValueError):
                return None
    return None


register_notifier_factory("email", email_factory)
