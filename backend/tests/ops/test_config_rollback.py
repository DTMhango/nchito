"""Config history rollback: a restore is a NEW revision, validated like any change, audited, and cannot get
around a setting's own endpoint or the model-route test rule."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.settings import service as settings_service
from app.models.platform import AuditEvent, ConfigKind, ConfigRevision, SettingRevision


async def _history(owner_client, **params):
    return (await owner_client.get("/api/data/config-history", params=params)).json()["items"]


async def test_a_setting_is_restored_as_a_new_revision_and_audited(owner_client, session) -> None:
    for value in (7, 9, 11):
        await settings_service.set_value(session, "backups.keep", value, actor="owner")
        await session.commit()
    items = [i for i in await _history(owner_client, kind="setting") if i["diff"]["key"] == "backups.keep"]
    first = next(i for i in items if i["diff"]["new"] == 7)
    r = await owner_client.post(f"/api/data/config-history/{first['id']}/rollback", json={"note": "was better"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 4 and body["rollback_of"] == first["id"] and body["note"] == "was better"
    assert body["diff"] == {"key": "backups.keep", "old": 11, "new": 7}
    assert await settings_service.get_value(session, "backups.keep") == 7
    listed = await _history(owner_client, kind="setting")
    assert next(i for i in listed if i["id"] == body["id"])["rollback_of"] == first["id"]
    assert len([i for i in listed if i["diff"]["key"] == "backups.keep"]) == 4  # history only grew
    audited = await session.scalars(select(AuditEvent).where(AuditEvent.action == "config.rolled_back"))
    assert [e.subject_id for e in audited] == ["backups.keep"]


async def test_restoring_the_current_value_is_refused(owner_client, session) -> None:
    await settings_service.set_value(session, "backups.keep", 8, actor="owner")
    await session.commit()
    rev = (await session.scalars(select(SettingRevision).where(SettingRevision.key == "backups.keep"))).one()
    r = await owner_client.post(f"/api/data/config-history/{rev.id}/rollback", json={})
    assert r.status_code == 409 and "already" in r.json()["detail"]


async def test_a_value_that_no_longer_validates_is_refused_and_nothing_changes(owner_client, session) -> None:
    await settings_service.set_value(session, "backups.keep", 9, actor="owner")
    bad = SettingRevision(key="backups.keep", version=99, old_value=9, new_value=-5, changed_by="owner")
    session.add(bad)  # a stored value the validator rejects now
    await session.commit()
    first = bad
    r = await owner_client.post(f"/api/data/config-history/{first.id}/rollback", json={})
    assert r.status_code == 422
    assert await settings_service.get_value(session, "backups.keep") == 9


async def test_the_pause_cannot_be_restored_around_its_own_endpoint(owner_client, session) -> None:
    session.add(SettingRevision(key="automation.paused", version=1, old_value=True, new_value=False,
                                changed_by="owner", reason="test"))
    await session.commit()
    rev = (await session.scalars(select(SettingRevision).where(SettingRevision.key == "automation.paused"))).one()
    r = await owner_client.post(f"/api/data/config-history/{rev.id}/rollback", json={})
    assert r.status_code == 409 and "/api/autopilot" in r.json()["detail"]


async def test_an_earlier_prompt_version_becomes_active_again(owner_client, session) -> None:
    stage = (await owner_client.get("/api/kit/prompts")).json()[0]["stage"]
    ids = []
    for text in ("Second wording.", "Third wording."):
        made = (await owner_client.post("/api/kit/prompts", json={"stage": stage, "text": text})).json()
        ids.append(made["id"])
        assert (await owner_client.post(f"/api/kit/prompts/{made['id']}/activate")).status_code == 200
    prompt_rows = await _history(owner_client, kind="prompt")
    activated = [i for i in prompt_rows if i["note"] and i["note"].startswith("activated")]
    older = next(i for i in activated if i["diff"]["to_version"] == 2)
    r = await owner_client.post(f"/api/data/config-history/{older['id']}/rollback", json={})
    assert r.status_code == 200, r.text
    assert r.json()["rollback_of"] == older["id"] and r.json()["kind"] == "prompt"
    prompts = (await owner_client.get("/api/kit/prompts", params={"stage": stage})).json()
    assert [p["version"] for p in prompts if p["active"]] == [2]
    again = await owner_client.post(f"/api/data/config-history/{older['id']}/rollback", json={})
    assert again.status_code == 409  # now already the active one


async def test_a_model_route_still_needs_a_passing_test(owner_client, session) -> None:
    values = await settings_service.values(session)
    stage_rev = ConfigRevision(kind=ConfigKind.model_routing, subject_id=uuid.uuid4(), version=1, author="owner",
                               snapshot={"stage": "extract", "provider": values["ai.provider"], "model": "m-old"})
    session.add(stage_rev)
    await session.commit()
    r = await owner_client.post(f"/api/data/config-history/{stage_rev.id}/rollback", json={})
    assert r.status_code == 409 and "successfully before activating" in r.json()["detail"]


async def test_unknown_revision_and_unsupported_kinds(owner_client, session) -> None:
    assert (await owner_client.post(f"/api/data/config-history/{uuid.uuid4()}/rollback", json={})).status_code == 404
    rubric = ConfigRevision(kind=ConfigKind.rubric, subject_id=None, version=1, author="owner", snapshot={})
    session.add(rubric)
    await session.commit()
    r = await owner_client.post(f"/api/data/config-history/{rubric.id}/rollback", json={})
    assert r.status_code == 409
