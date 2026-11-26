"""Fakes for the ops tests: a scripted HTTP transport and an in-memory Google Drive."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.connect.http_transport import HttpResponse


@dataclass
class Call:
    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, str]
    json: Any
    content: bytes | None
    data: dict[str, str] | None


class FakeTransport:
    """Records every request; ``responder(call)`` returns the response (default: 200 ``{"ok": true}``)."""

    def __init__(self, responder: Callable[[Call], HttpResponse] | None = None) -> None:
        self.calls: list[Call] = []
        self.responder = responder or (lambda call: HttpResponse(200, json.dumps({"ok": True}).encode()))

    async def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                      params: Mapping[str, str] | None = None, json: Any = None, content: bytes | None = None,
                      data: Mapping[str, str] | None = None) -> HttpResponse:
        call = Call(method, url, dict(headers or {}), dict(params or {}), json, content, dict(data) if data else None)
        self.calls.append(call)
        return self.responder(call)


def reply(status: int = 200, body: Any = None) -> HttpResponse:
    return HttpResponse(status, json.dumps(body if body is not None else {"ok": True}).encode())


@dataclass
class _Node:
    id: str
    name: str
    parent: str
    mime: str
    content: bytes = b""
    shared: bool = False


@dataclass
class FakeDrive:
    """Enough of Drive v3 for the store: folders, files, md5, permissions, token refresh."""

    nodes: dict[str, _Node] = field(default_factory=dict)
    access_tokens: int = 0
    reject_first_token: bool = False
    corrupt_md5: bool = False
    transport: FakeTransport = field(init=False)

    def __post_init__(self) -> None:
        self.transport = FakeTransport(self.handle)
        self.valid_token = "access-0"
        self.current_token = self.valid_token

    def children(self, parent: str) -> list[_Node]:
        return [n for n in self.nodes.values() if n.parent == parent]

    def _file_json(self, n: _Node) -> dict[str, Any]:
        md5 = hashlib.md5(n.content, usedforsecurity=False).hexdigest()
        return {"id": n.id, "name": n.name, "mimeType": n.mime, "size": str(len(n.content)),
                "md5Checksum": "0" * 32 if self.corrupt_md5 else md5}

    def handle(self, call: Call) -> HttpResponse:
        if call.url.endswith("/token"):
            self.access_tokens += 1
            self.valid_token = f"access-{self.access_tokens}"
            return reply(200, {"access_token": self.valid_token, "expires_in": 3600})
        if call.headers.get("Authorization") != f"Bearer {self.valid_token}":
            return reply(401, {"error": "invalid"})
        url, m = call.url, call.method
        if m == "GET" and url.endswith("/drive/v3/files"):
            q = call.params["q"]
            name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q).group(1).replace("\\'", "'")  # type: ignore[union-attr]
            parent = re.search(r"'([^']+)' in parents", q).group(1)  # type: ignore[union-attr]
            found = [n for n in self.children(parent) if n.name == name]
            if "mimeType = " in q:
                found = [n for n in found if n.mime == "application/vnd.google-apps.folder"]
            elif "mimeType != " in q:
                found = [n for n in found if n.mime != "application/vnd.google-apps.folder"]
            return reply(200, {"files": [self._file_json(n) for n in found]})
        if m == "POST" and url.endswith("/drive/v3/files") and "/upload/" not in url:
            body = call.json
            node = _Node(uuid.uuid4().hex, body["name"], body["parents"][0], body["mimeType"])
            self.nodes[node.id] = node
            return reply(200, {"id": node.id})
        if m == "POST" and "/upload/drive/v3/files" in url:
            raw = call.content or b""
            boundary = call.headers["Content-Type"].split("boundary=")[1].encode()
            parts = [p for p in raw.split(b"--" + boundary) if p.strip(b"-\r\n")]
            meta = json.loads(parts[0].split(b"\r\n\r\n", 1)[1].strip())
            data = parts[1].split(b"\r\n\r\n", 1)[1].removesuffix(b"\r\n")
            node = _Node(uuid.uuid4().hex, meta["name"], meta["parents"][0], meta["mimeType"], data)
            self.nodes[node.id] = node
            return reply(200, self._file_json(node))
        if m == "PATCH" and "/upload/drive/v3/files/" in url:
            node = self.nodes[url.rsplit("/", 1)[1]]
            node.content = call.content or b""
            return reply(200, self._file_json(node))
        if m == "GET" and call.params.get("alt") == "media":
            node = self.nodes.get(url.rsplit("/", 1)[1])
            return HttpResponse(200, node.content) if node else reply(404)
        if m == "DELETE":
            self.nodes.pop(url.rsplit("/", 1)[1], None)
            return HttpResponse(204)
        if m == "POST" and url.endswith("/permissions"):
            fid = url.split("/files/")[1].split("/")[0]
            assert call.json == {"role": "reader", "type": "anyone"}
            self.nodes[fid].shared = True
            return reply(200, {"id": "perm"})
        if m == "GET" and call.params.get("fields") == "webViewLink":
            fid = url.rsplit("/", 1)[1]
            return reply(200, {"webViewLink": f"https://drive.example.com/view/{fid}"})
        return reply(404, {"error": f"unhandled {m} {url}"})
