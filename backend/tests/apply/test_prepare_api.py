"""``POST /applications/{id}/packet/prepare``: the pipeline's prepare_packet behind the Studio's "Send for
approval" (invented data only, example.com addresses)."""

from __future__ import annotations

import pytest

from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.models.applications import Stage
from app.models.platform import Connection, ConnectionProvider
from tests.tailoring.helpers import good_spec, world

ME = "owner.example@example.com"
POSTED = "jobs@acme.example.com"


@pytest.fixture(autouse=True)
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(get_config(), "files_dir", tmp_path / "files")


async def _seeded(*, mailbox: bool = True, stage: Stage = Stage.shortlisted):
    async with get_sessionmaker()() as s:
        w = await world(s, raw_text=f"We need a data analyst with SQL. Apply by email to {POSTED}.", stage=stage)
        w.job.apply_email = POSTED
        if mailbox:
            s.add(Connection(provider=ConnectionProvider.imap_smtp, label="Mail", enabled=True, health="ok",
                             scopes_granted=[], config={"from_address": ME, "imap_host": "imap.example.com",
                                                        "smtp_host": "smtp.example.com"}))
        await s.commit()
    return w


async def test_nothing_to_prepare_without_a_checked_spec(owner_client):
    w = await _seeded()
    r = await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_spec", r.text


async def test_unconfirmed_address_goes_manual_then_email_once_confirmed(owner_client):
    w = await _seeded()
    assert (await owner_client.put(f"/api/applications/{w.app.id}/spec", json={"spec": good_spec(w)})).status_code \
        == 200
    r = await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare", json={})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["channel"] == "manual" and first["created"]
    assert first["packet"]["contents"]["destination"]["url"] == f"mailto:{POSTED}"
    assert {f["kind"] for f in first["packet"]["contents"]["files"]} == {"cv", "letter"}

    confirmed = await owner_client.put(f"/api/jobs/{w.job.id}/apply-email", json={"confirmed": True})
    assert confirmed.json()["apply_email"]["usable"]
    r = await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare", json={})
    second = r.json()
    assert second["channel"] == "email" and second["packet"]["version"] == 2
    assert second["packet"]["contents"]["email"]["to"] == [POSTED]
    assert second["packet"]["contents"]["sending_identity"] == ME
    # Asked for manual, it is manual whatever the address.
    manual = (await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare",
                                      json={"channel": "manual"})).json()
    assert manual["channel"] == "manual"


async def test_templates_are_honoured_and_an_unknown_one_is_refused(owner_client):
    w = await _seeded()
    await owner_client.put(f"/api/applications/{w.app.id}/spec", json={"spec": good_spec(w)})
    r = await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare", json={"cv_template": "compact"})
    assert r.status_code == 200, r.text
    docs = (await owner_client.get(f"/api/applications/{w.app.id}/documents")).json()
    cv_ids = {f["document_id"] for f in r.json()["packet"]["contents"]["files"] if f["kind"] == "cv"}
    assert {d["template_key"] for d in docs if d["id"] in cv_ids} == {"compact"}
    bad = await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare", json={"cv_template": "nope"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "unknown_template"


async def test_gone_out_cannot_be_prepared(owner_client):
    w = await _seeded(stage=Stage.submitted)
    r = await owner_client.post(f"/api/applications/{w.app.id}/packet/prepare", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "illegal_stage"
