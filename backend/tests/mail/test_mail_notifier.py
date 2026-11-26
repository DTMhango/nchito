"""The email notifier mails the owner's own mailbox once per event, links only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.connect import notifier
from app.connect.mail_notifier import EmailNotifier
from app.connect.notifier import Button, DeliveryError, OutboundMessage
from tests.mail.helpers import ME, FakeMailbox

pytestmark = pytest.mark.nodb

MSG = OutboundMessage(event_id="ev-1", kind="needs_you", title="Needs you: approve a packet", body="1 approval",
                      created_at=datetime(2026, 11, 26, tzinfo=UTC), link="/pending",
                      buttons=(Button("Open", "/applications/x"),))


async def test_mails_itself_once_per_event_with_links():
    box = FakeMailbox()
    n = EmailNotifier(box, ME)
    await n.send(MSG)
    await n.send(MSG)  # a retry after the first one reached sent items
    assert len(box.sent) == 1
    mail = box.sent[0]
    assert list(mail.to) == [ME] and mail.subject == MSG.title and "/pending" in mail.body_text
    assert "Open: http" in mail.body_text and mail.idempotency_key == "notify-ev-1"
    assert "email" in notifier.registered_channels()


async def test_a_refused_message_is_a_delivery_error():
    with pytest.raises(DeliveryError):
        await EmailNotifier(FakeMailbox(mode="refuse"), ME).send(MSG)
