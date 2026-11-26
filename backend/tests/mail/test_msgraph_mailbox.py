"""Outlook mailbox over a fake Microsoft Graph: idempotency, no resend, find_sent, refresh, paging, 429, secrets."""

# ruff: noqa: E501  (invented fixtures and long assertions)
from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.connect import msgraph_auth
from app.connect.mail_common import IDEMPOTENCY_HEADER, TransportTimeout, message_id_for
from app.connect.mailbox import (
    Attachment,
    MailAuthError,
    Mailbox,
    MailConfigError,
    MailError,
    MailSendError,
    OutgoingMail,
)
from app.connect.msgraph_mail import MemoryTokenStore, MsGraphConfig, MsGraphMailbox, exchange_code
from tests.mail.graph_fake import EMPLOYER, OWNER, FakeGraph, inbox_item

pytestmark = pytest.mark.nodb

KEY = "11111111-2222-3333-4444-555555555555"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
SECRETS = ("access-old", "access-new-1", "refresh-abc", "client-secret-xyz")


def mail(**kw) -> OutgoingMail:
    return OutgoingMail(to=[EMPLOYER], subject="Application", body_text="Hello", idempotency_key=KEY, **kw)


def outlook(graph: FakeGraph | None = None, *, folder: str | None = "Jobs", tokens=None, expires_in=timedelta(hours=1)):
    graph = graph or FakeGraph()
    store = MemoryTokenStore(tokens or {"access_token": "access-old", "refresh_token": "refresh-abc",
                                        "expires_at": (NOW + expires_in).isoformat()})
    box = MsGraphMailbox(http=graph, tokens=store, client_id="cid", client_secret="client-secret-xyz", tenant="common",
                         config=MsGraphConfig(OWNER, folder), clock=lambda: NOW, sleep=graph.sleep)
    return box, graph, store


def test_it_is_a_mailbox():
    assert isinstance(outlook()[0], Mailbox)


# ----- send -------------------------------------------------------------------------------------


async def test_send_creates_a_draft_with_our_message_id_and_header_then_sends_it_once():
    box, g, _ = outlook()
    att = Attachment("cv.pdf", "application/pdf", b"%PDF invented")
    sent_id = await box.send(mail(attachments=[att], cc=["boss@acme.example.com"]))
    assert sent_id == message_id_for(KEY, OWNER)
    draft = g.drafts["AAMk-draft-1"]
    assert draft["internetMessageId"] == message_id_for(KEY, OWNER)
    assert draft["internetMessageHeaders"] == [{"name": IDEMPOTENCY_HEADER, "value": KEY}]
    assert draft["toRecipients"] == [{"emailAddress": {"address": EMPLOYER}}]
    assert draft["ccRecipients"] == [{"emailAddress": {"address": "boss@acme.example.com"}}]
    assert draft["body"] == {"contentType": "Text", "content": "Hello"}
    assert base64.b64decode(draft["attachments"][0]["contentBytes"]) == b"%PDF invented"
    assert draft["attachments"][0]["name"] == "cv.pdf"
    assert [c["method"] + " " + c["url"].removeprefix("https://graph.microsoft.com/v1.0") for c in g.calls] == [
        "POST /me/messages", "POST /me/messages/AAMk-draft-1/send"]
    assert all(c["headers"]["Authorization"] == "Bearer access-old" for c in g.calls)
    assert len(g.sent) == 1


async def test_a_timeout_on_the_send_call_is_unknown_never_retried_and_settled_from_sent_items():
    box, g, _ = outlook()
    g.send_mode = "timeout_after_accept"
    assert await box.send(mail()) is None
    assert g.urls("POST").count("https://graph.microsoft.com/v1.0/me/messages/AAMk-draft-1/send") == 1
    found = await box.find_sent(KEY)  # Graph did take it: Sent Items settles the question
    assert found is not None and found.provider_message_id == message_id_for(KEY, OWNER)
    assert len(g.sent) == 1


