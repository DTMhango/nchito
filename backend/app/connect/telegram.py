"""Telegram bot notifier: one ``sendMessage`` per notification with Open / Approve link buttons.

The buttons are deep links into the app (URL buttons), never callbacks: approving still needs the
owner's signed-in session, so a forwarded or leaked Telegram message cannot approve anything.
The bot token lives encrypted in the connection and is never put in a message or an error.
"""

from __future__ import annotations

import html

from app.connect.http_transport import HttpTransport
from app.connect.notifier import DeliveryError, OutboundMessage

API = "https://api.telegram.org"
MAX_TEXT = 3800  # Telegram's limit is 4096 characters; keep headroom for the escaped text


def format_text(message: OutboundMessage) -> str:
    text = f"<b>{html.escape(message.title)}</b>"
    if message.body:
        text += f"\n{html.escape(message.body)}"
    return text[:MAX_TEXT]


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, transport: HttpTransport, *, bot_token: str, chat_id: str) -> None:
        self._http = transport
        self._token = bot_token
        self._chat = chat_id

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***")

    async def _post(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        try:
            resp = await self._http.request("POST", f"{API}/bot{self._token}/{method}", json=payload)
        except Exception as exc:  # network errors carry the URL, which holds the token
            raise DeliveryError(f"telegram unreachable: {type(exc).__name__}") from None
        body = resp.json() if resp.body else {}
        if not resp.ok or not (body or {}).get("ok", False):
            retryable = resp.status == 429 or resp.status >= 500
            description = self._redact(str((body or {}).get("description", "no detail")))[:200]
            raise DeliveryError(f"telegram answered {resp.status}: {description}", retryable=retryable)
        return body

    async def send(self, message: OutboundMessage) -> None:
        payload: dict[str, object] = {"chat_id": self._chat, "text": format_text(message), "parse_mode": "HTML",
                                      "disable_web_page_preview": True}
        if message.buttons:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": b.label, "url": b.url} for b in message.buttons]]}
        await self._post("sendMessage", payload)

    async def check(self) -> str:
        """Connection test: the token is valid. Returns the bot's username."""
        body = await self._post("getMe", {})
        return str((body.get("result") or {}).get("username", "bot"))  # type: ignore[union-attr]
