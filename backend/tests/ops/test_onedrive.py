"""OneDrive FileStore against an in-memory fake Graph drive (no network): app-folder confinement, upload
sessions, redirects, refresh, throttling, integrity, audited share links."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

import pytest

from app.connect import onedrive
from app.connect.filestore import FileStore
from app.connect.http_transport import HttpResponse
from app.connect.local_store import LocalStoreError
from tests.ops.fakes import Call, FakeTransport

pytestmark = pytest.mark.nodb

NOW = 1_000_000.0
GRAPH = "https://graph.microsoft.com/v1.0"
ROOT = f"{GRAPH}/me/drive/special/approot"


def respond(status: int = 200, body=None, headers=None) -> HttpResponse:
    raw = b"" if body is None else json.dumps(body).encode() if not isinstance(body, bytes) else body
    return HttpResponse(status, raw, headers or {})


@dataclass
class FakeOneDrive:
    files: dict[str, bytes] = field(default_factory=dict)
    refreshes: int = 0
    throttle: int = 0
    corrupt_hash: bool = False
    sessions: dict[str, dict] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    links_allowed: bool = True
    transport: FakeTransport = field(init=False)

    def __post_init__(self) -> None:
        self.transport = FakeTransport(self.handle)
        self.valid = "access-0"

    def _meta(self, path: str) -> dict:
        data = self.files[path]
        sha1 = "0" * 40 if self.corrupt_hash else hashlib.sha1(data, usedforsecurity=False).hexdigest()
        return {"id": f"id-{abs(hash(path))}", "name": path.rsplit("/", 1)[-1], "size": len(data),
                "file": {"hashes": {"sha1Hash": sha1}}}

    def _path(self, url: str) -> tuple[str, str]:
        m = re.fullmatch(re.escape(ROOT) + r":/(.+?):(/content|/createUploadSession)?", url)
        assert m, f"outside the app folder: {url}"
        return unquote(m.group(1)), m.group(2) or ""

    def handle(self, c: Call) -> HttpResponse:
        if "/oauth2/v2.0/token" in c.url:
            assert c.data and c.data["grant_type"] == "refresh_token" and c.data["refresh_token"] == "refresh-0"
            self.refreshes += 1
            self.valid = f"access-{self.refreshes}"
            return respond(200, {"access_token": self.valid, "expires_in": 3600})
        if c.url.startswith("https://upload.example.com/"):
            assert "Authorization" not in c.headers, "the upload address is pre-authorised: no bearer token"
            return self._chunk(c)
        if c.url.startswith("https://download.example.com/"):
            assert "Authorization" not in c.headers
            return respond(200, self.files[unquote(c.url.removeprefix("https://download.example.com/"))])
        assert c.url.startswith(GRAPH + "/"), c.url
        if c.headers.get("Authorization") != f"Bearer {self.valid}":
            return respond(401, {"error": {"code": "InvalidAuthenticationToken"}})
        if self.throttle:
            self.throttle -= 1
            return respond(429, {"error": {}}, {"Retry-After": "4"})
        if c.url == ROOT:
            return respond(200, {"id": "root", "name": "Nchito"})
        m = re.fullmatch(re.escape(GRAPH) + r"/me/drive/items/([^/]+)/createLink", c.url)
        if m:
            if not self.links_allowed:
                return respond(403, {"error": {"code": "accessDenied"}})
            assert c.json == {"type": "view", "scope": "anonymous"}
            self.links.append(m.group(1))
            return respond(200, {"link": {"webUrl": f"https://1drv.example.com/s/{m.group(1)}"}})
        path, tail = self._path(c.url)
        if c.method == "PUT" and tail == "/content":
            assert c.params == {"@microsoft.graph.conflictBehavior": "replace"}
            self.files[path] = c.content or b""
            return respond(201, self._meta(path))
        if c.method == "POST" and tail == "/createUploadSession":
            sid = f"https://upload.example.com/session/{len(self.sessions)}"
            self.sessions[sid] = {"path": path, "buf": b""}
            return respond(200, {"uploadUrl": sid})
        if c.method == "GET" and tail == "/content":
            if path not in self.files:
                return respond(404, {"error": {"code": "itemNotFound"}})
            return respond(302, None, {"Location": "https://download.example.com/" + path})
        if c.method == "GET":
            return respond(200, {"id": self._meta(path)["id"], "file": {}}) if path in self.files else respond(404, {})
        if c.method == "DELETE":
            return respond(204) if self.files.pop(path, None) is not None else respond(404, {})
        raise AssertionError(f"unscripted: {c.method} {c.url}")

    def _chunk(self, c: Call) -> HttpResponse:
        session = self.sessions[c.url]
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", c.headers["Content-Range"])
        assert m and int(m.group(1)) == len(session["buf"])
        assert (len(c.content or b"") % (320 * 1024) == 0) or int(m.group(2)) + 1 == int(m.group(3))
        session["buf"] += c.content or b""
        if int(m.group(2)) + 1 < int(m.group(3)):
            return respond(202, {"nextExpectedRanges": [f"{len(session['buf'])}-"]})
        self.files[session["path"]] = session["buf"]
        return respond(201, self._meta(session["path"]))


def make_store(drive: FakeOneDrive, *, expires_in: float = 3600, recorder=None, on_tokens=None):
    tokens = onedrive.OneDriveTokens("access-0", "refresh-0", NOW + expires_in)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    store = onedrive.OneDriveStore(drive.transport, tokens, client_id="cid", client_secret="csecret", tenant="common",
                                   recorder=recorder, on_tokens_changed=on_tokens, now=lambda: NOW, sleep=sleep)
    store.sleeps = sleeps  # type: ignore[attr-defined]
    return store


def test_store_satisfies_the_filestore_protocol() -> None:
    assert isinstance(make_store(FakeOneDrive()), FileStore)
    assert make_store(FakeOneDrive()).kind == "onedrive"


async def test_put_get_exists_delete_roundtrip_with_nested_keys() -> None:
    drive = FakeOneDrive()
    store = make_store(drive)
    content = b"%PDF-1.4 cv bytes"
    stored = await store.put("applications/abc/cv v1.pdf", content, "application/pdf")
    assert stored.sha256 == hashlib.sha256(content).hexdigest() and stored.size_bytes == len(content)
    assert list(drive.files) == ["applications/abc/cv v1.pdf"]
    assert await store.exists("applications/abc/cv v1.pdf")
    assert not await store.exists("applications/abc/none.pdf")
    assert await store.get("applications/abc/cv v1.pdf") == content  # through the download redirect
    await store.delete("applications/abc/cv v1.pdf")
    await store.delete("applications/abc/cv v1.pdf")  # twice is harmless
    assert not await store.exists("applications/abc/cv v1.pdf")
    with pytest.raises(KeyError):
        await store.get("applications/abc/cv v1.pdf")


async def test_every_request_stays_inside_the_app_folder_and_keys_cannot_escape() -> None:
    drive = FakeOneDrive()
    store = make_store(drive)
    await store.put("a/b.txt", b"x", "text/plain")
    await store.get("a/b.txt")
    await store.share_link("a/b.txt", audience="anyone_with_link")
    graph_calls = [c for c in drive.transport.calls if c.url.startswith(GRAPH)]
    assert all(c.url.startswith(ROOT) or "/me/drive/items/" in c.url for c in graph_calls)
    assert not any("/drive/root" in c.url or ("/drive/items" in c.url and c.method != "POST") for c in graph_calls)
    before = len(drive.transport.calls)
    for bad in ("../x", "/abs", "a//b", "a/./b", "a/../../b", ""):
        with pytest.raises(LocalStoreError):
            await store.put(bad, b"x", "text/plain")
        with pytest.raises(LocalStoreError):
            await store.get(bad)
    assert len(drive.transport.calls) == before


async def test_large_files_go_through_an_upload_session_in_chunks_without_the_bearer_token() -> None:
    drive = FakeOneDrive()
    store = make_store(drive)
    content = bytes(range(256)) * 20_000  # 5.12 MB
    stored = await store.put("backups/big.bin", content, "application/octet-stream")
    assert stored.size_bytes == len(content) and drive.files["backups/big.bin"] == content
    puts = [c for c in drive.transport.calls if c.url.startswith("https://upload.example.com/")]
    assert len(puts) == 2 and puts[0].headers["Content-Range"].startswith("bytes 0-3276799/5120000")
    assert not any(c.url.endswith("/content") and c.method == "PUT" for c in drive.transport.calls)


async def test_small_files_are_one_request() -> None:
    drive = FakeOneDrive()
    await make_store(drive).put("a.txt", b"x" * 100, "text/plain")
    assert [c.method for c in drive.transport.calls] == ["PUT"]


async def test_a_checksum_mismatch_is_an_error() -> None:
    with pytest.raises(onedrive.OneDriveError, match="checksum"):
        await make_store(FakeOneDrive(corrupt_hash=True)).put("a.txt", b"hello", "text/plain")


async def test_an_expiring_token_is_refreshed_and_stored_and_a_401_refreshes_once() -> None:
    seen: list[onedrive.OneDriveTokens] = []

    async def on_tokens(t: onedrive.OneDriveTokens) -> None:
        seen.append(t)

    drive = FakeOneDrive()
    store = make_store(drive, expires_in=10, on_tokens=on_tokens)
    await store.put("a.txt", b"x", "text/plain")
    assert drive.refreshes == 1 and seen[0].access_token == "access-1" and seen[0].refresh_token == "refresh-0"
    drive.valid = "rotated-elsewhere"
    assert await store.exists("a.txt")
    assert drive.refreshes == 2 and len(seen) == 2


async def test_a_refused_refresh_says_reconnect() -> None:
    drive = FakeOneDrive()
    drive.transport.responder = lambda c: respond(400, {"error": "invalid_grant", "error_description": "refresh-0 bad"})
    with pytest.raises(onedrive.OneDriveError, match="reconnect") as err:
        await make_store(drive, expires_in=0).exists("a.txt")
    assert "refresh-0" not in str(err.value)


async def test_a_429_waits_retry_after_and_repeats_then_gives_up_with_a_plain_message() -> None:
    drive = FakeOneDrive()
    store = make_store(drive)
    drive.throttle = 2
    await store.put("a.txt", b"x", "text/plain")
    assert store.sleeps == [4.0, 4.0] and drive.files["a.txt"] == b"x"  # type: ignore[attr-defined]
    drive.throttle = 10
    with pytest.raises(onedrive.OneDriveError, match="throttling"):
        await store.put("b.txt", b"x", "text/plain")


async def test_share_link_is_explicit_and_recorded() -> None:
    drive = FakeOneDrive()
    seen: list[onedrive.ShareRecord] = []

    async def recorder(record: onedrive.ShareRecord) -> None:
        seen.append(record)

    store = make_store(drive, recorder=recorder)
    await store.put("shared/cv.pdf", b"x", "application/pdf")
    assert drive.links == [] and seen == [], "putting a file never shares it"
    url = await store.share_link("shared/cv.pdf", audience="anyone_with_link")
    assert url.startswith("https://1drv.example.com/s/") and len(drive.links) == 1
    assert len(seen) == 1 and seen[0].role == "reader" and seen[0].audience == "anyone_with_link"
    assert seen[0].key == "shared/cv.pdf" and seen[0].url == url and seen[0].file_id
    with pytest.raises(KeyError):
        await store.share_link("shared/none.pdf", audience="anyone_with_link")
    drive.links_allowed = False
    with pytest.raises(onedrive.OneDriveError, match="links"):
        await store.share_link("shared/cv.pdf", audience="anyone_with_link")
    assert len(seen) == 1  # a refused link is not recorded as granted


async def test_check_names_the_app_folder_and_explains_a_work_account() -> None:
    drive = FakeOneDrive()
    assert await make_store(drive).check() == "Nchito"
    drive.transport.responder = lambda c: respond(400, {"error": {"code": "invalidRequest"}})
    with pytest.raises(onedrive.OneDriveError, match="work and school"):
        await make_store(drive).check()


async def test_requests_never_leave_microsoft_graph() -> None:
    store = make_store(FakeOneDrive())
    with pytest.raises(onedrive.OneDriveError):
        await store._call("GET", "https://evil.example.com/x")


def test_authorize_url_asks_only_for_the_app_folder_permission() -> None:
    from urllib.parse import parse_qs, urlsplit

    url = onedrive.authorize_url(tenant="common", client_id="cid", redirect_uri="https://x.example/cb", state="s")
    assert parse_qs(urlsplit(url).query)["scope"][0].split() == ["offline_access", "User.Read",
                                                                 "Files.ReadWrite.AppFolder"]


async def test_exchange_code_requires_the_app_folder_scope_and_a_refresh_token() -> None:
    def run(body, status=200):
        t = FakeTransport(lambda c: respond(status, body))
        return onedrive.exchange_code(t, tenant="common", client_id="c", client_secret="s", redirect_uri="https://x/cb",
                                      code="c1", now=lambda: NOW)

    ok = await run({"access_token": "a", "refresh_token": "r", "expires_in": 100, "scope": "Files.ReadWrite.AppFolder"})
    assert ok.expires_at == NOW + 100 and ok.refresh_token == "r"
    for body in ({"access_token": "a", "scope": "Files.ReadWrite.AppFolder"},
                 {"access_token": "a", "refresh_token": "r", "scope": "User.Read"}):
        with pytest.raises(onedrive.OneDriveError):
            await run(body)
    with pytest.raises(onedrive.OneDriveError) as err:
        await run({"error": "invalid_grant", "error_description": "the code abc is bad"}, 400)
    assert "abc" not in str(err.value)
