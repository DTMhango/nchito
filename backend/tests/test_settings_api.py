from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def test_settings_require_owner(client):
    assert (await client.get("/api/settings")).status_code == 401
    assert (await client.put("/api/settings/general.timezone", json={"value": "UTC"})).status_code == 401


async def test_list_grouped_with_metadata(owner_client):
    body = (await owner_client.get("/api/settings")).json()
    groups = {g["key"]: g for g in body["groups"]}
    assert {"general", "scoring", "automation", "appearance", "budget"} <= set(groups)
    tz = next(s for s in groups["general"]["settings"] if s["key"] == "general.timezone")
    assert tz["value"] == "Africa/Lusaka" and tz["default"] == "Africa/Lusaka"
    cap = next(s for s in groups["budget"]["settings"] if s["key"] == "budget.monthly_cap_minor")
    assert cap["value"] is None and cap["nullable"] is True
    mode = next(s for s in groups["automation"]["settings"] if s["key"] == "automation.default_mode")
    assert mode["choices"] == ["save_only", "prepare", "ask_then_apply", "auto_apply"]
    assert mode["value"] == "prepare"


async def test_put_history_and_audit(owner_client):
    r = await owner_client.put("/api/settings/automation.daily_cap", json={"value": 3, "reason": "go slow"})
    assert r.status_code == 200
    assert r.json()["value"] == 3 and r.json()["version"] == 1 and r.json()["updated_by"] == "owner"
    await owner_client.put("/api/settings/automation.daily_cap", json={"value": 4})

    hist = (await owner_client.get("/api/settings/automation.daily_cap/history")).json()
    assert [(h["version"], h["old_value"], h["new_value"]) for h in hist] == [(2, 3, 4), (1, 5, 3)]
    assert hist[1]["reason"] == "go slow"

    audit = (await owner_client.get("/api/audit", params={"subject_type": "setting",
                                                          "subject_id": "automation.daily_cap"})).json()
    assert len(audit["items"]) == 2
    assert audit["items"][0]["detail"]["new"] == 4


async def test_invalid_values_rejected_and_unchanged(owner_client):
    r = await owner_client.put("/api/settings/automation.daily_cap", json={"value": "five"})
    assert r.status_code == 422
    r = await owner_client.put("/api/settings/automation.daily_cap", json={"value": 50})  # > weekly cap 20
    assert r.status_code == 422 and "weekly" in r.json()["detail"]
    r = await owner_client.put("/api/settings/scoring.threshold_tailor", json={"value": 95})  # > auto 85
    assert r.status_code == 422
    assert (await owner_client.get("/api/settings/automation.daily_cap")).json()["value"] == 5
    assert (await owner_client.put("/api/settings/nope.nope", json={"value": 1})).status_code == 404
    assert (await owner_client.get("/api/settings/automation.daily_cap/history")).json() == []


async def test_app_name_override(owner_client):
    await owner_client.put("/api/settings/general.app_name", json={"value": "Kazi"})
    assert (await owner_client.get("/api/auth/me")).json()["app_name"] == "Kazi"


async def test_appearance_roundtrip(owner_client, client):
    default = (await client.get("/api/settings/appearance")).json()
    # Same defaults as the frontend's DEFAULT_APPEARANCE.
    assert default == {"theme_id": "copperbelt", "mode": "system", "density": "comfortable", "radius": None,
                       "font_scale": 1.0, "accent_override": None, "reduced_motion": False}
    new = {**default, "theme_id": "workshop", "mode": "dark", "density": "compact",
           "radius": 4, "font_scale": 15 / 14, "accent_override": "cobalt", "reduced_motion": True}
    r = await owner_client.put("/api/settings/appearance", json=new)
    assert r.status_code == 200 and r.json() == new
    assert (await owner_client.get("/api/settings/appearance")).json() == new
    hexed = {**new, "accent_override": "#1F4FD8"}
    assert (await owner_client.put("/api/settings/appearance", json=hexed)).json() == hexed

    bad = await owner_client.put("/api/settings/appearance", json={**new, "theme_id": "no-such-theme"})
    assert bad.status_code == 422
    bad = await owner_client.put("/api/settings/appearance", json={**new, "accent_override": "not a colour"})
    assert bad.status_code == 422
    bad = await owner_client.put("/api/settings/appearance", json={**new, "font_scale": 1.5})
    assert bad.status_code == 422


async def test_setting_revisions_are_append_only(owner_client, session):
    await owner_client.put("/api/settings/automation.daily_cap", json={"value": 3})
    with pytest.raises(DBAPIError):
        await session.execute(text("UPDATE setting_revision SET new_value = '99'"))
    await session.rollback()
    with pytest.raises(DBAPIError):
        await session.execute(text("DELETE FROM audit_event"))
