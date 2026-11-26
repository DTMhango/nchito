"""Mail endpoints: connect (IMAP), Gmail OAuth, test, disconnect, mail threads. Secrets never leave."""

# ruff: noqa: E501  (invented fixtures and long assertions)
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app.connect import mail_connections
from app.core.config import get_config
from app.models.applications import MailClassification, MailThread, PendingAction, Stage
from app.models.platform import AuditEvent, Connection
from tests.mail.helpers import ME, FakeHttp, FakeImap, FakeSmtp, make_setup

PASSWORD = "app-password-very-secret-123"
IMAP = {"provider": "imap_smtp", "label": "Work mail",
        "config": {"from_address": ME, "imap_host": "imap.example.com", "smtp_host": "smtp.example.com",
                   "read_folder": "Jobs"},
        "secrets": {"password": PASSWORD}}


async def connect_imap(client, **over):
    return await client.post("/api/connections", json={**IMAP, **over})


async def test_connect_imap_encrypts_and_masks_the_password(owner_client, session, caplog):
    caplog.set_level(logging.DEBUG)
    r = await connect_imap(owner_client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert PASSWORD not in r.text and body["secrets_masked"]["password"].endswith(PASSWORD[-4:])
    assert "folder" in body["reads_description"] and "Jobs" in body["reads_description"]
    row = await session.get(Connection, body["id"])
    assert row.secrets_enc and PASSWORD not in row.secrets_enc
    listed = await owner_client.get("/api/connections")
    assert PASSWORD not in listed.text
    audit_text = " ".join(str(e.detail) for e in await session.scalars(select(AuditEvent)))
    assert PASSWORD not in audit_text and PASSWORD not in caplog.text


async def test_connect_validates_and_gmail_must_use_oauth(owner_client):
    assert (await connect_imap(owner_client, secrets={})).status_code == 422
    bad = {**IMAP["config"], "imap_port": 70000}
    assert (await connect_imap(owner_client, config=bad)).status_code == 422
    extra = {**IMAP["config"], "password": "oops"}
    assert (await connect_imap(owner_client, config=extra)).status_code == 422
    r = await owner_client.post("/api/connections", json={"provider": "gmail", "label": "g", "config": {}})
    assert r.status_code == 422 and "Google sign-in" in r.text


async def test_update_keeps_secrets_unless_replaced_and_cannot_set_internal_keys(owner_client, session):
    cid = (await connect_imap(owner_client)).json()["id"]
    r = await owner_client.put(f"/api/connections/{cid}", json={"config": {"read_folder": "Inbox", "checkpoint_at": "x"},
                                                                "secrets": {"password": ""}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config"]["read_folder"] == "Inbox" and "checkpoint_at" not in body["config"]
    assert body["secrets_masked"]["password"].endswith(PASSWORD[-4:])  # blank keeps the stored one
    assert PASSWORD not in r.text


async def test_test_endpoint_reports_health_without_secrets(owner_client, monkeypatch):
    cid = (await connect_imap(owner_client)).json()["id"]
    imap = FakeImap()
    real = mail_connections.build_mailbox
    monkeypatch.setattr(mail_connections, "build_mailbox",
                        lambda conn, **kw: real(conn, smtp=FakeSmtp(), imap=imap))
    r = await owner_client.post(f"/api/connections/{cid}/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    imap.ok = False
    r = await owner_client.post(f"/api/connections/{cid}/test")
    assert r.json()["ok"] is False and PASSWORD not in r.text
    listed = (await owner_client.get("/api/connections")).json()
    assert listed[0]["health"] == "failing"


async def test_disconnect_deletes_the_connection_and_audits(owner_client, session):
    cid = (await connect_imap(owner_client)).json()["id"]
    r = await owner_client.delete(f"/api/connections/{cid}")
    assert r.status_code == 204
    assert await session.get(Connection, cid) is None
    actions = list(await session.scalars(select(AuditEvent.action)))
    assert "connection.deleted" in actions


async def test_gmail_oauth_start_needs_server_credentials_then_returns_the_consent_url(owner_client, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "google_oauth_client_id", None)
    monkeypatch.setattr(cfg, "google_oauth_client_secret", None)
    assert (await owner_client.post("/api/connections/oauth/gmail/start")).status_code == 409
    monkeypatch.setattr(cfg, "google_oauth_client_id", "cid-1")
    monkeypatch.setattr(cfg, "google_oauth_client_secret", "csecret-1")
    r = await owner_client.post("/api/connections/oauth/gmail/start")
    assert r.status_code == 200
    url = urlsplit(r.json()["authorize_url"])
    q = parse_qs(url.query)
    assert q["client_id"] == ["cid-1"] and q["redirect_uri"] == ["http://testserver/api/connections/oauth/gmail/callback"]
    assert q["access_type"] == ["offline"] and "csecret-1" not in r.text
    assert set(q["scope"][0].split()) == {"https://www.googleapis.com/auth/gmail.send",
                                          "https://www.googleapis.com/auth/gmail.readonly"}
    assert (await owner_client.post("/api/connections/oauth/msgraph/start")).status_code == 501  # not built yet


async def test_gmail_oauth_callback_stores_encrypted_tokens(owner_client, session, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "google_oauth_client_id", "cid-1")
    monkeypatch.setattr(cfg, "google_oauth_client_secret", "csecret-1")
    state = parse_qs(urlsplit((await owner_client.post("/api/connections/oauth/gmail/start")).json()
                              ["authorize_url"]).query)["state"][0]

    def handler(method, url, params, json, form, headers):
        if "oauth2.googleapis.com" in url:
            assert form["code"] == "code-1" and form["grant_type"] == "authorization_code"
            return 200, {"access_token": "acc-tok-1", "refresh_token": "ref-tok-1", "expires_in": 3600,
                         "scope": "https://www.googleapis.com/auth/gmail.send "
                                  "https://www.googleapis.com/auth/gmail.readonly"}
        return 200, {"emailAddress": "owner.jobs@example.com"}

    monkeypatch.setattr(mail_connections, "HttpxTransport", lambda: FakeHttp(handler))
    r = await owner_client.get("/api/connections/oauth/gmail/callback", params={"code": "code-1", "state": state},
                               follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith("/settings/connections")
    row = (await session.scalars(select(Connection))).one()
    assert row.config == {"from_address": "owner.jobs@example.com"} and row.provider.value == "gmail"
    assert "acc-tok-1" not in row.secrets_enc and "ref-tok-1" not in row.secrets_enc
    assert mail_connections.read_secrets(row)["refresh_token"] == "ref-tok-1"
    listed = await owner_client.get("/api/connections")
    assert "ref-tok-1" not in listed.text and "acc-tok-1" not in listed.text
    assert "gmail.readonly" in listed.json()[0]["scopes_granted"][1]
    assert "whole mailbox" in listed.json()[0]["reads_description"]


async def test_oauth_callback_rejects_a_forged_state(owner_client, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "google_oauth_client_id", "cid-1")
    monkeypatch.setattr(cfg, "google_oauth_client_secret", "csecret-1")
    r = await owner_client.get("/api/connections/oauth/gmail/callback", params={"code": "c", "state": "forged"},
                               follow_redirects=False)
    assert r.status_code == 400


# ----- mail threads ---------------------------------------------------------------------------------------


async def thread_for(session, **kw) -> MailThread:
    conn = Connection(provider=mail_connections.ConnectionProvider.imap_smtp, label="m", config={}, scopes_granted=[])
    session.add(conn)
    await session.flush()
    t = MailThread(connection_id=conn.id, provider_thread_id=kw.pop("tid", "t1"), provider_message_ids=["m1"],
                   subject="Re: your application", classification=MailClassification.rejection, **kw)
    session.add(t)
    await session.commit()
    return t


async def test_mail_threads_list_filters_by_review_and_application(owner_client, session):
    setup = await make_setup(session, stage=Stage.submitted, applied=True)
    a = await thread_for(session, tid="a", needs_review=True, match_confidence=0.4, sender="hr@acme.example.com")
    b = await thread_for(session, tid="b", needs_review=False, application_id=setup.app.id)
    r = await owner_client.get("/api/mail-threads", params={"needs_review": "true"})
    assert [t["id"] for t in r.json()["items"]] == [str(a.id)]
    assert r.json()["items"][0]["sender"] == "hr@acme.example.com"
    r = await owner_client.get("/api/mail-threads", params={"application_id": str(setup.app.id)})
    assert [t["id"] for t in r.json()["items"]] == [str(b.id)]


async def test_linking_a_thread_settles_the_review_and_proposes_never_applies(owner_client, session):
    setup = await make_setup(session, stage=Stage.submitted, applied=True)
    t = await thread_for(session, needs_review=True, match_confidence=0.4)
    r = await owner_client.put(f"/api/mail-threads/{t.id}", json={"application_id": str(setup.app.id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["application_id"] == str(setup.app.id) and body["needs_review"] is False
    assert body["match_confidence"] == 1.0
    await session.refresh(setup.app)
    assert setup.app.stage == Stage.submitted  # a rejection is proposed, not applied
    actions = list(await session.scalars(select(PendingAction)))
    assert len(actions) == 1 and actions[0].detail["proposed_stage"] == "rejected"
    # re-linking does not duplicate the proposal
    await owner_client.put(f"/api/mail-threads/{t.id}", json={"application_id": str(setup.app.id)})
    assert len(list(await session.scalars(select(PendingAction)))) == 1


async def test_reclassify_and_unlink_and_unknown_ids(owner_client, session):
    t = await thread_for(session, needs_review=True)
    r = await owner_client.put(f"/api/mail-threads/{t.id}",
                               json={"application_id": None, "classification": "information_request"})
    assert r.json()["classification"] == "information_request" and r.json()["application_id"] is None
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await owner_client.put(f"/api/mail-threads/{missing}", json={"application_id": None})).status_code == 404
    r = await owner_client.put(f"/api/mail-threads/{t.id}", json={"application_id": missing})
    assert r.status_code == 404
