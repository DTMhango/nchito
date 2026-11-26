"""Generic signed webhook notifier.

Each POST carries a JSON body and these headers:

- ``X-Nchito-Timestamp``: unix seconds when it was signed.
- ``X-Nchito-Event-Id``: the idempotency key; a receiver may drop a repeat.
- ``X-Nchito-Signature``: ``sha256=<hex>``, HMAC-SHA256 of ``"<timestamp>.<body>"`` with the shared secret.

``verify_signature`` is the receiver's check (and what the tests use): constant-time compare and
a tolerance window against replays.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from app.connect.http_transport import HttpTransport
from app.connect.notifier import DeliveryError, OutboundMessage

TOLERANCE_SECONDS = 300
MIN_SECRET_LENGTH = 16


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("webhook url must be https (http only for localhost)")
    if not parts.hostname:
        raise ValueError("webhook url has no host")
    if parts.username or parts.password:
        raise ValueError("put credentials in the signing secret, not in the url")
    return url


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_signature(secret: str, *, timestamp: str, signature: str, body: bytes,
                     now: Callable[[], float] = time.time, tolerance: int = TOLERANCE_SECONDS) -> bool:
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(now() - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, ts, body), signature)


def payload_of(message: OutboundMessage) -> dict[str, object]:
    return {"id": message.event_id, "kind": message.kind, "title": message.title, "body": message.body,
            "link": message.link, "buttons": [{"label": b.label, "url": b.url} for b in message.buttons],
            "created_at": message.created_at.isoformat()}


class WebhookNotifier:
    channel = "webhook"

    def __init__(self, transport: HttpTransport, *, url: str, secret: str,
                 now: Callable[[], float] = time.time) -> None:
        self._http = transport
        self._url = validate_url(url)
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"the signing secret must be at least {MIN_SECRET_LENGTH} characters")
        self._secret = secret
        self._now = now

    async def send(self, message: OutboundMessage) -> None:
        body = json.dumps(payload_of(message), separators=(",", ":"), sort_keys=True).encode()
        ts = int(self._now())
        headers = {"Content-Type": "application/json", "X-Nchito-Timestamp": str(ts),
                   "X-Nchito-Event-Id": message.event_id, "X-Nchito-Signature": sign(self._secret, ts, body),
                   "User-Agent": "Nchito-Webhook/1"}
        try:
            resp = await self._http.request("POST", self._url, headers=headers, content=body)
        except Exception as exc:
            raise DeliveryError(f"webhook unreachable: {type(exc).__name__}") from None
        if not resp.ok:
            raise DeliveryError(f"webhook answered {resp.status}", retryable=resp.status == 429 or resp.status >= 500)
