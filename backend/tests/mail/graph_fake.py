"""An in-memory Microsoft Graph (mail subset) behind the mail ``HttpTransport``. Invented data, no network."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.connect.mail_common import HttpResult, TransportTimeout

GRAPH = "https://graph.microsoft.com/v1.0"
OWNER = "owner.jobs@example.com"
EMPLOYER = "hr@acme.example.com"


def inbox_item(n: int, *, sender: str = EMPLOYER, subject: str = "Re: your application", html: bool = False,
               received: str | None = None, headers: list[dict[str, str]] | None = None) -> dict[str, Any]:
    body = "<p>Hello <b>there</b></p>" if html else f"Body {n}"
    return {"id": f"AAMk-in-{n}", "conversationId": f"conv-{n}", "subject": subject,
            "from": {"emailAddress": {"address": sender.upper()}},
            "toRecipients": [{"emailAddress": {"address": OWNER}}],
            "receivedDateTime": received or f"2026-11-2{n}T10:00:00.0000000Z",
            "body": {"contentType": "html" if html else "text", "content": body},
            "internetMessageId": f"<in-{n}@mail.example.com>", "internetMessageHeaders": headers or []}


class FakeGraph:
    """Scripted Graph. ``send_mode``: ok | timeout_after_accept | timeout_before | 500 | 429 | 400."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.sleeps: list[float] = []
        self.valid_token = "access-old"
        self.refresh_count = 0
        self.send_mode = "ok"
        self.draft_failure: int | str | None = None  # an HTTP status, or "timeout"
        self.rewrite_message_id = False  # Exchange replaced our Message-ID
        self.throttle: dict[str, int] = {}  # "GET" or "POST /me/messages" -> remaining 429s
        self.retry_after = "3"
        self.drafts: dict[str, dict[str, Any]] = {}
        self.sent: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.inbox: list[dict[str, Any]] = []
        self.folders = {"Jobs": "AAMk-jobs"}
        self.page = 2
        self.since = ""

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def urls(self, method: str | None = None) -> list[str]:
        return [c["url"] for c in self.calls if method is None or c["method"] == method]

    async def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                      params: Mapping[str, Any] | None = None, json: Any = None,
                      form: Mapping[str, str] | None = None) -> HttpResult:
        call = {"method": method, "url": url, "headers": dict(headers or {}), "params": dict(params or {}),
                "json": json, "form": dict(form or {})}
        self.calls.append(call)
        out = self.handle(method, url, call["params"], json, call["form"], call["headers"])
        status, data, *rest = out
        return HttpResult(status, data, rest[0] if rest else {})

    # ----- the service ----------------------------------------------------------------------

    def handle(self, method, url, params, json, form, headers):
        if "/oauth2/v2.0/token" in url:
            if form.get("grant_type") == "refresh_token" and form.get("refresh_token") == "refresh-abc":
                self.refresh_count += 1
                self.valid_token = f"access-new-{self.refresh_count}"
                return 200, {"access_token": self.valid_token, "expires_in": 3600, "scope": "Mail.Send Mail.Read"}
            return 400, {"error": "invalid_grant"}
        if headers.get("Authorization") != f"Bearer {self.valid_token}":
            return 401, {"error": {"code": "InvalidAuthenticationToken"}}
        path = url.removeprefix(GRAPH).split("?")[0]
        key = f"{method} {path}"
        if self.throttle.get(key) or self.throttle.get(method):
            slot = key if self.throttle.get(key) else method
            self.throttle[slot] -= 1
            return 429, {"error": {"code": "TooManyRequests"}}, {"Retry-After": self.retry_after}
        if key == "GET /me":
            return 200, {"mail": OWNER}
        if key == "POST /me/messages":
            return self._draft(json)
        m = re.fullmatch(r"POST /me/messages/([^/]+)/send", key)
        if m:
            return self._send(m.group(1))
        m = re.fullmatch(r"DELETE /me/messages/([^/]+)", key)
        if m:
            self.deleted.append(m.group(1))
            return 204, None
        if key == "GET /me/mailFolders" or key == "GET /me/mailFolders/inbox/childFolders":
            name = re.search(r"displayName eq '(.*)'", params.get("$filter", ""))
            found = self.folders.get(name.group(1)) if name else None
            return 200, {"value": [{"id": found}] if found and path == "/me/mailFolders" else []}
        if key == "GET /me/mailFolders/sentitems/messages":
            return self._sent_items(params)
        m = re.fullmatch(r"GET /me/mailFolders/([^/]+)/messages", key)
        if m:
            return self._inbox(m.group(1), url, params)
        raise AssertionError(f"unscripted call: {key}")

    def _draft(self, body: dict[str, Any]):
        if self.draft_failure == "timeout":
            raise TransportTimeout("ReadTimeout")
        if self.draft_failure:
            return self.draft_failure, {"error": {"code": "ErrorX"}}
        draft_id = f"AAMk-draft-{len(self.drafts) + 1}"
        self.drafts[draft_id] = body
        return 201, {"id": draft_id, "internetMessageId": body.get("internetMessageId", "<graph-made@outlook.example>")}

    def _send(self, draft_id: str):
        if self.send_mode == "timeout_before":
            raise TransportTimeout("ReadTimeout")
        if self.send_mode in ("500", "429", "400"):
            return int(self.send_mode), {"error": {"code": "ErrorX"}}
        draft = self.drafts[draft_id]
        mid = "<rewritten@outlook.example>" if self.rewrite_message_id else draft.get("internetMessageId")
        self.sent.append({"id": f"AAMk-sent-{len(self.sent) + 1}", "subject": draft["subject"],
                          "internetMessageId": mid, "internetMessageHeaders": [
                              *draft.get("internetMessageHeaders", []), {"name": "Received", "value": "x"}],
                          "from": {"emailAddress": {"address": OWNER}},
                          "toRecipients": draft["toRecipients"], "sentDateTime": datetime.now(UTC).isoformat(),
                          "body": draft["body"]})
        if self.send_mode == "timeout_after_accept":
            raise TransportTimeout("ReadTimeout")  # Graph took it, the answer was lost
        return 202, None

    def _sent_items(self, params: Mapping[str, Any]):
        wanted = re.search(r"internetMessageId eq '(.*)'", params.get("$filter", ""))
        items = [s for s in self.sent if not wanted or s["internetMessageId"] == wanted.group(1)]
        return 200, {"value": list(reversed(items))}

    def _inbox(self, folder: str, url: str, params: Mapping[str, Any]):
        assert folder in ("AAMk-jobs", "inbox"), f"read outside the configured folder: {folder}"
        skip = int(parse_qs(urlsplit(url).query).get("skip", ["0"])[0])
        top = int(params.get("$top", self.page)) if params else self.page
        top = min(top, self.page)
        match = re.search(r"receivedDateTime ge (\S+)", (params or {}).get("$filter", ""))
        if match:  # the next-page link carries the query: remember the first page's filter
            self.since = match.group(1)
        rows = [i for i in self.inbox if i["receivedDateTime"] >= self.since]
        rows = sorted(rows, key=lambda i: i["receivedDateTime"])
        page = rows[skip:skip + top]
        data: dict[str, Any] = {"value": page}
        if skip + top < len(rows):
            data["@odata.nextLink"] = f"{GRAPH}/me/mailFolders/{folder}/messages?skip={skip + top}"
        return 200, data
