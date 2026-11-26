"""Connection endpoints (Telegram, webhook, Drive OAuth), backup/retention endpoints, config history."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.connect import gdrive, records
from app.connect.http_transport import set_transport
from app.core import crypto
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.models.platform import AuditEvent, Connection, ConnectionProvider
from tests.ops.fakes import FakeDrive, FakeTransport, reply

TOKEN = "123456789:AAFexampleexampleexample1234"
SECRET = "a-long-shared-secret-value"


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    set_transport(None)


async def make(owner_client, provider: str, config: dict, secrets: dict, label: str = "x"):
    return await owner_client.post("/api/connections", json={"provider": provider, "label": label, "config": config,
                                                             "secrets": secrets})


async def test_telegram_connection_is_stored_encrypted_and_returned_masked(owner_client, session) -> None:
    r = await make(owner_client, "telegram", {"chat_id": "555"}, {"bot_token": TOKEN}, "My bot")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "telegram" and body["config"] == {"chat_id": "555"}
    assert body["secrets_masked"]["bot_token"].startswith("********") and TOKEN not in r.text
    assert "reads nothing" in body["reads_description"].lower()
    row = await session.scalar(select(Connection).where(Connection.provider == ConnectionProvider.telegram))
    assert TOKEN not in (row.secrets_enc or "") and json.loads(crypto.decrypt(row.secrets_enc))["bot_token"] == TOKEN
    audit = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "connection.created"))).all()
    assert audit and TOKEN not in json.dumps(audit[0].detail)
    listed = (await owner_client.get("/api/connections")).json()
    assert TOKEN not in json.dumps(listed)


async def test_connection_input_is_validated(owner_client) -> None:
    assert (await make(owner_client, "telegram", {"chat_id": "not a chat"}, {"bot_token": TOKEN})).status_code == 422
    assert (await make(owner_client, "telegram", {"chat_id": "5"}, {"bot_token": "nope"})).status_code == 422
    assert (await make(owner_client, "telegram", {"chat_id": "5", "x": 1}, {"bot_token": TOKEN})).status_code == 422
    assert (await make(owner_client, "webhook", {"url": "http://example.com/in"}, {"signing_secret": SECRET})
            ).status_code == 422
    assert (await make(owner_client, "webhook", {"url": "https://example.com/in"}, {"signing_secret": "short"})
            ).status_code == 422
    assert (await make(owner_client, "gdrive", {}, {})).status_code == 422, "Drive connects through OAuth"


async def test_connection_test_sends_a_message_through_the_injected_transport(owner_client) -> None:
    fake = FakeTransport(lambda c: reply(200, {"ok": True, "result": {"username": "my_bot"}}))
    set_transport(fake)
    made = (await make(owner_client, "telegram", {"chat_id": "555"}, {"bot_token": TOKEN})).json()
    r = await owner_client.post(f"/api/connections/{made['id']}/test")
    assert r.status_code == 200 and r.json()["ok"] is True and "my_bot" in r.json()["detail"]
    assert [c.url.rsplit("/", 1)[1] for c in fake.calls] == ["getMe", "sendMessage"]
    assert (await owner_client.get("/api/connections")).json()[0]["health"] == "ok"

    set_transport(FakeTransport(lambda c: reply(401, {"ok": False, "description": "Unauthorized"})))
    bad = await owner_client.post(f"/api/connections/{made['id']}/test")
    assert bad.json()["ok"] is False and TOKEN not in bad.text
    assert (await owner_client.get("/api/connections")).json()[0]["health"] == "failing"


async def test_webhook_connection_test_is_signed_and_secret_update_keeps_old_when_blank(owner_client, session) -> None:
    fake = FakeTransport()
    set_transport(fake)
    made = (await make(owner_client, "webhook", {"url": "https://hooks.example.com/in"},
                       {"signing_secret": SECRET})).json()
    r = await owner_client.post(f"/api/connections/{made['id']}/test")
    assert r.json()["ok"] is True
    assert fake.calls[0].headers["X-Nchito-Signature"].startswith("sha256=")
    upd = await owner_client.put(f"/api/connections/{made['id']}", json={"label": "Renamed", "secrets": {
        "signing_secret": ""}, "enabled": False})
    assert upd.status_code == 200 and upd.json()["label"] == "Renamed" and upd.json()["enabled"] is False
    row = await session.scalar(select(Connection))
    assert json.loads(crypto.decrypt(row.secrets_enc))["signing_secret"] == SECRET
    assert (await owner_client.delete(f"/api/connections/{made['id']}")).status_code == 204


async def test_providers_no_stream_manages_stay_501(owner_client) -> None:
    r = await make(owner_client, "s3", {}, {})
    assert r.status_code == 501


async def test_drive_oauth_needs_server_credentials(owner_client) -> None:
    cfg = get_config()
    assert cfg.google_oauth_client_id is None
    r = await owner_client.post("/api/connections/oauth/gdrive/start")
    assert r.status_code == 409 and "GOOGLE_OAUTH_CLIENT_ID" in r.json()["detail"]


async def test_drive_oauth_round_trip_creates_the_connection_and_a_working_store(owner_client, session,
                                                                                 monkeypatch) -> None:
    cfg = get_config()
    monkeypatch.setattr(cfg, "google_oauth_client_id", "client-id.example.com")
    monkeypatch.setattr(cfg, "google_oauth_client_secret", "client-secret-value")
    start = await owner_client.post("/api/connections/oauth/gdrive/start")
    assert start.status_code == 200
    url = urlsplit(start.json()["authorize_url"])
    query = parse_qs(url.query)
    assert query["scope"] == [gdrive.SCOPE] and query["client_id"] == ["client-id.example.com"]
    state = query["state"][0]

    bad = await owner_client.get("/api/connections/oauth/gdrive/callback", params={"code": "c", "state": "forged"})
    assert bad.status_code == 400

    drive = FakeDrive()
    original = drive.handle

    def responder(call):
        if call.url.endswith("/token") and (call.data or {}).get("grant_type") == "authorization_code":
            return reply(200, {"access_token": "access-0", "refresh_token": "refresh-secret", "expires_in": 30,
                               "scope": gdrive.SCOPE})
        return original(call)

    drive.transport.responder = responder
    set_transport(drive.transport)
    done = await owner_client.get("/api/connections/oauth/gdrive/callback", params={"code": "good", "state": state})
    assert done.status_code == 307 and done.headers["location"].endswith("connected=gdrive")

    listed = (await owner_client.get("/api/connections")).json()
    assert [c["provider"] for c in listed] == ["gdrive"] and listed[0]["scopes_granted"] == [gdrive.SCOPE]
    assert "refresh-secret" not in json.dumps(listed) and "refresh-secret" not in json.dumps(
        [e.detail for e in await session.scalars(select(AuditEvent))])

    store = await records.drive_store(session)
    await store.put("applications/a/cv.pdf", b"cv-bytes", "application/pdf")
    await session.commit()
    await session.refresh(conn := await session.scalar(select(Connection)))
    stored = json.loads(crypto.decrypt(conn.secrets_enc))["tokens"]
    assert stored["access_token"] == "access-1", "the refreshed token was written back (encrypted)"
    assert conn.config["root_folder_id"], "the root folder id was remembered"
    link = await store.share_link("applications/a/cv.pdf", audience="anyone_with_link")
    await session.commit()
    shares = (await session.scalars(select(AuditEvent).where(
        AuditEvent.action == "filestore.share_link_created"))).all()
    assert len(shares) == 1 and shares[0].detail["url"] == link and shares[0].detail["role"] == "reader"

    # the test endpoint reaches the root folder
    test = await owner_client.post(f"/api/connections/{conn.id}/test")
    assert test.json()["ok"] is True and "Nchito" in test.json()["detail"]


# ----- data endpoints --------------------------------------------------------------------------


async def test_backup_endpoints_create_and_list(owner_client, tmp_path, monkeypatch) -> None:
    from app.ops import backup

    if not backup.pg_available():
        pytest.skip("pg_dump / pg_restore are not on PATH; install the PostgreSQL client tools")
    cfg = get_config()
    monkeypatch.setattr(cfg, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(cfg, "files_dir", tmp_path / "files")
    assert (await owner_client.get("/api/data/backups")).json() == []
    r = await owner_client.post("/api/data/backups")
    assert r.status_code == 202, r.text
    made = r.json()
    assert made["target"] == "local" and made["encrypted"] is True and made["size_bytes"] > 0
    listed = (await owner_client.get("/api/data/backups")).json()
    assert [b["id"] for b in listed] == [made["id"]]
    audit = (await owner_client.get("/api/audit", params={"action": "backup.completed"})).json()
    assert audit["items"] and audit["items"][0]["subject_id"] == made["id"]


async def test_backup_endpoints_need_the_owner(client) -> None:
    assert (await client.get("/api/data/backups")).status_code == 401
    assert (await client.post("/api/data/retention/run")).status_code == 401


async def test_retention_endpoint_runs_and_records_a_run(owner_client, tmp_path, monkeypatch) -> None:
    cfg = get_config()
    monkeypatch.setattr(cfg, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(cfg, "files_dir", tmp_path / "files")
    r = await owner_client.post("/api/data/retention/run")
    assert r.status_code == 202 and r.json() == {"ok": True}
    runs = (await owner_client.get("/api/runs")).json()
    items = runs["items"] if isinstance(runs, dict) else runs
    assert any(x["kind"] == "retention" and x["status"] == "succeeded" for x in items)


async def test_config_history_lists_settings_changes_newest_first(owner_client, session) -> None:
    baseline = len((await owner_client.get("/api/data/config-history")).json()["items"])  # setup wrote some
    await settings_service.set_many(session, {"backups.keep": 7}, actor="owner")
    await session.commit()  # one transaction per change, so the two have different times
    await settings_service.set_many(session, {"backups.keep": 9}, actor="owner")
    await session.commit()
    page = (await owner_client.get("/api/data/config-history")).json()
    assert len(page["items"]) == baseline + 2
    assert [(i["kind"], i["version"], i["diff"]["new"]) for i in page["items"][:2]] == [("setting", 2, 9),
                                                                                         ("setting", 1, 7)]
    assert page["items"][0]["diff"]["key"] == "backups.keep" and page["items"][0]["author"] == "owner"
    assert (await owner_client.get("/api/data/config-history", params={"kind": "rubric"})).json()["items"] == []
    assert (await owner_client.get("/api/data/config-history", params={"kind": "bogus"})).status_code == 422
    assert (await owner_client.get("/api/data/config-history", params={"cursor": "junk"})).status_code == 422
