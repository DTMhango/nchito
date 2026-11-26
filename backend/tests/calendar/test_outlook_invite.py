"""An interview invitation read from an Outlook (Microsoft Graph) mailbox: its ``.ics`` attachment reaches the
calendar as a proposal, exactly as from Gmail or IMAP. Fake Graph, invented data."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from app.connect.msgraph_mail import MemoryTokenStore, MsGraphConfig, MsGraphMailbox
from app.core.settings import service as settings_service
from app.pipeline import events as svc
from tests.calendar.helpers import ics_invite, make_job_app
from tests.mail.graph_fake import OWNER, FakeGraph, inbox_item


async def test_an_outlook_ics_attachment_becomes_a_proposal(session) -> None:
    _, app = await make_job_app(session)
    graph = FakeGraph()
    ics = ics_invite(uid="outlook-1@acme.example.com")
    graph.inbox.append({**inbox_item(1, subject="Interview invitation"), "hasAttachments": True})
    graph.attachments["AAMk-in-1"] = [{
        "@odata.type": "#microsoft.graph.fileAttachment", "name": "invite.ics", "contentType": "text/calendar",
        "size": len(ics), "contentBytes": base64.b64encode(ics).decode()}]
    tokens = MemoryTokenStore({"access_token": "access-old", "refresh_token": "refresh-abc",
                               "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
    box = MsGraphMailbox(http=graph, tokens=tokens, client_id="cid", client_secret="secret", tenant="common",
                         config=MsGraphConfig(OWNER, "inbox"), sleep=graph.sleep)
    [msg] = await box.list_messages(datetime(2026, 11, 1, tzinfo=UTC))
    ev = await svc.propose_from_message(session, app, msg, values=await settings_service.values(session))
    await session.commit()
    assert ev is not None and ev.status == "proposed" and ev.source == "mail"
    assert ev.ics_uid == "outlook-1@acme.example.com"
    assert ev.starts_at == datetime(2026, 12, 3, 12, 30, tzinfo=UTC)
