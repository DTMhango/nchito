"""A follow-up message through an Outlook (Microsoft Graph) mailbox: the real email channel and the Mailbox
abstraction over a fake Graph. It goes out once, as a reply in the application's conversation. Invented data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.apply import dispatch
from app.apply.channels import registry
from app.apply.channels.email import EmailChannel
from app.connect.msgraph_mail import MemoryTokenStore, MsGraphConfig, MsGraphMailbox
from app.core.db import get_sessionmaker
from app.models.applications import DispatchStatus, MailThread
from app.models.followups import OutboundMessage
from tests.followups.helpers import RECRUITER, link_thread, maker, sent_app
from tests.followups.test_messages import LATER, SEND_AT, approve, draft, send
from tests.mail.graph_fake import FakeGraph, inbox_item


async def test_a_follow_up_goes_out_through_outlook_as_a_reply_in_the_conversation(channel):
    app_id = await sent_app()
    thread_id = await link_thread(app_id)
    async with maker()() as s:
        conversation = (await s.get(MailThread, thread_id)).provider_thread_id
    msg_id = await draft(app_id, "info_reply")
    async with maker()() as s:
        msg = await s.get(OutboundMessage, msg_id)
        assert msg.thread_ref == conversation
    packet = await approve(msg_id)
    identity = packet.contents.sending_identity

    graph = FakeGraph()
    graph.inbox.append({**inbox_item(7, sender=RECRUITER), "conversationId": conversation})
    tokens = MemoryTokenStore({"access_token": "access-old", "refresh_token": "refresh-abc",
                               "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
    outlook = MsGraphMailbox(http=graph, tokens=tokens, client_id="cid", client_secret="secret", tenant="common",
                             config=MsGraphConfig(identity, "inbox"), sleep=graph.sleep)

    async def no_files(_f):
        raise AssertionError("a message has no attachments")

    async def resolve(_session, wanted):
        return outlook if wanted == identity else None

    async def factory(_session):
        return EmailChannel(attachments=no_files, sessionmaker=get_sessionmaker(), resolver=resolve)

    registry.register("email", factory, replace=True)
    result = await send(msg_id, now=LATER)
    assert result.status == "queued", result.reason
    async with maker()() as s:
        status = await dispatch.run(s, result.attempt.id, now=SEND_AT)
    assert status == DispatchStatus.sent
    assert graph.replied_to == ["AAMk-in-7"]  # a reply in the conversation, not a new mail
    [out] = graph.sent
    assert out["subject"] == packet.contents.email.subject
    assert [r["emailAddress"]["address"] for r in out["toRecipients"]] == [RECRUITER]
