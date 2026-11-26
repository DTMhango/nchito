"""Gmail and IMAP/SMTP mailboxes behind fake transports: idempotency, no resend, refresh, narrow reads."""

# ruff: noqa: E501  (invented fixtures and long assertions)
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from app.connect.gmail import GmailConfig, GmailMailbox, MemoryTokenStore, authorize_url
from app.connect.imap_smtp import ImapSmtpConfig, ImapSmtpMailbox
from app.connect.mail_common import IDEMPOTENCY_HEADER, TransportTimeout, message_id_for, parse_rfc822
from app.connect.mailbox import Attachment, MailAuthError, MailConfigError, MailSendError, OutgoingMail
from tests.mail.helpers import ME, NOW, FakeHttp, FakeImap, FakeSmtp, raw_mail

pytestmark = pytest.mark.nodb

KEY = "11111111-2222-3333-4444-555555555555"
SECRET_BITS = ("access-old", "access-new", "refresh-abc", "client-secret-xyz")


def mail(**kw) -> OutgoingMail:
    return OutgoingMail(to=["hr@acme.example.com"], subject="Application", body_text="Hello", idempotency_key=KEY, **kw)


def gmail(handler, *, tokens=None, config=None, clock=lambda: NOW) -> tuple[GmailMailbox, FakeHttp, MemoryTokenStore]:
    http = FakeHttp(handler)
    store = MemoryTokenStore(tokens or {"access_token": "access-old", "refresh_token": "refresh-abc",
                                        "expires_at": (NOW + timedelta(hours=1)).isoformat()})
    box = GmailMailbox(http=http, tokens=store, client_id="cid", client_secret="client-secret-xyz",
                       config=config or GmailConfig(ME, read_label="Jobs"), clock=clock)
    return box, http, store


def ok_send(method, url, params, json, form, headers):
    if url.endswith("/messages/send"):
        return 200, {"id": "g1", "threadId": "t1"}
    raise AssertionError(url)


async def test_gmail_send_returns_provider_id_and_carries_the_idempotency_key():
    box, http, _ = gmail(ok_send)
    assert await box.send(mail()) == "g1"
    raw = base64.urlsafe_b64decode(http.calls[0]["json"]["raw"])
    sent = parse_rfc822(raw)
    assert sent.headers["x-nchito-idempotency-key"] == KEY
    assert sent.headers["message-id"] == message_id_for(KEY, ME)
    assert http.calls[0]["headers"]["Authorization"] == "Bearer access-old"


async def test_gmail_timeout_after_handoff_is_unknown_and_never_retried():
    def handler(*a):
        raise TransportTimeout("ReadTimeout")

    box, http, _ = gmail(handler)
    assert await box.send(mail()) is None
    assert len(http.calls) == 1  # no second POST


async def test_gmail_server_error_is_unknown_but_client_error_is_a_refusal():
    box, _, _ = gmail(lambda *a: (503, "oops"))
    assert await box.send(mail()) is None
    box, _, _ = gmail(lambda *a: (400, {"error": "bad"}))
    with pytest.raises(MailSendError):
        await box.send(mail())


async def test_gmail_refreshes_an_expiring_token_and_stores_it():
    seen = []

    def handler(method, url, params, json, form, headers):
        seen.append(url)
        if "oauth2.googleapis.com" in url:
            assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "refresh-abc"
            return 200, {"access_token": "access-new", "expires_in": 3600}
        assert headers["Authorization"] == "Bearer access-new"
        return 200, {"id": "g2"}

    tokens = {"access_token": "access-old", "refresh_token": "refresh-abc",
              "expires_at": (NOW + timedelta(seconds=10)).isoformat()}
    box, _, store = gmail(handler, tokens=tokens)
    assert await box.send(mail()) == "g2"
    assert store.tokens["access_token"] == "access-new" and store.tokens["refresh_token"] == "refresh-abc"
    assert sum("oauth2" in u for u in seen) == 1


async def test_gmail_refreshes_once_on_401_then_retries():
    state = {"n": 0}

    def handler(method, url, params, json, form, headers):
        if "oauth2.googleapis.com" in url:
            return 200, {"access_token": "access-new", "expires_in": 3600}
        state["n"] += 1
        return (401, {}) if headers["Authorization"] == "Bearer access-old" else (200, {"id": "g3"})

    box, _, _ = gmail(handler)
    assert await box.send(mail()) == "g3"


async def test_gmail_revoked_refresh_token_is_an_auth_error_without_leaking_tokens():
    def handler(method, url, params, json, form, headers):
        return (400, {"error": "invalid_grant"}) if "oauth2" in url else (401, {})

    box, _, _ = gmail(handler)
    with pytest.raises(MailAuthError) as err:
        await box.send(mail())
    assert not any(bit in str(err.value) for bit in SECRET_BITS)