async def test_a_timeout_before_the_message_left_is_still_never_retried():
    box, g, _ = outlook()
    g.send_mode = "timeout_before"
    assert await box.send(mail()) is None
    assert len(g.sent) == 0 and [c["method"] for c in g.calls].count("POST") == 2
    assert await box.find_sent(KEY) is None


@pytest.mark.parametrize("mode", ["500", "429"])
async def test_throttling_or_a_server_error_on_the_send_call_is_unknown_without_waiting_or_retrying(mode):
    box, g, _ = outlook()
    g.send_mode = mode
    assert await box.send(mail()) is None
    assert g.sleeps == [] and [c["url"].endswith("/send") for c in g.calls].count(True) == 1


async def test_a_client_error_on_the_send_call_is_a_refusal_and_the_draft_is_removed():
    box, g, _ = outlook()
    g.send_mode = "400"
    with pytest.raises(MailSendError):
        await box.send(mail())
    assert g.deleted == ["AAMk-draft-1"]


@pytest.mark.parametrize("failure", [400, 503, "timeout"])
async def test_a_failed_draft_is_a_clean_refusal_and_nothing_is_sent(failure):
    box, g, _ = outlook()
    g.draft_failure = failure
    with pytest.raises(MailSendError):
        await box.send(mail())
    assert not any(u.endswith("/send") for u in g.urls()) and g.sent == []


async def test_a_429_while_preparing_the_draft_waits_retry_after_and_repeats():
    box, g, _ = outlook()
    g.throttle["POST /me/messages"] = 2
    assert await box.send(mail()) == message_id_for(KEY, OWNER)
    assert g.sleeps == [3.0, 3.0] and len(g.sent) == 1


async def test_oversized_attachments_are_refused_before_any_call():
    box, g, _ = outlook()
    with pytest.raises(MailSendError):
        await box.send(mail(attachments=[Attachment("big.pdf", "application/pdf", b"x" * 3_000_001)]))
    assert g.calls == []


async def test_a_mail_without_a_key_still_sends_and_returns_a_message_id():
    box, g, _ = outlook()
    assert await box.send(OutgoingMail(to=[EMPLOYER], subject="s", body_text="b")) == "<graph-made@outlook.example>"
    assert "internetMessageHeaders" not in g.drafts["AAMk-draft-1"]


# ----- find_sent --------------------------------------------------------------------------------


async def test_find_sent_by_message_id_in_sent_items_only():
    box, g, _ = outlook()
    await box.send(mail())
    assert (await box.find_sent(KEY)) is not None
    assert await box.find_sent("99999999-0000-0000-0000-000000000000") is None
    assert all("/mailFolders/sentitems/messages" in u for u in g.urls("GET"))


async def test_find_sent_falls_back_to_the_key_header_when_exchange_rewrote_the_message_id():
    box, g, _ = outlook()
    g.rewrite_message_id = True
    await box.send(mail())
    found = await box.find_sent(KEY)
    assert found is not None and found.headers["message-id"] == "<rewritten@outlook.example>"
    assert found.headers["x-nchito-idempotency-key"] == KEY


# ----- tokens -----------------------------------------------------------------------------------


async def test_an_expiring_token_is_refreshed_and_stored():
    box, g, store = outlook(expires_in=timedelta(seconds=10))
    await box.send(mail())
    assert g.refresh_count == 1 and store.tokens["access_token"] == "access-new-1"
    assert store.tokens["refresh_token"] == "refresh-abc"  # Microsoft sent no new one: the old one stays
    token_call = next(c for c in g.calls if "/oauth2/v2.0/token" in c["url"])
    assert token_call["form"]["grant_type"] == "refresh_token" and token_call["form"]["client_secret"] == "client-secret-xyz"
    assert "Mail.Send" in token_call["form"]["scope"]


