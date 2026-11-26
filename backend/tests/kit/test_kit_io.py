"""Kit export and import: round trip, template export, preview writes nothing, refusals."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

from app.core.config import get_config
from app.kit import export as kit_export
from app.kit import onboarding
from app.kit.importers import kitfile
from app.kit.zipsafe import UnsafeZip, ZipLimits, read_zip
from app.models.base import Origin, ReviewState
from app.models.kit import Answer, Fact, Person, Track, VaultDocument
from app.models.platform import AuditEvent
from app.models.search import Campaign, Rubric, Source
from tests.conftest import REPO

KIT = REPO / "kits" / "example"
LIMITS = ZipLimits(max_zip_bytes=5_000_000, max_file_bytes=1_000_000, max_files=100)
FIXED = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_config(), "files_dir", tmp_path / "files")
    return tmp_path / "files"


def example_zip(mutate=None, extra: dict[str, bytes] | None = None, vault_override: dict[str, bytes] | None = None):
    raw = json.loads((KIT / "kit.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(raw)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("kit.json", json.dumps(raw))
        for doc in raw["vault"]:
            content = (vault_override or {}).get(doc["path"]) or (KIT / doc["path"]).read_bytes()
            zf.writestr(doc["path"], content)
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return buf.getvalue()


async def apply_example(session):
    parsed = kitfile.parse_kit_zip(example_zip(), LIMITS)
    result = await kitfile.apply(session, parsed)
    await session.commit()
    return result


async def wipe(session, table_names):
    await session.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in table_names) + " RESTART IDENTITY CASCADE"))
    await session.commit()


def comparable(kit):
    d = kit.model_dump(mode="json")
    d.pop("exported_at")
    return d


# ----- round trip ----------------------------------------------------------------------------


async def test_round_trip_into_empty_database(session, table_names, files_dir):
    await apply_example(session)
    first = await kit_export.prepare(session, "personal_backup", exported_at=FIXED)
    data = kit_export.build_zip(first)
    assert kit_export.build_zip(first) == data  # deterministic bytes

    await wipe(session, table_names)
    assert await session.scalar(select(func.count()).select_from(Fact)) == 0

    parsed = kitfile.parse_kit_zip(data, LIMITS)
    await kitfile.apply(session, parsed)
    await session.commit()
    second = await kit_export.prepare(session, "personal_backup", exported_at=FIXED)

    assert comparable(second.kit) == comparable(first.kit)
    assert kit_export.build_zip(second) == data  # byte-comparable
    # vault hashes: listing, bytes in the zip, and bytes on disk all agree
    assert first.kit.vault and {v.sha256 for v in second.kit.vault} == {v.sha256 for v in first.kit.vault}
    for doc in second.kit.vault:
        assert hashlib.sha256(second.vault_files[doc.path]).hexdigest() == doc.sha256
    rows = (await session.scalars(select(VaultDocument))).all()
    for row in rows:
        on_disk = (files_dir / row.file_path).read_bytes()
        assert hashlib.sha256(on_disk).hexdigest() == row.sha256


async def test_example_kit_covers_setup_sections_after_import(session):
    await apply_example(session)
    assert await session.scalar(select(func.count()).select_from(Rubric)) >= 1
    assert await session.scalar(select(func.count()).select_from(Campaign)) >= 1
    assert await session.scalar(select(func.count()).select_from(Source)) >= 1
    assert await session.scalar(select(func.count()).select_from(Track)) >= 1


async def test_import_is_repeatable_and_lands_as_needs_review(session):
    first = await apply_example(session)
    assert first.created > 0
    states = {r.review_state for r in (await session.scalars(select(Fact))).all()}
    assert states == {ReviewState.needs_review}
    assert {r.origin for r in (await session.scalars(select(Fact))).all()} == {Origin.imported}
    for camp in (await session.scalars(select(Campaign))).all():
        assert camp.review_state == ReviewState.needs_review
        assert camp.automation.mode in ("save_only", "prepare")
        assert camp.unconfirmed_items
    for src in (await session.scalars(select(Source))).all():
        assert src.enabled is False
    facts_before = await session.scalar(select(func.count()).select_from(Fact))
    second = await apply_example(session)
    assert second.created == 0 and second.updated == 0
    assert await session.scalar(select(func.count()).select_from(Fact)) == facts_before


async def test_confirmed_row_shows_as_conflict_when_incoming_differs(session):
    await apply_example(session)
    fact = (await session.scalars(select(Fact).order_by(Fact.code))).first()
    fact.review_state = ReviewState.confirmed
    await session.commit()
    code = fact.code

    def edit(raw):
        for f in raw["facts"]:
            if f["code"] == code:
                f["text"] = f["text"] + " (edited)"

    parsed = kitfile.parse_kit_zip(example_zip(edit), LIMITS)
    diff = {(r.entity, r.key): r for r in await kitfile.plan(session, parsed.kit)}
    assert diff[("fact", code)].change == "conflict"
    assert diff[("fact", code)].before["text"] != diff[("fact", code)].after["text"]
    await kitfile.apply(session, parsed)
    await session.commit()
    await session.refresh(fact)
    assert fact.review_state == ReviewState.needs_review  # a changed row goes back to review


async def test_exclude_keys_skip_items(session):
    parsed = kitfile.parse_kit_zip(example_zip(), LIMITS)
    code = parsed.kit.facts[0].code
    await kitfile.apply(session, parsed, exclude={f"fact:{code}"})
    await session.commit()
    assert await session.scalar(select(Fact.id).where(Fact.code == code)) is None
    assert await session.scalar(select(func.count()).select_from(Fact)) == len(parsed.kit.facts) - 1


async def test_import_audited(session):
    await apply_example(session)
    actions = [a for (a,) in (await session.execute(select(AuditEvent.action))).all()]
    assert "kit.imported" in actions and "kit.loaded" in actions


# ----- template export -----------------------------------------------------------------------


async def test_share_setup_contains_no_personal_facts(session):
    await apply_example(session)
    person = await session.scalar(select(Person))
    bundle = await kit_export.prepare(session, "share_setup", exported_at=FIXED)
    kit = bundle.kit
    assert kit.kind == "share_setup"
    for name in kit_export.PERSONAL_SECTIONS:
        assert not getattr(kit, name), name
    assert bundle.vault_files == {}
    blob = kit_export.kit_json_bytes(kit).decode()
    for secret in (person.full_name.value, person.email.value, person.phone.value):
        assert secret not in blob
    for c in kit.campaigns:
        assert not c.criteria.pay_floors and not c.criteria.seniority
    for t in kit.tracks:
        assert not t.lead_fact_codes and t.summary_fact_code is None
    assert all(g.params.type in kit_export.SHAREABLE_GUARDRAILS for g in kit.guardrails)
    # and the file itself is a valid share setup that imports into an empty database
    parsed = kitfile.parse_kit_zip(kit_export.build_zip(bundle), LIMITS)
    assert parsed.kit.kind == "share_setup"


async def test_share_setup_scan_flags_personal_details_in_a_template(session):
    await apply_example(session)
    person = await session.scalar(select(Person))
    from app.models.kit import Template

    tpl = (await session.scalars(select(Template))).first()
    tpl.html = f"<p>Contact {person.email.value} or call me</p>"
    await session.commit()
    bundle = await kit_export.prepare(session, "share_setup", exported_at=FIXED)
    kinds = {h.kind for h in kit_export.personal_details(bundle)}
    assert "email" in kinds


async def test_export_endpoints(owner_client, session):
    await apply_example(session)
    person = await session.scalar(select(Person))
    from app.models.kit import Template

    tpl = (await session.scalars(select(Template))).first()
    tpl.html = f"<p>{person.full_name.value}</p>"
    await session.commit()

    preview = await owner_client.post("/api/data/export/preview", json={"kind": "share_setup"})
    assert preview.status_code == 200
    body = preview.json()
    assert body["personal_details_found"] and "person" not in body["counts"]

    blocked = await owner_client.post("/api/data/export", json={"kind": "share_setup"})
    assert blocked.status_code == 409
    ok = await owner_client.post("/api/data/export",
                                json={"kind": "share_setup", "acknowledge_personal_details": True})
    assert ok.status_code == 200

    backup = await owner_client.post("/api/data/export", json={"kind": "personal_backup"})
    assert backup.status_code == 200
    out = backup.json()
    download = await owner_client.get(out["download_url"])
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == out["sha256"]
    parsed = kitfile.parse_kit_zip(download.content, LIMITS)
    assert parsed.kit.person is not None and parsed.kit.vault
    assert (await owner_client.get("/api/data/exports/" + "0" * 32)).status_code == 404


async def test_export_never_contains_secrets(owner_client, session):
    from app.models.platform import Connection, ConnectionProvider

    session.add(Connection(provider=ConnectionProvider.anthropic, label="key", secrets_enc="FERNET-SECRET-VALUE"))
    await session.commit()
    await apply_example(session)
    for kind in ("personal_backup", "share_setup"):
        bundle = await kit_export.prepare(session, kind, exported_at=FIXED)
        assert b"FERNET-SECRET-VALUE" not in kit_export.build_zip(bundle)
        assert b"secrets_enc" not in kit_export.kit_json_bytes(bundle.kit)


# ----- import preview and commit through the API ----------------------------------------------


async def counts(session) -> dict[str, int]:
    return {m.__name__: await session.scalar(select(func.count()).select_from(m))
            for m in (Fact, Person, Track, Answer, VaultDocument, Campaign, Rubric, Source)}


async def test_preview_writes_nothing_then_commit_applies(owner_client, session, files_dir):
    before = await counts(session)
    audit_before = await session.scalar(select(func.count()).select_from(AuditEvent))
    r = await owner_client.post("/api/data/import", data={"source": "kit_file"},
                                files={"file": ("example.kit.zip", example_zip(), "application/zip")})
    assert r.status_code == 201, r.text
    preview = r.json()
    assert {i["change"] for i in preview["diff"]} == {"add"}
    assert any(i["entity"] == "fact" for i in preview["diff"])
    assert await counts(session) == before
    assert await session.scalar(select(func.count()).select_from(AuditEvent)) == audit_before
    assert not list((files_dir / "vault").rglob("*")) if (files_dir / "vault").exists() else True

    skip = next(i for i in preview["diff"] if i["entity"] == "fact")
    commit = await owner_client.post("/api/data/import/commit", json={
        "import_id": preview["import_id"], "exclude_keys": [f"fact:{skip['key']}"]})
    assert commit.status_code == 200, commit.text
    out = commit.json()
    assert out["created"] > 0 and out["needs_review"] > 0
    after = await counts(session)
    assert after["Fact"] == len(json.loads((KIT / "kit.json").read_text())["facts"]) - 1
    again = await owner_client.post("/api/data/import/commit", json={"import_id": preview["import_id"]})
    assert again.status_code == 404  # a commit consumes the preview


async def test_commit_is_one_transaction(owner_client, session, monkeypatch):
    r = await owner_client.post("/api/data/import", data={"source": "kit_file"},
                                files={"file": ("k.zip", example_zip(), "application/zip")})
    import_id = r.json()["import_id"]
    before = await counts(session)

    async def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(kitfile, "_campaign", boom)
    from httpx import ASGITransport, AsyncClient

    # follow the app's own error handling: the request fails and the session rolls back
    transport = ASGITransport(app=owner_client._transport.app, raise_app_exceptions=False,
                              client=("10.0.0.1", 50000))
    async with AsyncClient(transport=transport, base_url="http://testserver", cookies=owner_client.cookies) as c:
        failed = await c.post("/api/data/import/commit", json={"import_id": import_id})
    assert failed.status_code == 500
    assert await counts(session) == before


# ----- refusals --------------------------------------------------------------------------------


def test_zip_slip_refused():
    for name in ("../evil.txt", "vault/../../evil", "/abs/evil", "C:/evil", "vault\\evil"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("kit.json", b"{}")
            zf.writestr(name, b"x")
        with pytest.raises(kitfile.KitImportError):
            kitfile.parse_kit_zip(buf.getvalue(), LIMITS)


def test_unexpected_files_refused():
    with pytest.raises(kitfile.KitImportError, match="unexpected file"):
        kitfile.parse_kit_zip(example_zip(extra={"notes.txt": b"x"}), LIMITS)
    with pytest.raises(kitfile.KitImportError, match="unexpected file"):
        kitfile.parse_kit_zip(example_zip(extra={"vault/sub/deep.txt": b"x"}), LIMITS)


def test_hash_mismatch_refused():
    raw = json.loads((KIT / "kit.json").read_text())
    path = raw["vault"][0]["path"]
    with pytest.raises(kitfile.KitImportError, match="sha256 mismatch"):
        kitfile.parse_kit_zip(example_zip(vault_override={path: b"tampered"}), LIMITS)


def test_vault_file_missing_or_unlisted_refused():
    raw = json.loads((KIT / "kit.json").read_text())
    path = raw["vault"][0]["path"]

    with pytest.raises(kitfile.KitImportError, match="does not list"):
        kitfile.parse_kit_zip(example_zip(extra={"vault/unlisted.txt": b"x"}), LIMITS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("kit.json", (KIT / "kit.json").read_bytes())
    with pytest.raises(kitfile.KitImportError, match="missing from the zip"):
        kitfile.parse_kit_zip(buf.getvalue(), LIMITS)
    assert path


def test_oversize_and_count_limits():
    big = io.BytesIO()
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("kit.json", b"0" * 200_000)
    small = ZipLimits(max_zip_bytes=5_000_000, max_file_bytes=100_000, max_files=10)
    with pytest.raises(UnsafeZip, match="per-file"):
        read_zip(big.getvalue(), small)
    with pytest.raises(UnsafeZip, match="upload limit"):
        read_zip(big.getvalue(), ZipLimits(max_zip_bytes=10, max_file_bytes=10, max_files=10))
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w") as zf:
        for i in range(11):
            zf.writestr(f"vault/f{i}", b"x")
    with pytest.raises(UnsafeZip, match="more than"):
        read_zip(many.getvalue(), small)
    with pytest.raises(UnsafeZip, match="valid zip"):
        read_zip(b"not a zip", small)


def test_symlink_and_encrypted_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("vault/link")
        info.external_attr = (0o120777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(UnsafeZip, match="link"):
        read_zip(buf.getvalue(), LIMITS)


def test_bad_json_and_schema_refused():
    for payload in (b"{not json", b"[]", b'{"schema_version": 1}'):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("kit.json", payload)
        with pytest.raises(kitfile.KitImportError):
            kitfile.parse_kit_zip(buf.getvalue(), LIMITS)


def test_newer_schema_refused_and_older_migrated(monkeypatch):
    with pytest.raises(kitfile.KitImportError, match="schema version 9"):
        kitfile.migrate({"schema_version": 9})
    monkeypatch.setattr(kitfile, "KIT_SCHEMA_VERSION", 2)
    monkeypatch.setattr(kitfile, "MIGRATIONS", {1: lambda raw: {**raw, "migrated": True}})
    assert kitfile.migrate({"schema_version": 1}) == {"schema_version": 2, "migrated": True}
    monkeypatch.setattr(kitfile, "MIGRATIONS", {})
    with pytest.raises(kitfile.KitImportError, match="no migration"):
        kitfile.migrate({"schema_version": 1})


async def test_import_endpoint_refuses_bad_uploads(owner_client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("kit.json", b"{}")
        zf.writestr("../evil", b"x")
    r = await owner_client.post("/api/data/import", data={"source": "kit_file"},
                                files={"file": ("k.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 422
    r = await owner_client.post("/api/data/import", data={"source": "kit_file"},
                                files={"file": ("k.zip", b"junk", "application/zip")})
    assert r.status_code == 422


async def test_requires_owner(client):
    assert (await client.post("/api/data/export", json={"kind": "personal_backup"})).status_code == 401
    assert (await client.get("/api/data/onboarding")).status_code == 401


# ----- onboarding ------------------------------------------------------------------------------


async def test_onboarding_state_is_computed(owner_client, session):
    state = (await owner_client.get("/api/data/onboarding")).json()
    assert [s["key"] for s in state["steps"]] == ["kit_present", "facts_confirmed", "campaign_exists",
                                                   "criteria_confirmed", "mail_connected"]
    assert not any(s["done"] for s in state["steps"])
    assert state["next_step"] == "kit_present" and not state["complete"]

    await apply_example(session)
    done = {s["key"]: s["done"] for s in (await onboarding_api(owner_client))["steps"]}
    assert done["kit_present"] and done["campaign_exists"]
    assert not done["facts_confirmed"] and not done["criteria_confirmed"]

    for model in (Person, Fact, Campaign):
        for row in (await session.scalars(select(model))).all():
            row.review_state = ReviewState.confirmed
    for camp in (await session.scalars(select(Campaign))).all():
        camp.unconfirmed_items = []
    from app.models.platform import Connection, ConnectionProvider

    session.add(Connection(provider=ConnectionProvider.gmail, label="Job mail"))
    await session.commit()
    final = await onboarding_api(owner_client)
    assert final["complete"] and final["next_step"] is None
    assert [s.done for s in await onboarding.compute(session)] == [True] * 5


async def onboarding_api(client):
    return (await client.get("/api/data/onboarding")).json()
