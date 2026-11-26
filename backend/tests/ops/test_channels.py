"""Telegram and webhook notifiers (fake transport) and the signature scheme."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.connect.notifier import Button, DeliveryError, OutboundMessage
from app.connect.telegram import TelegramNotifier, format_text
from app.connect.webhook import WebhookNotifier, sign, validate_url, verify_signature
from tests.ops.fakes import FakeTransport, reply

pytestmark = pytest.mark.nodb

TOKEN = "123456789:AAFexampleexampleexample1234"
SECRET = "a-long-shared-secret-value"
MSG = OutboundMessage(event_id="pending:42", kind="pending_action", title="Needs you: Sign in <now>",
                      body="Body & more", created_at=datetime(2026, 11, 26, 9, 0, tzinfo=UTC), link="https://app.example.com/today",
                      buttons=(Button("Approve", "https://app.example.com/today?intent=approve"),
                               Button("Open", "https://app.example.com/today")))


async def test_telegram_sends_html_escaped_text_and_url_buttons() -> None:
    transport = FakeTransport()
    await TelegramNotifier(transport, bot_token=TOKEN, chat_id="555").send(MSG)
    call = transport.calls[0]
    assert call.url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert call.json["chat_id"] == "555" and call.json["parse_mode"] == "HTML"
    assert call.json["text"] == "<b>Needs you: Sign in &lt;now&gt;</b>\nBody &amp; more"
    keyboard = call.json["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in keyboard] == ["Approve", "Open"]
    assert all("url" in b and "callback_data" not in b for b in keyboard), "link buttons only: no remote approve"


async def test_telegram_errors_never_contain_the_token() -> None:
    def boom(call):
        raise ConnectionError(f"could not reach {call.url}")

    with pytest.raises(DeliveryError) as exc:
        await TelegramNotifier(FakeTransport(boom), bot_token=TOKEN, chat_id="1").send(MSG)
    assert TOKEN not in exc.value.detail and TOKEN not in repr(exc.value)

    bad = FakeTransport(lambda c: reply(401, {"ok": False, "description": f"Unauthorized {TOKEN}"}))
    with pytest.raises(DeliveryError) as exc2:
        await TelegramNotifier(bad, bot_token=TOKEN, chat_id="1").send(MSG)
    assert TOKEN not in exc2.value.detail and not exc2.value.retryable

    flaky = FakeTransport(lambda c: reply(502, {"ok": False, "description": "bad gateway"}))
    with pytest.raises(DeliveryError) as exc3:
        await TelegramNotifier(flaky, bot_token=TOKEN, chat_id="1").send(MSG)
    assert exc3.value.retryable


async def test_telegram_check_returns_the_bot_name() -> None:
    transport = FakeTransport(lambda c: reply(200, {"ok": True, "result": {"username": "nchito_test_bot"}}))
    assert await TelegramNotifier(transport, bot_token=TOKEN, chat_id="1").check() == "nchito_test_bot"
    assert transport.calls[0].url.endswith("/getMe")


def test_telegram_text_is_capped() -> None:
    long = OutboundMessage("e", "k", "T", "x" * 9000, datetime.now(UTC))
    assert len(format_text(long)) <= 3800


async def test_webhook_body_headers_and_signature_verify() -> None:
    transport = FakeTransport()
    notifier = WebhookNotifier(transport, url="https://hooks.example.com/in", secret=SECRET,
                               now=lambda: 1_700_000_000)
    await notifier.send(MSG)
    call = transport.calls[0]
    assert call.url == "https://hooks.example.com/in"
    assert call.headers["X-Nchito-Event-Id"] == "pending:42"
    assert call.headers["X-Nchito-Timestamp"] == "1700000000"
    body = json.loads(call.content)
    assert body["id"] == "pending:42" and body["title"].startswith("Needs you") and "payload" not in body
    sig = call.headers["X-Nchito-Signature"]
    assert sig == sign(SECRET, 1_700_000_000, call.content)
    assert verify_signature(SECRET, timestamp="1700000000", signature=sig, body=call.content, now=lambda: 1_700_000_100)


def test_webhook_signature_rejects_tampering_wrong_secret_and_replay() -> None:
    body = b'{"id":"1"}'
    sig = sign(SECRET, 1000, body)
    ok = {"timestamp": "1000", "signature": sig, "now": lambda: 1000}
    assert verify_signature(SECRET, body=body, **ok)
    assert not verify_signature(SECRET, body=b'{"id":"2"}', **ok)
    assert not verify_signature("another-secret-value-1", body=body, **ok)
    assert not verify_signature(SECRET, body=body, timestamp="1000", signature=sig, now=lambda: 1000 + 301)
    assert verify_signature(SECRET, body=body, timestamp="1000", signature=sig, now=lambda: 1000 + 301, tolerance=600)
    assert not verify_signature(SECRET, body=body, timestamp="soon", signature=sig, now=lambda: 1000)
    assert not verify_signature(SECRET, body=body, timestamp="1001", signature=sig, now=lambda: 1001), "ts is signed"


async def test_webhook_failures_are_delivery_errors() -> None:
    notifier = WebhookNotifier(FakeTransport(lambda c: reply(500)), url="https://hooks.example.com/in", secret=SECRET)
    with pytest.raises(DeliveryError) as exc:
        await notifier.send(MSG)
    assert exc.value.retryable
    gone = WebhookNotifier(FakeTransport(lambda c: reply(404)), url="https://hooks.example.com/in", secret=SECRET)
    with pytest.raises(DeliveryError) as exc2:
        await gone.send(MSG)
    assert not exc2.value.retryable


def test_webhook_url_and_secret_rules() -> None:
    assert validate_url("https://hooks.example.com/x")
    assert validate_url("http://localhost:9000/x")
    for bad in ("http://hooks.example.com/x", "ftp://x.example.com", "https://user:pw@x.example.com/", "https:///x"):
        with pytest.raises(ValueError):
            validate_url(bad)
    with pytest.raises(ValueError, match="at least"):
        WebhookNotifier(FakeTransport(), url="https://hooks.example.com/in", secret="short")