async def test_a_401_refreshes_once_and_repeats_the_call():
    box, g, store = outlook(tokens={"access_token": "stale", "refresh_token": "refresh-abc",
                                    "expires_at": (NOW + timedelta(hours=1)).isoformat()})
    assert await box.check() is True
    assert g.refresh_count == 1 and store.tokens["access_token"] == "access-new-1"


async def test_a_refused_refresh_token_means_reconnect_and_nothing_is_sent():
    box, g, _ = outlook(tokens={"access_token": "stale", "refresh_token": "revoked",
                                "expires_at": (NOW - timedelta(hours=1)).isoformat()})
    with pytest.raises(MailAuthError):
        await box.send(mail())
    assert g.sent == []


async def test_missing_refresh_token_is_an_auth_error():
    box, _, _ = outlook(tokens={"access_token": "x"})
    with pytest.raises(MailAuthError):
        await box.send(mail())


# ----- reading ----------------------------------------------------------------------------------


async def test_list_messages_reads_only_the_configured_folder_oldest_first_and_pages_with_nextlink():
    box, g, _ = outlook()
    g.inbox = [inbox_item(n) for n in (5, 1, 4, 2, 3)]
    got = await box.list_messages(datetime(2026, 11, 22, tzinfo=UTC), limit=200)
    assert [m.subject for m in got] == ["Re: your application"] * 4
    assert [m.provider_message_id for m in got] == [f"AAMk-in-{n}" for n in (2, 3, 4, 5)]
    assert [m.received_at for m in got] == sorted(m.received_at for m in got)
    reads = [u for u in g.urls("GET") if "/messages" in u]
    assert len(reads) == 2 and all("/mailFolders/AAMk-jobs/messages" in u for u in reads)  # 4 rows, page of 2: two calls, next link followed
    first = next(c for c in g.calls if "AAMk-jobs/messages" in c["url"])
    assert first["params"]["$filter"] == "receivedDateTime ge 2026-11-22T00:00:00Z"
    assert got[0].sender == EMPLOYER and got[0].to == [OWNER] and got[0].thread_id == "conv-2"


async def test_list_messages_stops_at_the_limit():
    box, g, _ = outlook()
    g.inbox = [inbox_item(n) for n in (1, 2, 3, 4, 5)]
    got = await box.list_messages(datetime(2026, 11, 1, tzinfo=UTC), limit=3)
    assert [m.provider_message_id for m in got] == ["AAMk-in-1", "AAMk-in-2", "AAMk-in-3"]


async def test_html_bodies_become_text_and_headers_are_kept_lowercased():
    box, g, _ = outlook(folder="inbox")
    g.inbox = [inbox_item(1, html=True, headers=[{"name": "In-Reply-To", "value": "<sent@example.com>"},
                                                 {"name": "Received", "value": "ignored"}])]
    (m,) = await box.list_messages(datetime(2026, 11, 1, tzinfo=UTC))
    assert "Hello" in m.body_text and "<p>" not in m.body_text and m.body_html.startswith("<p>")
    assert m.headers["in-reply-to"] == "<sent@example.com>" and "received" not in m.headers
    assert m.headers["message-id"] == "<in-1@mail.example.com>"
    assert not any("displayName" in str(c["params"]) for c in g.calls)  # a well-known folder needs no lookup


async def test_reading_needs_a_configured_folder_and_a_missing_folder_is_an_error():
    box, g, _ = outlook(folder=None)
    with pytest.raises(MailConfigError):
        await box.list_messages(NOW)
    assert g.calls == []
    box, _, _ = outlook(folder="Nope")
    with pytest.raises(MailConfigError):
        await box.list_messages(NOW)


async def test_a_429_on_a_read_waits_and_repeats_but_a_huge_retry_after_gives_up():
    box, g, _ = outlook()
    g.inbox = [inbox_item(1)]
    g.throttle["GET"] = 1
    got = await box.list_messages(datetime(2026, 11, 1, tzinfo=UTC))
    assert len(got) == 1 and g.sleeps == [3.0]
    box, g, _ = outlook()
    g.throttle["GET"] = 5
    g.retry_after = "900"
    with pytest.raises(MailError, match="throttling"):
        await box.list_messages(NOW)
    assert g.sleeps == []


