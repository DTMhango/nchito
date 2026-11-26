"""Google Drive FileStore against an in-memory fake Drive (no network)."""

from __future__ import annotations

import hashlib

import pytest

from app.connect import gdrive
from app.connect.filestore import FileStore
from app.connect.local_store import LocalFileStore, LocalStoreError
from tests.ops.fakes import FakeDrive, FakeTransport, reply

pytestmark = pytest.mark.nodb

NOW = 1_000_000.0


def make_store(drive: FakeDrive, *, expires_in: float = 3600, recorder=None, on_tokens=None, on_root=None,
               root_id: str | None = None):
    tokens = gdrive.DriveTokens("access-0", "refresh-0", NOW + expires_in)
    return gdrive.GoogleDriveStore(drive.transport, tokens, client_id="cid", client_secret="csecret",
                                   root_folder_name="Nchito", root_folder_id=root_id, recorder=recorder,
                                   on_tokens_changed=on_tokens, on_root_created=on_root, now=lambda: NOW)


def test_store_satisfies_the_filestore_protocol() -> None:
    assert isinstance(make_store(FakeDrive()), FileStore)


async def test_put_get_exists_delete_roundtrip_with_nested_folders() -> None:
    drive = FakeDrive()
    store = make_store(drive)
    content = b"%PDF-1.4 cv bytes"
    stored = await store.put("applications/abc/cv.pdf", content, "application/pdf")
    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.size_bytes == len(content)
    assert await store.exists("applications/abc/cv.pdf")
    assert not await store.exists("applications/abc/missing.pdf")
    assert await store.get("applications/abc/cv.pdf") == content
    folders = sorted(n.name for n in drive.nodes.values() if n.mime.endswith("folder"))
    assert folders == ["Nchito", "abc", "applications"]
    await store.delete("applications/abc/cv.pdf")
    assert not await store.exists("applications/abc/cv.pdf")
    await store.delete("applications/abc/cv.pdf")  # deleting twice is harmless


async def test_put_again_replaces_the_file_instead_of_duplicating() -> None:
    drive = FakeDrive()
    store = make_store(drive)
    await store.put("a/b.txt", b"one", "text/plain")
    await store.put("a/b.txt", b"two!", "text/plain")
    files = [n for n in drive.nodes.values() if not n.mime.endswith("folder")]
    assert len(files) == 1
    assert await store.get("a/b.txt") == b"two!"


async def test_get_missing_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        await make_store(FakeDrive()).get("nope/x.txt")


async def test_share_link_is_explicit_and_recorded() -> None:
    drive = FakeDrive()
    seen: list[gdrive.ShareRecord] = []

    async def recorder(record: gdrive.ShareRecord) -> None:
        seen.append(record)

    store = make_store(drive, recorder=recorder)
    await store.put("shared/cv.pdf", b"x", "application/pdf")
    assert not any(n.shared for n in drive.nodes.values()), "putting a file never shares it"
    url = await store.share_link("shared/cv.pdf", audience="anyone_with_link")
    assert url.startswith("https://drive.example.com/view/")
    assert [n.shared for n in drive.nodes.values() if n.name == "cv.pdf"] == [True]
    assert len(seen) == 1 and seen[0].role == "reader" and seen[0].audience == "anyone_with_link"
    assert seen[0].key == "shared/cv.pdf" and seen[0].url == url
    with pytest.raises(KeyError):
        await store.share_link("shared/none.pdf", audience="anyone_with_link")


async def test_keys_must_be_safe_relative_paths() -> None:
    store = make_store(FakeDrive())
    for bad in ("../x", "/abs", "a//b", "a/./b", ""):
        with pytest.raises(LocalStoreError):
            await store.put(bad, b"x", "text/plain")


async def test_a_checksum_mismatch_is_an_error() -> None:
    drive = FakeDrive(corrupt_md5=True)
    with pytest.raises(gdrive.DriveError, match="checksum"):
        await make_store(drive).put("a.txt", b"data", "text/plain")