async def test_gmail_reads_only_the_configured_label_and_query():
    def handler(method, url, params, json, form, headers):
        if url.endswith("/messages"):
            return 200, {"messages": [{"id": "m1"}]}
        raw = raw_mail(sender="hr@acme.example.com", subject="Re: Application", body="Thanks")
        return 200, {"id": "m1", "threadId": "t9", "raw": base64.urlsafe_b64encode(raw).decode()}

    box, http, _ = gmail(handler, config=GmailConfig(ME, read_label="Jobs", read_query="from:acme.example.com"))
    messages = await box.list_messages(NOW - timedelta(days=1))
    q = http.calls[0]["params"]["q"]
    assert 'label:"Jobs"' in q and "(from:acme.example.com)" in q and f"after:{int((NOW - timedelta(days=1)).timestamp())}" in q
    assert messages[0].thread_id == "t9" and messages[0].provider_message_id == "m1"
    assert messages[0].sender == "hr@acme.example.com"


async def test_gmail_without_a_label_or_query_refuses_to_read():
    box, http, _ = gmail(ok_send, config=GmailConfig(ME))
    with pytest.raises(MailConfigError):
        await box.list_messages(NOW)
    assert http.calls == []


async def test_gmail_find_sent_matches_the_key_in_sent_items():
    own = raw_mail(sender=ME, to="hr@acme.example.com", message_id=message_id_for(KEY, ME))
    own = own.replace(b"Subject:", f"{IDEMPOTENCY_HEADER}: {KEY}\r\nSubject:".encode(), 1)

    def handler(method, url, params, json, form, headers):
        if url.endswith("/messages"):
            assert params["q"].startswith("in:sent rfc822msgid:")
            return (200, {"messages": [{"id": "s1"}]}) if KEY in params["q"] else (200, {})
        return 200, {"id": "s1", "threadId": "t", "raw": base64.urlsafe_b64encode(own).decode()}

    box, _, _ = gmail(handler)
    found = await box.find_sent(KEY)
    assert found is not None and found.provider_message_id == "s1"
    assert await box.find_sent("99999999-0000-0000-0000-000000000000") is None


async def test_gmail_check_and_authorize_url_scopes_are_the_narrowest():
    box, _, _ = gmail(lambda m, u, p, j, f, h: (200, {"emailAddress": ME, "messages": []}))
    assert await box.check() is True
    url = authorize_url("cid", "http://testserver/cb", "state1")
    assert "gmail.send" in url and "gmail.readonly" in url and "gmail.modify" not in url and "mail.google.com" not in url


# ----- IMAP / SMTP ----------------------------------------------------------------------------------------


def imap_box(smtp=None, imap=None, **cfg) -> ImapSmtpMailbox:
    return ImapSmtpMailbox(smtp=smtp or FakeSmtp(), imap=imap or FakeImap(),
                           config=ImapSmtpConfig(ME, **({"read_folder": "Jobs"} | cfg)))


async def test_imap_send_builds_exactly_the_mail_with_key_and_attachment():
    smtp = FakeSmtp()
    box = imap_box(smtp=smtp)
    result = await box.send(mail(attachments=[Attachment("cv.pdf", "application/pdf", b"%PDF-1")]))
    assert result == message_id_for(KEY, ME)
    parsed = parse_rfc822(smtp.sent[0])
    assert parsed.headers["x-nchito-idempotency-key"] == KEY
    assert parsed.to == ["hr@acme.example.com"] and parsed.body_text.strip() == "Hello"
    assert b"cv.pdf" in smtp.sent[0]


async def test_imap_timeout_after_accept_is_unknown_and_reconcile_finds_it_in_sent_items():
    smtp = FakeSmtp(mode="timeout_after_accept")
    imap = FakeImap()
    box = imap_box(smtp=smtp, imap=imap)
    assert await box.send(mail()) is None
    assert len(smtp.sent) == 1
    imap.sent.extend(smtp.sent)  # the server put it in Sent
    found = await box.find_sent(KEY)
    assert found is not None and found.headers["x-nchito-idempotency-key"] == KEY


async def test_imap_rejection_is_a_refusal_and_reads_only_the_configured_folder():
    with pytest.raises(MailSendError):
        await imap_box(smtp=FakeSmtp(mode="reject")).send(mail())
    imap = FakeImap(inbox=[raw_mail(sender="hr@acme.example.com")])
    box = imap_box(imap=imap)
    assert len(await box.list_messages(datetime(2026, 1, 1, tzinfo=UTC))) == 1
    assert imap.folders_read == ["Jobs"]
    with pytest.raises(MailConfigError):
        await ImapSmtpMailbox(smtp=FakeSmtp(), imap=FakeImap(), config=ImapSmtpConfig(ME)).list_messages(NOW)
