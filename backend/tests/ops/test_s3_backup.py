"""S3-compatible backup target: the store against a fake client, the connection record (keys encrypted,
never returned), the backup job's remote selection, and retention reaching the remote copy."""

from __future__ import annotations

import asyncio
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.connect import s3
from app.core.settings import service as settings_service
from app.models.platform import Connection
from app.ops import backup, jobs

ENDPOINT = "https://s3.example.com"


class NoSuchKey(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[str] = []
        self.deny = False

    def _guard(self, name: str) -> None:
        self.calls.append(name)
        if self.deny:
            raise PermissionError("access key AKIASECRET is not allowed")

    def head_bucket(self, Bucket):
        self._guard("head_bucket")

    def put_object(self, Bucket, Key, Body, ContentType):
        self._guard("put_object")
        self.objects[(Bucket, Key)] = bytes(Body)

    def get_object(self, Bucket, Key):
        self._guard("get_object")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self._guard("delete_object")
        self.objects.pop((Bucket, Key), None)

    def head_object(self, Bucket, Key):
        self._guard("head_object")
        if (Bucket, Key) not in self.objects:
            raise NoSuchKey
        return {}


@pytest.fixture
def fake():
    client = FakeS3()
    seen: list[tuple[str, str, str, str]] = []

    def factory(endpoint, region, key_id, secret):
        seen.append((endpoint, region, key_id, secret))
        return client

    s3.set_client_factory(factory)
    client.factory_calls = seen  # type: ignore[attr-defined]
    yield client
    s3.set_client_factory(None)


async def test_store_puts_gets_checks_and_deletes_under_its_prefix(fake) -> None:
    store = s3.S3Store(fake, "bk", "nchito/")
    stored = await store.put("backups/a.backup", b"cipher", "application/octet-stream")
    assert stored.size_bytes == 6 and ("bk", "nchito/backups/a.backup") in fake.objects
    assert await store.exists("backups/a.backup") and await store.get("backups/a.backup") == b"cipher"
    assert await store.check() == "bk"
    await store.delete("backups/a.backup")
    assert not await store.exists("backups/a.backup")
    with pytest.raises(s3.S3Error):
        await store.put("../escape", b"x", "text/plain")
    with pytest.raises(s3.S3Error):
        await store.share_link("backups/a.backup", audience="anyone_with_link")


async def test_provider_errors_never_leak_their_text(fake) -> None:
    fake.deny = True
    with pytest.raises(s3.S3Error) as err:
        await s3.S3Store(fake, "bk").put("k", b"x", "text/plain")
    assert "AKIASECRET" not in str(err.value)


async def test_connection_is_encrypted_validated_and_tested(owner_client, session, fake) -> None:
    body = {"provider": "s3", "label": "Backups", "config": {"endpoint": ENDPOINT, "bucket": "nchito-backups",
                                                                "region": "auto", "prefix": "prod"},
            "secrets": {"access_key_id": "AKIAEXAMPLE", "secret_access_key": "s3cr3t-value"}}
    r = await owner_client.post("/api/connections", json=body)
    assert r.status_code == 201, r.text
    assert "s3cr3t-value" not in r.text and set(r.json()["secrets_masked"]) == {"access_key_id", "secret_access_key"}
    stored = await session.get(Connection, r.json()["id"])
    assert stored is not None and "s3cr3t-value" not in str(stored.secrets_enc)
    for bad in ({"endpoint": "http://remote.example.com", "bucket": "nchito-backups"},
                {"endpoint": ENDPOINT, "bucket": "Bad_Bucket"}):
        assert (await owner_client.post("/api/connections", json={**body, "config": bad})).status_code == 422
    tested = await owner_client.post(f"/api/connections/{r.json()['id']}/test")
    assert tested.status_code == 200 and tested.json()["ok"] is True
    assert fake.factory_calls[-1] == (ENDPOINT, "auto", "AKIAEXAMPLE", "s3cr3t-value")
    fake.deny = True
    failed = await owner_client.post(f"/api/connections/{r.json()['id']}/test")
    assert failed.json()["ok"] is False and "s3cr3t-value" not in failed.text


async def test_backup_job_uses_the_s3_store_and_says_so_when_it_is_missing(owner_client, session, fake) -> None:
    store, warning = await jobs.remote_store(session, "s3")
    assert store is None and warning and "not connected" in warning
    await owner_client.post("/api/connections", json={
        "provider": "s3", "label": "B", "config": {"endpoint": ENDPOINT, "bucket": "nchito-backups"},
        "secrets": {"access_key_id": "k", "secret_access_key": "s"}})
    store, warning = await jobs.remote_store(session, "s3")
    assert warning is None and isinstance(store, s3.S3Store)
    assert (await jobs.remote_store(session, "local")) == (None, None)


async def test_retention_removes_the_remote_copy_with_the_local_one(fake, tmp_path: Path, session) -> None:
    await settings_service.set_value(session, "backups.keep", 1, actor="test")
    store = s3.S3Store(fake, "bk", "p")
    base = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)
    for day in range(3):
        name = f"nchito-2026112{day}T020000Z"
        key = f"backups/{name}.backup"
        await store.put(key, b"x", "application/octet-stream")
        info = backup.BackupInfo(id=name, path=str(tmp_path / f"{name}.backup"),
                                 created_at=base + timedelta(days=day), size_bytes=1, sha256="0" * 64,
                                 remote_target="s3", remote_key=key)
        await asyncio.to_thread(Path(info.path).write_bytes, b"x")
        await asyncio.to_thread(Path(info.path + ".json").write_text, json.dumps(info.to_json()), "utf-8")
    removed = await backup.prune_backups(1, directory=tmp_path, store=store)
    assert sorted(removed) == ["nchito-20261120T020000Z", "nchito-20261121T020000Z"]
    assert [k for (_, k) in fake.objects] == ["p/backups/nchito-20261122T020000Z.backup"]