async def test_expired_token_is_refreshed_and_persisted() -> None:
    drive = FakeDrive()
    saved: list[gdrive.DriveTokens] = []

    async def on_tokens(tokens: gdrive.DriveTokens) -> None:
        saved.append(tokens)

    store = make_store(drive, expires_in=10, on_tokens=on_tokens)  # inside the refresh margin
    await store.put("a.txt", b"x", "text/plain")
    assert drive.access_tokens == 1
    assert saved and saved[0].access_token == "access-1" and saved[0].refresh_token == "refresh-0"


async def test_a_401_triggers_one_refresh_then_succeeds() -> None:
    drive = FakeDrive()
    store = make_store(drive)
    drive.valid_token = "rotated-elsewhere"  # the access token we hold is now rejected
    await store.put("a.txt", b"x", "text/plain")
    assert drive.access_tokens == 1


async def test_revoked_refresh_token_is_a_clear_error() -> None:
    transport = FakeTransport(lambda call: reply(400, {"error": "invalid_grant"}))
    tokens = gdrive.DriveTokens("a", "r", NOW - 5)
    store = gdrive.GoogleDriveStore(transport, tokens, client_id="c", client_secret="s", root_folder_name="N",
                                    now=lambda: NOW)
    with pytest.raises(gdrive.DriveError, match="reconnect"):
        await store.exists("x.txt")


async def test_root_folder_is_created_once_and_reported() -> None:
    drive = FakeDrive()
    roots: list[str] = []

    async def on_root(folder_id: str) -> None:
        roots.append(folder_id)

    store = make_store(drive, on_root=on_root)
    await store.put("a/x.txt", b"1", "text/plain")
    await store.put("a/y.txt", b"2", "text/plain")
    assert len(roots) == 1
    assert sum(1 for n in drive.nodes.values() if n.name == "Nchito") == 1
    reopened = make_store(drive, root_id=roots[0])
    assert await reopened.exists("a/x.txt")


def test_authorize_url_asks_only_for_the_narrow_scope() -> None:
    url = gdrive.authorize_url(client_id="cid", redirect_uri="https://app.example.com/cb", state="st")
    assert "drive.file" in url and "drive.readonly" not in url and "state=st" in url


async def test_exchange_code_requires_refresh_token_and_the_scope() -> None:
    ok = FakeTransport(lambda c: reply(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3600,
                                             "scope": gdrive.SCOPE}))
    tokens = await gdrive.exchange_code(ok, client_id="c", client_secret="s", redirect_uri="u", code="x",
                                        now=lambda: NOW)
    assert tokens.refresh_token == "r" and tokens.expires_at == NOW + 3600
    no_refresh = FakeTransport(lambda c: reply(200, {"access_token": "a", "scope": gdrive.SCOPE}))
    with pytest.raises(gdrive.DriveError, match="refresh token"):
        await gdrive.exchange_code(no_refresh, client_id="c", client_secret="s", redirect_uri="u", code="x")
    wrong_scope = FakeTransport(lambda c: reply(200, {"access_token": "a", "refresh_token": "r",
                                                      "scope": "https://example.com/other"}))
    with pytest.raises(gdrive.DriveError, match="not granted"):
        await gdrive.exchange_code(wrong_scope, client_id="c", client_secret="s", redirect_uri="u", code="x")


async def test_local_store_is_the_default_and_never_makes_links(tmp_path) -> None:
    store = LocalFileStore(tmp_path)
    assert isinstance(store, FileStore) and store.kind == "local"
    stored = await store.put("applications/1/cv.pdf", b"abc", "application/pdf")
    assert stored.sha256 == hashlib.sha256(b"abc").hexdigest()
    assert await store.get("applications/1/cv.pdf") == b"abc"
    assert await store.exists("applications/1/cv.pdf")
    with pytest.raises(LocalStoreError):
        await store.share_link("applications/1/cv.pdf", audience="anyone_with_link")
    with pytest.raises(LocalStoreError):
        await store.get("../outside")
    await store.delete("applications/1/cv.pdf")
    assert not await store.exists("applications/1/cv.pdf")