async def test_a_link_outside_graph_is_never_followed():
    box, g, _ = outlook()
    with pytest.raises(MailError):
        await box._call("GET", "https://evil.example.com/steal")
    assert g.calls == []


# ----- check ------------------------------------------------------------------------------------


async def test_check_is_true_when_signed_in_and_the_folder_is_readable():
    box, g, _ = outlook()
    g.inbox = []
    assert await box.check() is True


async def test_check_is_false_for_an_unknown_folder_or_a_dead_refresh_token():
    assert await outlook(folder="Nope")[0].check() is False
    assert await outlook(tokens={"access_token": "x", "refresh_token": "revoked", "expires_at": (NOW - timedelta(hours=1)).isoformat()})[0].check() is False


# ----- sign-in helpers and secrets --------------------------------------------------------------


def test_authorize_url_asks_for_the_narrowest_scopes_and_the_chosen_tenant():
    url = msgraph_auth.authorize_url(tenant="consumers", client_id="cid", redirect_uri="https://x.example/cb", state="s",
                                     scopes=msgraph_auth.MAIL_SCOPES)
    assert url.startswith("https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?")
    from urllib.parse import parse_qs, urlsplit

    q = parse_qs(urlsplit(url).query)
    assert q["scope"][0].split() == ["offline_access", "User.Read", "Mail.Send", "Mail.Read"]
    assert "client_secret" not in url


async def test_exchange_code_returns_tokens_and_requires_a_refresh_token_and_the_send_scope():
    g = FakeGraph()

    def handler(method, url, params, json, form, headers):
        assert form["grant_type"] == "authorization_code" and form["code"] == "c1"
        return 200, {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600, "scope": "Mail.Send Mail.Read User.Read"}

    g.handle = handler
    tokens = await exchange_code(g, tenant="common", client_id="cid", client_secret="s", redirect_uri="https://x/cb", code="c1", now=NOW)
    assert tokens["refresh_token"] == "r1" and tokens["expires_at"] == (NOW + timedelta(hours=1)).isoformat()
    g.handle = lambda *a: (200, {"access_token": "a1", "expires_in": 3600, "scope": "Mail.Send"})
    with pytest.raises(MailAuthError, match="refresh token"):
        await exchange_code(g, tenant="common", client_id="cid", client_secret="s", redirect_uri="https://x/cb", code="c1")
    g.handle = lambda *a: (200, {"access_token": "a1", "refresh_token": "r", "scope": "User.Read"})
    with pytest.raises(MailAuthError, match=r"Mail.Send"):
        await exchange_code(g, tenant="common", client_id="cid", client_secret="s", redirect_uri="https://x/cb", code="c1")
    g.handle = lambda *a: (400, {"error": "invalid_grant", "error_description": "secret details"})
    with pytest.raises(MailAuthError) as err:
        await exchange_code(g, tenant="common", client_id="cid", client_secret="s", redirect_uri="https://x/cb", code="c1")
    assert "secret details" not in str(err.value)

    def boom(*a):
        raise TransportTimeout("x")

    g.handle = boom
    with pytest.raises(MailError):
        await exchange_code(g, tenant="common", client_id="cid", client_secret="s", redirect_uri="https://x/cb", code="c1")


async def test_no_secret_appears_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    box, g, _ = outlook(expires_in=timedelta(seconds=10))
    g.send_mode = "400"
    with pytest.raises(MailSendError) as e1:
        await box.send(mail())
    box2, _, _ = outlook(tokens={"access_token": "x", "refresh_token": "revoked", "expires_at": (NOW - timedelta(hours=1)).isoformat()})
    with pytest.raises(MailAuthError) as e2:
        await box2.send(mail())
    text = f"{e1.value} {e2.value} {caplog.text}"
    assert not any(secret in text for secret in (*SECRETS, "revoked"))
