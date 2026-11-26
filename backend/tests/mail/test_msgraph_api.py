"""Outlook and OneDrive endpoints, the default mailbox, the backup target, and the email channel end to end
with the Outlook mailbox over a fake Graph. Secrets never leave."""

# ruff: noqa: E501  (invented fixtures and long assertions)
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app.apply import prepare
from app.apply.channels.email import EmailChannel, default_resolver
from app.connect import mail_connections, onedrive_records
from app.connect.http_transport import set_transport
from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.models.platform import AuditEvent, Connection, ConnectionProvider
from app.ops import jobs
from tests.mail.graph_fake import OWNER, FakeGraph
from tests.mail.helpers import ME, FakeHttp, file_for, make_packet, make_setup
from tests.ops.fakes import FakeTransport
from tests.ops.test_onedrive import FakeOneDrive, respond

ACCESS, REFRESH, CLIENT_SECRET = "acc-tok-ms-1", "ref-tok-ms-1", "csecret-ms"
CV = b"%PDF-1.4 invented cv"


def configure(monkeypatch, *, tenant="common"):
    cfg = get_config()
    monkeypatch.setattr(cfg, "ms_oauth_client_id", "ms-cid")
    monkeypatch.setattr(cfg, "ms_oauth_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(cfg, "ms_oauth_tenant", tenant)


def token_answer(scope: str):
    return {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600, "scope": scope}


async def sign_in_outlook(client, monkeypatch, *, address=OWNER):
    state = parse_qs(urlsplit((await client.post("/api/connections/oauth/msgraph/start")).json()["authorize_url"]).query)["state"][0]

    def handler(method, url, params, json_, form, headers):
        if "/oauth2/v2.0/token" in url:
            assert form["code"] == "code-1" and form["client_secret"] == CLIENT_SECRET
            return 200, token_answer("Mail.Send Mail.Read User.Read")
        assert url.endswith("/me") and headers["Authorization"] == f"Bearer {ACCESS}"
        return 200, {"mail": address}

    monkeypatch.setattr(mail_connections, "HttpxTransport", lambda: FakeHttp(handler))
    return await client.get("/api/connections/oauth/msgraph/callback", params={"code": "code-1", "state": state},
                            follow_redirects=False)


# ----- Outlook sign-in --------------------------------------------------------------------------


async def test_outlook_start_needs_server_credentials_then_returns_the_consent_url(owner_client, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "ms_oauth_client_id", None)
    monkeypatch.setattr(cfg, "ms_oauth_client_secret", None)
    for provider in ("msgraph", "onedrive"):
        r = await owner_client.post(f"/api/connections/oauth/{provider}/start")
        assert r.status_code == 409 and "MS_OAUTH_CLIENT_ID" in r.json()["detail"] and "MS_OAUTH_CLIENT_SECRET" in r.json()["detail"]
    configure(monkeypatch, tenant="consumers")
    r = await owner_client.post("/api/connections/oauth/msgraph/start")
    assert r.status_code == 200 and CLIENT_SECRET not in r.text
    url = urlsplit(r.json()["authorize_url"])
    q = parse_qs(url.query)
    assert url.path == "/consumers/oauth2/v2.0/authorize"
    assert q["redirect_uri"] == ["http://testserver/api/connections/oauth/msgraph/callback"]
    assert q["scope"][0].split() == ["offline_access", "User.Read", "Mail.Send", "Mail.Read"]
    r = await owner_client.post("/api/connections/oauth/onedrive/start")
    q = parse_qs(urlsplit(r.json()["authorize_url"]).query)
    assert q["redirect_uri"] == ["http://testserver/api/connections/oauth/onedrive/callback"]
    assert q["scope"][0].split() == ["offline_access", "User.Read", "Files.ReadWrite.AppFolder"]


async def test_outlook_callback_stores_encrypted_tokens_and_signing_in_again_does_not_duplicate(owner_client, session, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    configure(monkeypatch)
    r = await sign_in_outlook(owner_client, monkeypatch)
    assert r.status_code == 307 and r.headers["location"].endswith("connected=msgraph")
    row = (await session.scalars(select(Connection))).one()
    assert row.provider.value == "msgraph" and row.config == {"from_address": OWNER}
    assert ACCESS not in row.secrets_enc and REFRESH not in row.secrets_enc
    assert mail_connections.read_secrets(row)["refresh_token"] == REFRESH
    assert row.scopes_granted == ["Mail.Send", "Mail.Read", "User.Read"]
    listed = await owner_client.get("/api/connections")
    assert ACCESS not in listed.text and REFRESH not in listed.text and CLIENT_SECRET not in listed.text
    assert "whole mailbox" in listed.json()[0]["reads_description"] and "nothing yet" in listed.json()[0]["reads_description"]
    audit_text = " ".join(str(e.detail) for e in await session.scalars(select(AuditEvent)))
    assert ACCESS not in audit_text + caplog.text and REFRESH not in audit_text + caplog.text
    await owner_client.put(f"/api/connections/{row.id}", json={"config": {"read_folder": "Jobs"}})
    await sign_in_outlook(owner_client, monkeypatch)
    rows = list(await session.scalars(select(Connection)))
    await session.refresh(rows[0])
    assert len(rows) == 1 and rows[0].config["read_folder"] == "Jobs"


async def test_outlook_callback_rejects_a_forged_state_and_pasting_keys_is_refused(owner_client, monkeypatch):
    configure(monkeypatch)
    for provider in ("msgraph", "onedrive"):
        r = await owner_client.get(f"/api/connections/oauth/{provider}/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
        assert r.status_code == 400
    for provider in ("msgraph", "onedrive"):
        r = await owner_client.post("/api/connections", json={"provider": provider, "label": "x", "config": {}})
        assert r.status_code == 422


async def test_outlook_folder_is_changeable_unknown_keys_are_not_and_test_runs_the_check(owner_client, session, monkeypatch):
    configure(monkeypatch)
    await sign_in_outlook(owner_client, monkeypatch)
    row = (await session.scalars(select(Connection))).one()
    ok = await owner_client.put(f"/api/connections/{row.id}", json={"config": {"read_folder": "Jobs"}})
    assert ok.status_code == 200 and 'folder "Jobs"' in ok.json()["reads_description"]
    assert (await owner_client.put(f"/api/connections/{row.id}", json={"config": {"read_label": "x"}})).status_code == 422
    graph = FakeGraph()
    monkeypatch.setattr(mail_connections, "HttpxTransport", lambda: graph)
    graph.valid_token = ACCESS
    done = (await owner_client.post(f"/api/connections/{row.id}/test")).json()
    assert done == {"ok": True, "detail": "connected", "cost_minor": 0, "cost_micros": 0}
    graph.folders.clear()  # the folder was deleted in Outlook
    failed = (await owner_client.post(f"/api/connections/{row.id}/test")).json()
    assert failed["ok"] is False
    assert (await owner_client.delete(f"/api/connections/{row.id}")).status_code == 204


# ----- default mailbox --------------------------------------------------------------------------


async def test_the_default_mailbox_comes_first_and_decides_the_sending_identity(owner_client, session, monkeypatch):
    from app.models.platform import Connection as C

    a = C(provider=ConnectionProvider.gmail, label="g", config={"from_address": "first@example.com"}, scopes_granted=[])
    b = C(provider=ConnectionProvider.msgraph, label="o", config={"from_address": "second@example.com"}, scopes_granted=[])
    session.add_all([a, b])
    await session.commit()
    assert (await prepare.sending_identity(session)) == "first@example.com"
    r = await owner_client.put("/api/settings/mail.default_mailbox", json={"value": str(b.id)})
    assert r.status_code == 200, r.text
    assert [c.label for c in await mail_connections.mail_connections(session)] == ["o", "g"]
    assert (await prepare.sending_identity(session)) == "second@example.com"
    assert (await owner_client.put("/api/settings/mail.default_mailbox", json={"value": "nope"})).status_code == 422
    assert (await owner_client.put("/api/settings/mail.default_mailbox", json={"value": None})).status_code == 200
    assert [c.label for c in await mail_connections.mail_connections(session)] == ["g", "o"]


# ----- OneDrive ---------------------------------------------------------------------------------


async def test_onedrive_round_trip_creates_the_connection_a_working_store_and_an_audited_share_link(owner_client, session, monkeypatch):
    configure(monkeypatch)
    state = parse_qs(urlsplit((await owner_client.post("/api/connections/oauth/onedrive/start")).json()["authorize_url"]).query)["state"][0]
    drive = FakeOneDrive()
    inner = drive.handle

    def responder(call):
        if "/oauth2/v2.0/token" in call.url and (call.data or {}).get("grant_type") == "authorization_code":
            assert call.data["client_secret"] == CLIENT_SECRET
            return respond(200, token_answer("Files.ReadWrite.AppFolder User.Read"))
        if "/oauth2/v2.0/token" in call.url:
            drive.valid = "refreshed"
            return respond(200, {"access_token": "refreshed", "expires_in": 3600})
        return inner(call)

    drive.transport.responder = responder
    drive.valid = ACCESS
    set_transport(drive.transport)
    try:
        done = await owner_client.get("/api/connections/oauth/onedrive/callback", params={"code": "good", "state": state}, follow_redirects=False)
        assert done.status_code == 307 and done.headers["location"].endswith("connected=onedrive")
        listed = (await owner_client.get("/api/connections")).json()
        assert [c["provider"] for c in listed] == ["onedrive"] and listed[0]["scopes_granted"] == ["offline_access", "User.Read", "Files.ReadWrite.AppFolder"]
        assert REFRESH not in json.dumps(listed) and ACCESS not in json.dumps(listed) and list(listed[0]["secrets_masked"]) == ["tokens"]
        assert "Nothing else" in listed[0]["reads_description"]
        conn = await session.scalar(select(Connection))
        assert ACCESS not in conn.secrets_enc and REFRESH not in conn.secrets_enc

        store = await onedrive_records.onedrive_store(session)
        await store.put("applications/a/cv.pdf", CV, "application/pdf")
        url = await store.share_link("applications/a/cv.pdf", audience="anyone_with_link")
        await session.commit()
        events = list(await session.scalars(select(AuditEvent).where(AuditEvent.action == "filestore.share_link_created")))
        assert len(events) == 1 and events[0].detail["url"] == url and events[0].detail["audience"] == "anyone_with_link"
        assert ACCESS not in json.dumps([e.detail for e in await session.scalars(select(AuditEvent))])

        tested = (await owner_client.post(f"/api/connections/{conn.id}/test")).json()
        assert tested["ok"] is True and "Nchito" in tested["detail"]
        renamed = await owner_client.put(f"/api/connections/{conn.id}", json={"label": "My OneDrive", "enabled": True})
        assert renamed.status_code == 200 and renamed.json()["label"] == "My OneDrive"
        assert (await owner_client.put(f"/api/connections/{conn.id}", json={"secrets": {"x": "y"}})).status_code == 422
        assert (await owner_client.delete(f"/api/connections/{conn.id}")).status_code == 204
    finally:
        set_transport(None)


async def test_a_onedrive_test_failure_is_reported_plainly(owner_client, session, monkeypatch):
    configure(monkeypatch)
    from app.core.crypto import encrypt

    conn = Connection(provider=ConnectionProvider.onedrive, label="OneDrive", scopes_granted=[], config={},
                      secrets_enc=encrypt(json.dumps({"tokens": {"access_token": "a", "refresh_token": "r", "expires_at": 9e12}})))
    session.add(conn)
    await session.commit()
    set_transport(FakeTransport(lambda c: respond(400, {"error": {"code": "invalidRequest"}})))
    try:
        r = (await owner_client.post(f"/api/connections/{conn.id}/test")).json()
    finally:
        set_transport(None)
    assert r["ok"] is False and "work and school" in r["detail"]
    await session.refresh(conn)
    assert conn.health == "failing"


async def test_onedrive_is_a_backup_target(session, monkeypatch):
    configure(monkeypatch)
    store, warning = await jobs.remote_store(session, "onedrive")
    assert store is None and "OneDrive unavailable" in (warning or "")  # not connected: kept locally, said so
    from app.core.crypto import encrypt

    session.add(Connection(provider=ConnectionProvider.onedrive, label="OneDrive", scopes_granted=[], config={},
                           secrets_enc=encrypt(json.dumps({"tokens": {"access_token": "a", "refresh_token": "r", "expires_at": 9e12}}))))
    await session.commit()
    store, warning = await jobs.remote_store(session, "onedrive")
    assert warning is None and store is not None and store.kind == "onedrive"


# ----- the email channel with the Outlook mailbox -----------------------------------------------


async def test_email_channel_end_to_end_with_the_outlook_mailbox(session, monkeypatch):
    configure(monkeypatch)
    graph = FakeGraph()
    graph.valid_token = ACCESS
    monkeypatch.setattr(mail_connections, "HttpxTransport", lambda: graph)
    from app.core.crypto import encrypt

    session.add(Connection(provider=ConnectionProvider.msgraph, label="Outlook", scopes_granted=[], enabled=True,
                           config={"from_address": OWNER, "read_folder": "Jobs"},
                           secrets_enc=encrypt(json.dumps({"access_token": ACCESS, "refresh_token": REFRESH,
                                                           "expires_at": "2999-01-01T00:00:00+00:00"}))))
    await session.commit()

    async def load(f):
        return CV

    channel = EmailChannel(attachments=load, sessionmaker=get_sessionmaker(), resolver=default_resolver)
    setup = await make_setup(session, contents=make_packet(files=[file_for(CV)], identity=OWNER))
    outcome = await channel.dispatch(setup.request())
    assert outcome.status == "sent" and outcome.evidence is not None and outcome.evidence.kind == "sent_mail_id"
    assert outcome.provider_message_id == f"<nchito-{setup.attempt.id}@example.com>"
    assert len(graph.sent) == 1 and graph.sent[0]["toRecipients"][0]["emailAddress"]["address"] == "hr@acme.example.com"
    draft = next(iter(graph.drafts.values()))
    assert draft["attachments"][0]["name"] == "cv.pdf" and draft["subject"] == "Application: Data Analyst"
    # A packet for another identity is not sent through this mailbox.
    other = await make_setup(session, contents=make_packet(identity=ME))
    assert (await channel.dispatch(other.request())).status == "failed" and len(graph.sent) == 1


async def test_email_channel_timeout_is_settled_from_sent_items_and_never_resent(session, monkeypatch):
    configure(monkeypatch)
    graph = FakeGraph()
    graph.valid_token = ACCESS
    graph.send_mode = "timeout_after_accept"
    monkeypatch.setattr(mail_connections, "HttpxTransport", lambda: graph)
    from app.core.crypto import encrypt

    session.add(Connection(provider=ConnectionProvider.msgraph, label="Outlook", scopes_granted=[], enabled=True,
                           config={"from_address": OWNER},
                           secrets_enc=encrypt(json.dumps({"access_token": ACCESS, "refresh_token": REFRESH,
                                                           "expires_at": "2999-01-01T00:00:00+00:00"}))))
    await session.commit()

    async def load(f):
        return CV

    setup = await make_setup(session, contents=make_packet(identity=OWNER))
    channel = EmailChannel(attachments=load, sessionmaker=get_sessionmaker(), resolver=default_resolver)
    first = await channel.dispatch(setup.request())
    assert first.status == "unknown" and len(graph.sent) == 1
    again = await EmailChannel(attachments=load, sessionmaker=get_sessionmaker(), resolver=default_resolver).dispatch(setup.request())
    assert again.status == "sent" and len(graph.sent) == 1 and len(graph.drafts) == 1  # found in Sent Items; no second draft
    assert (await channel.reconcile(str(setup.attempt.id))).status == "sent"
