from __future__ import annotations

import pyotp
from sqlalchemy import select

from app.core.config import get_config
from app.models.platform import AuditEvent
from tests.conftest import OWNER


async def test_setup_flow(client):
    r = await client.get("/api/setup/status")
    assert r.json() == {"owner_exists": False}

    r = await client.post("/api/setup/owner", json=OWNER)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == OWNER["email"]
    assert body["timezone"] == "Africa/Lusaka"
    assert body["app_name"] == "Nchito"
    assert get_config().session_cookie_name in r.cookies

    assert (await client.get("/api/setup/status")).json() == {"owner_exists": True}
    again = await client.post("/api/setup/owner", json={**OWNER, "email": "other@example.com"})
    assert again.status_code == 409


async def test_setup_rejects_weak_password_and_bad_timezone(client):
    r = await client.post("/api/setup/owner", json={**OWNER, "password": "short"})
    assert r.status_code == 422
    r = await client.post("/api/setup/owner", json={**OWNER, "timezone": "Mars/Olympus"})
    assert r.status_code == 422
    assert (await client.get("/api/setup/status")).json() == {"owner_exists": False}


async def test_me_requires_session(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_login_logout(owner_client, session):
    client = owner_client
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).status_code == 401

    bad = await client.post("/api/auth/login", json={"email": OWNER["email"], "password": "wrong password!!"})
    assert bad.status_code == 401

    ok = await client.post("/api/auth/login", json={"email": OWNER["email"].upper(), "password": OWNER["password"]})
    assert ok.status_code == 204
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": OWNER["email"], "display_name": OWNER["display_name"],
                         "timezone": "Africa/Lusaka", "app_name": "Nchito", "totp_enabled": False}

    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401

    actions = (await session.scalars(select(AuditEvent.action))).all()
    assert {"owner.created", "auth.login", "auth.logout"} <= set(actions)


async def test_revoked_session_cookie_is_useless(owner_client):
    stolen = dict(owner_client.cookies)
    await owner_client.post("/api/auth/logout")
    owner_client.cookies.update(stolen)
    assert (await owner_client.get("/api/auth/me")).status_code == 401


async def test_tampered_cookie_rejected(owner_client):
    name = get_config().session_cookie_name
    owner_client.cookies.set(name, owner_client.cookies[name] + "x")
    assert (await owner_client.get("/api/auth/me")).status_code == 401


async def test_login_rate_limit(owner_client):
    client = owner_client
    client.cookies.clear()
    limit = get_config().login_rate_limit_attempts
    for _ in range(limit):
        r = await client.post("/api/auth/login", json={"email": OWNER["email"], "password": "not the password"})
        assert r.status_code == 401
    blocked = await client.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]})
    assert blocked.status_code == 429


async def test_totp_flow(owner_client):
    client = owner_client
    setup = (await client.post("/api/auth/totp/setup")).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(setup["secret"])
    assert (await client.post("/api/auth/totp/enable", json={"code": "000000" if totp.now() != "000000"
                                                              else "111111"})).status_code == 422
    assert (await client.post("/api/auth/totp/enable", json={"code": totp.now()})).status_code == 204

    client.cookies.clear()
    creds = {"email": OWNER["email"], "password": OWNER["password"]}
    r = await client.post("/api/auth/login", json=creds)
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    r = await client.post("/api/auth/login", json={**creds, "totp": totp.now()})
    assert r.status_code == 204
    assert (await client.get("/api/auth/me")).json()["totp_enabled"] is True


async def test_change_password(owner_client):
    r = await owner_client.post("/api/auth/password", json={"current_password": "nope nope nope",
                                                            "new_password": "another long passphrase"})
    assert r.status_code == 403
    r = await owner_client.post("/api/auth/password", json={"current_password": OWNER["password"],
                                                            "new_password": "another long passphrase"})
    assert r.status_code == 204
    owner_client.cookies.clear()
    r = await owner_client.post("/api/auth/login", json={"email": OWNER["email"],
                                                         "password": "another long passphrase"})
    assert r.status_code == 204


async def test_csrf_cross_site_requests_refused(owner_client):
    r = await owner_client.put("/api/settings/general.display_currency", json={"value": "ZMW"},
                               headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = await owner_client.put("/api/settings/general.display_currency", json={"value": "ZMW"},
                               headers={"Origin": "https://evil.example.net"})
    assert r.status_code == 403
    r = await owner_client.put("/api/settings/general.display_currency", json={"value": "ZMW"},
                               headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"})
    assert r.status_code == 200
    # Safe methods are never blocked.
    r = await owner_client.get("/api/auth/me", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


async def test_sessions_list_revoke(owner_client, app):
    import httpx

    first = owner_client
    transport = httpx.ASGITransport(app=app, client=("10.0.0.2", 50001))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as second:
        r = await second.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]},
                              headers={"user-agent": "phone"})
        assert r.status_code == 204
        rows = (await first.get("/api/auth/sessions")).json()
        assert len(rows) == 2
        assert sum(x["current"] for x in rows) == 1
        other = next(x for x in rows if not x["current"])
        assert other["user_agent"] == "phone" and other["ip"] == "10.0.0.2"
        assert (await second.get("/api/auth/me")).status_code == 200
        assert (await first.delete(f"/api/auth/sessions/{other['id']}")).status_code == 204
        assert (await second.get("/api/auth/me")).status_code == 401
        assert (await first.delete(f"/api/auth/sessions/{other['id']}")).status_code == 404
        assert len((await first.get("/api/auth/sessions")).json()) == 1


async def test_revoke_others_and_password_change(owner_client, app, session):
    import httpx

    first = owner_client
    transport = httpx.ASGITransport(app=app, client=("10.0.0.2", 50001))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as second:
        await second.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]})
        assert (await first.post("/api/auth/sessions/revoke-others")).json() == {"revoked": 1}
        assert (await second.get("/api/auth/me")).status_code == 401
        assert (await first.get("/api/auth/me")).status_code == 200
        await second.post("/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]})
        r = await first.post("/api/auth/password", json={"current_password": OWNER["password"],
                                                         "new_password": "another long passphrase 1"})
        assert r.status_code == 204
        assert (await second.get("/api/auth/me")).status_code == 401
        assert (await first.get("/api/auth/me")).status_code == 200
    actions = set((await session.scalars(select(AuditEvent.action))).all())
    assert {"auth.sessions_revoked_others", "auth.password_changed"} <= actions
