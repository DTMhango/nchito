from __future__ import annotations

import hashlib
import json
import zlib

import pytest
from sqlalchemy import select

from app.core.config import get_config
from app.kit.loader import load_kit
from app.kit.schema import KitFile
from app.models.platform import AuditEvent
from tests.conftest import REPO

KIT = REPO / "kits" / "example"


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_config(), "files_dir", tmp_path / "files")
    return tmp_path / "files"


async def audit_actions(session) -> list[str]:
    return [a for (a,) in (await session.execute(select(AuditEvent.action).order_by(AuditEvent.id))).all()]


def fact_body(text="Cut reporting time by 40%.", **kw):
    return {"kind": "achievement", "text": text, **kw}


async def load_example(session):
    kit = KitFile.model_validate(json.loads((KIT / "kit.json").read_text(encoding="utf-8")))
    files = {v.path: (KIT / v.path).read_bytes() for v in kit.vault}
    report = await load_kit(session, kit, vault_files=files)
    await session.commit()
    return report


async def test_requires_owner(client):
    for path in ("/api/kit/facts", "/api/kit/person", "/api/kit/review"):
        assert (await client.get(path)).status_code == 401


# ----- person ----------------------------------------------------------------------------


async def test_person_singleton(owner_client, session):
    assert (await owner_client.get("/api/kit/person")).status_code == 404
    body = {"full_name": {"value": "Test Person"}, "home_country": "ZM",
            "email": {"value": "a@example.com", "visibility": "forms_only"}}
    r = await owner_client.put("/api/kit/person", json=body)
    assert r.status_code == 200 and r.json()["review_state"] == "confirmed"
    body["full_name"] = {"value": "Test Person Two"}
    r = await owner_client.put("/api/kit/person", json=body)
    assert r.json()["full_name"]["value"] == "Test Person Two"
    assert (await owner_client.get("/api/kit/person")).json()["email"]["visibility"] == "forms_only"
    assert await audit_actions(session) == ["auth.owner_created", "kit.person.created", "kit.person.updated"] or {
        "kit.person.created", "kit.person.updated"} <= set(await audit_actions(session))


# ----- facts -----------------------------------------------------------------------------


async def test_fact_codes_are_assigned_and_never_reused(owner_client):
    codes = []
    for i in range(3):
        r = await owner_client.post("/api/kit/facts", json=fact_body(f"Fact number {i}"))
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "draft"
        codes.append(r.json()["code"])
    assert codes == ["F-1", "F-2", "F-3"]
    last = (await owner_client.get("/api/kit/facts", params={"q": "number 2"})).json()["items"][0]
    # Deleting retires: the row and its code stay.
    assert (await owner_client.delete(f"/api/kit/facts/{last['id']}")).status_code == 204
    got = (await owner_client.get(f"/api/kit/facts/{last['id']}")).json()
    assert got["status"] == "retired" and got["code"] == "F-3"
    nxt = await owner_client.post("/api/kit/facts", json=fact_body("Another"))
    assert nxt.json()["code"] == "F-4"


async def test_fact_explicit_code_bumps_the_counter_and_duplicates_conflict(owner_client):
    r = await owner_client.post("/api/kit/facts", json=fact_body(code="F-112"))
    assert r.status_code == 201 and r.json()["code"] == "F-112"
    assert (await owner_client.post("/api/kit/facts", json=fact_body("Dup", code="F-112"))).status_code == 409
    assert (await owner_client.post("/api/kit/facts", json=fact_body("Next"))).json()["code"] == "F-113"


async def test_fact_code_cannot_change_and_edit_keeps_it(owner_client):
    f = (await owner_client.post("/api/kit/facts", json=fact_body())).json()
    r = await owner_client.put(f"/api/kit/facts/{f['id']}", json=fact_body("Edited", code=f["code"],
                                                                         tags=["a"], canonical_wording=True,
                                                                         keep_out_of_prompts=True))
    assert r.status_code == 200
    out = r.json()
    assert out["code"] == f["code"] and out["text"] == "Edited" and out["tags"] == ["a"]
    assert out["canonical_wording"] and out["keep_out_of_prompts"]
    r = await owner_client.put(f"/api/kit/facts/{f['id']}", json=fact_body("x", code="F-999"))
    assert r.status_code == 422
    r = await owner_client.put(f"/api/kit/facts/{f['id']}", json=fact_body("No code given"))
    assert r.json()["code"] == f["code"]


async def test_fact_approve_retire_and_filters(owner_client, session):
    a = (await owner_client.post("/api/kit/facts", json=fact_body("Alpha", tags=["data"], tracks=["t1"]))).json()
    await owner_client.post("/api/kit/facts", json=fact_body("Beta", kind="bullet"))
    approved = (await owner_client.post(f"/api/kit/facts/{a['id']}/approve")).json()
    assert approved["status"] == "approved"

    def listing(**p):
        return owner_client.get("/api/kit/facts", params=p)

    assert [i["code"] for i in (await listing(status="approved")).json()["items"]] == [a["code"]]
    assert (await listing(tag="data")).json()["total"] == 1
    assert (await listing(track="t1")).json()["total"] == 1
    assert (await listing(kind="bullet")).json()["total"] == 1
    assert (await listing(q="beta")).json()["total"] == 1
    retired = (await owner_client.post(f"/api/kit/facts/{a['id']}/retire")).json()
    assert retired["status"] == "retired"
    assert (await owner_client.post(f"/api/kit/facts/{a['id']}/approve")).json()["status"] == "approved"
    assert {"kit.fact.created", "kit.fact.approved", "kit.fact.retired"} <= set(await audit_actions(session))


async def test_pagination(owner_client):
    for i in range(5):
        await owner_client.post("/api/kit/facts", json=fact_body(f"F text {i}"))
    first = (await owner_client.get("/api/kit/facts", params={"limit": 2})).json()
    assert len(first["items"]) == 2 and first["total"] == 5 and first["next_cursor"]
    second = (await owner_client.get("/api/kit/facts", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    last = (await owner_client.get("/api/kit/facts", params={"limit": 2, "cursor": second["next_cursor"]})).json()
    assert len(last["items"]) == 1 and last["next_cursor"] is None
    seen = [i["code"] for i in first["items"] + second["items"] + last["items"]]
    assert len(set(seen)) == 5


# ----- the other entities ----------------------------------------------------------------


async def crud_roundtrip(client, path, create, update_patch, key):
    r = await client.post(path, json=create)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["review_state"] == "confirmed" and item["origin"] == "owner"
    r = await client.put(f"{path}/{item['id']}", json={**create, **update_patch})
    assert r.status_code == 200, r.text
    assert r.json()[key] == update_patch[key]
    assert (await client.get(f"{path}/{item['id']}")).json()[key] == update_patch[key]
    assert (await client.get(path)).json()["total"] == 1
    assert (await client.delete(f"{path}/{item['id']}")).status_code == 204
    assert (await client.get(f"{path}/{item['id']}")).status_code == 404
    return item


async def test_experience_skill_reference_track_crud(owner_client):
    await crud_roundtrip(owner_client, "/api/kit/experiences",
                         {"org": "Acme", "titles": [{"title": "Analyst", "start": "2020-01"}],
                          "start_date": "2020-01", "forbidden_titles": ["Head"]},
                         {"org": "Acme Ltd"}, "org")
    await crud_roundtrip(owner_client, "/api/kit/skills",
                         {"name": "SQL", "group": "data", "level": "advanced", "claim": "yes"},
                         {"claim": "never"}, "claim")
    await crud_roundtrip(owner_client, "/api/kit/references",
                         {"name": "Ref One", "consent": True, "share_policy": "on_request"},
                         {"share_policy": "forms_only"}, "share_policy")
    await crud_roundtrip(owner_client, "/api/kit/tracks",
                         {"key": "analytics", "name": "Analytics", "lead_fact_codes": ["F-1"]},
                         {"name": "Analytics lead"}, "name")


async def test_duplicate_skill_and_track_conflict(owner_client):
    assert (await owner_client.post("/api/kit/skills", json={"name": "SQL"})).status_code == 201
    assert (await owner_client.post("/api/kit/skills", json={"name": "SQL"})).status_code == 409
    t = {"key": "k", "name": "K"}
    assert (await owner_client.post("/api/kit/tracks", json=t)).status_code == 201
    assert (await owner_client.post("/api/kit/tracks", json=t)).status_code == 409


async def test_guardrail_crud_all_types(owner_client):
    params = [
        {"type": "never_mention", "terms": ["x"]},
        {"type": "never_together", "group_a": ["a"], "group_b": ["b"]},
        {"type": "require_wording", "use": "A", "instead_of": ["B"]},
        {"type": "reframe", "prefer": "a", "over": "b"},
        {"type": "omit_field", "fields": ["dob"]},
        {"type": "format", "rule": "money_usd_first"},
        {"type": "positioning", "instruction": "lead with scope"},
        {"type": "limit", "document": "cv", "pages": 2},
        {"type": "attach_policy", "document_type": "id", "when": "never"},
    ]
    for p in params:
        r = await owner_client.post("/api/kit/guardrails", json={
            "name": p["type"], "params": p, "scope": ["cv", "letter"], "strictness": "block_waivable_once"})
        assert r.status_code == 201, r.text
        assert r.json()["type"] == p["type"] and r.json()["strictness"] == "block_waivable_once"
    assert (await owner_client.get("/api/kit/guardrails")).json()["total"] == 9
    bad = await owner_client.post("/api/kit/guardrails", json={"name": "n", "params": {"type": "nope"}})
    assert bad.status_code == 422


async def test_guardrail_check_endpoint_split_pair_and_never_skill(owner_client):
    await owner_client.post("/api/kit/skills", json={"name": "Tableau", "claim": "never"})
    await owner_client.post("/api/kit/guardrails", json={
        "name": "pair", "scope": ["everywhere"],
        "params": {"type": "never_together", "group_a": ["12 clients"], "group_b": ["USD 3 million"]}})
    await owner_client.post("/api/kit/guardrails", json={
        "name": "advice", "strictness": "advise", "severity": "warn",
        "params": {"type": "never_mention", "terms": ["synergy"]}})
    ok = (await owner_client.post("/api/kit/guardrails/check", json={"texts": {"cv": "Managed 12 clients"}})).json()
    assert not ok["blocked"] and all(r["status"] == "pass" for r in ok["results"])
    split = (await owner_client.post("/api/kit/guardrails/check", json={
        "texts": {"cv": "Managed 12 clients", "letter": "Revenue of USD 3 million"}})).json()
    assert split["blocked"] and any(r["check"] == "pair" and r["status"] == "block" for r in split["results"])
    tab = (await owner_client.post("/api/kit/guardrails/check", json={"texts": {"cv": "Used Tableau"}})).json()
    assert tab["blocked"]
    advice = (await owner_client.post("/api/kit/guardrails/check", json={"texts": {"cv": "synergy"}})).json()
    assert not advice["blocked"] and any(r["status"] == "warn" for r in advice["results"])
    names = (await owner_client.post("/api/kit/guardrails/check", json={
        "texts": {"cv": "x"}, "file_names": ["Tableau-report.pdf"]})).json()
    assert names["blocked"]


async def test_template_crud_and_builtin_protected(owner_client, session):
    body = {"key": "classic", "kind": "cv", "name": "Classic", "html": "<p>{{ person.name }}</p>",
            "limits": {"pages": 2}, "accent": "#112233"}
    r = await owner_client.post("/api/kit/templates", json=body)
    assert r.status_code == 201 and r.json()["builtin"] is False
    assert (await owner_client.post("/api/kit/templates", json=body)).status_code == 409
    assert (await owner_client.put(f"/api/kit/templates/{r.json()['id']}", json={**body, "name": "C2"})).json()[
        "name"] == "C2"
    from app.models.kit import Template

    row = await session.get(Template, __import__("uuid").UUID(r.json()["id"]))
    row.builtin = True
    await session.commit()
    assert (await owner_client.delete(f"/api/kit/templates/{r.json()['id']}")).status_code == 403


async def test_answer_crud_and_match_with_country_condition(owner_client):
    q = "Will you require visa sponsorship?"

    def cond(**kw):
        return {"version": 1, "root": {"type": "group", "conditions": [
            {"type": "values", "facet": "location.country", **kw}]}}

    base = {"patterns": {"canonical": q, "variants": ["Do you need sponsorship?"]}, "value_type": "choice",
            "answer_class": "auto"}
    a1 = await owner_client.post("/api/kit/answers", json={**base, "value": "No", "conditions": cond(include=["ZM"])})
    a2 = await owner_client.post("/api/kit/answers", json={**base, "value": "Yes", "conditions": cond(exclude=["ZM"])})
    assert a1.status_code == a2.status_code == 201
    ask = (await owner_client.post("/api/kit/answers/match",
                                   json={"question": "do you need sponsorship", "context": {"country": "GB"}})).json()
    assert ask["outcome"] == "value" and ask["value"] == "Yes" and ask["answer_id"] == a2.json()["id"]
    zm = {"question": q, "context": {"country": "ZM"}}
    home = (await owner_client.post("/api/kit/answers/match", json=zm)).json()
    assert home["value"] == "No"
    unknown = (await owner_client.post("/api/kit/answers/match", json={"question": q})).json()
    assert unknown["outcome"] == "ask_owner"
    other = (await owner_client.post("/api/kit/answers/match", json={"question": "Favourite food?"})).json()
    assert other["outcome"] == "ask_owner" and other["answer_id"] is None


async def test_answer_never_class_over_api(owner_client):
    await owner_client.post("/api/kit/answers", json={
        "patterns": {"canonical": "What is your ethnicity?"}, "answer_class": "never",
        "forced_choice": "Prefer not to say"})
    out = (await owner_client.post("/api/kit/answers/match", json={
        "question": "What is your ethnicity?", "options": ["A", "Prefer not to say"]})).json()
    assert out["outcome"] == "do_not_answer" and out["select"] == "Prefer not to say"


# ----- vault -----------------------------------------------------------------------------


def make_pdf(*, text: bool, compress: bool = False) -> bytes:
    content = b"BT /F1 12 Tf (Hello) Tj ET" if text else b"q 100 0 0 100 0 0 cm /Im0 Do Q"
    if compress:
        content = zlib.compress(content)
        stream = b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(content)
    else:
        stream = b"<< /Length %d >>\nstream\n" % len(content)
    return b"%PDF-1.4\n1 0 obj\n" + stream + content + b"\nendstream\nendobj\ntrailer\n%%EOF\n"


async def upload(client, content, name="doc.pdf", mime="application/pdf", **form):
    data = {"title": "My doc", "doc_type": "cert", **form}
    return await client.post("/api/kit/vault", data=data, files={"file": (name, content, mime)})


async def test_vault_upload_download_and_text_layer(owner_client, files_dir, session):
    pdf = make_pdf(text=True)
    r = await upload(owner_client, pdf, sensitivity="on_request")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["sha256"] == hashlib.sha256(pdf).hexdigest() and doc["size_bytes"] == len(pdf)
    assert doc["mime_type"] == "application/pdf" and doc["has_text_layer"] is True
    assert doc["sensitivity"] == "on_request" and doc["doc_type"] == "cert"
    stored = [p for p in files_dir.rglob("*") if p.is_file()]
    assert len(stored) == 1 and stored[0].read_bytes() == pdf
    dl = await owner_client.get(f"/api/kit/vault/{doc['id']}/download")
    assert dl.status_code == 200 and dl.content == pdf

    scanned = (await upload(owner_client, make_pdf(text=False), name="scan.pdf", title="Scan")).json()
    assert scanned["has_text_layer"] is False
    flate = (await upload(owner_client, make_pdf(text=True, compress=True), name="c.pdf")).json()
    assert flate["has_text_layer"] is True
    txt = (await upload(owner_client, b"plain words", name="n.txt", mime="text/plain")).json()
    assert txt["has_text_layer"] is True and txt["mime_type"] == "text/plain"
    png = (await upload(owner_client, b"\x89PNG\r\n\x1a\nxxxx", name="p.png", mime="image/png",
                        doc_type="photo")).json()
    assert png["has_text_layer"] is False

    assert {"kit.vault_document.created", "kit.vault_document.downloaded"} <= set(await audit_actions(session))


async def test_vault_duplicate_empty_and_oversize(owner_client, monkeypatch):
    assert (await upload(owner_client, b"same")).status_code == 201
    assert (await upload(owner_client, b"same", name="other.pdf")).status_code == 409
    assert (await upload(owner_client, b"")).status_code == 422
    await owner_client.put("/api/settings/documents.vault_max_upload_mb", json={"value": 1})
    r = await upload(owner_client, b"x" * (1024 * 1024 + 1), name="big.bin")
    assert r.status_code == 413


async def test_vault_update_and_delete_removes_file(owner_client, files_dir):
    doc = (await upload(owner_client, b"hello", name="a.txt", mime="text/plain")).json()
    r = await owner_client.put(f"/api/kit/vault/{doc['id']}", json={
        "title": "Renamed", "doc_type": "degree", "sensitivity": "after_offer_only"})
    assert r.status_code == 200 and r.json()["sensitivity"] == "after_offer_only"
    assert (await owner_client.delete(f"/api/kit/vault/{doc['id']}")).status_code == 204
    assert not [p for p in files_dir.rglob("*") if p.is_file()]
    assert (await owner_client.get(f"/api/kit/vault/{doc['id']}/download")).status_code == 404


# ----- needs review ----------------------------------------------------------------------


async def test_loaded_kit_lands_needs_review_and_lists_stale_first(owner_client, session):
    report = await load_example(session)
    assert report.created["fact"] >= 1 and not report.skipped
    review = (await owner_client.get("/api/kit/review")).json()
    entities = {i["entity"] for i in review["items"]}
    assert {"person", "experience", "fact", "skill", "reference", "track", "guardrail", "answer",
            "vault_document", "template"} <= entities
    ranks = [i["stale_first_rank"] for i in review["items"]]
    assert ranks == list(range(len(ranks)))
    groups = {i["group"] for i in review["items"] if i["entity"] == "answer"}
    assert "visa" in groups
    only = (await owner_client.get("/api/kit/review", params={"entity": "skill"})).json()
    assert only["total"] and {i["entity"] for i in only["items"]} == {"skill"}
    assert all(f["review_state"] == "needs_review"
               for f in (await owner_client.get("/api/kit/facts")).json()["items"])


async def test_review_confirm_edit_drop(owner_client, session):
    await load_example(session)
    items = (await owner_client.get("/api/kit/review", params={"entity": "skill"})).json()["items"]
    keep, drop = items[0], items[1]
    # edit keeps it in the queue
    skill = (await owner_client.get(f"/api/kit/skills/{keep['id']}")).json()
    edited = {k: skill[k] for k in ("name", "group", "level", "claim", "note")}
    edited["note"] = "edited by owner"
    r = await owner_client.put(f"/api/kit/skills/{keep['id']}", json=edited)
    assert r.json()["review_state"] == "needs_review"
    # confirm
    r = await owner_client.post(f"/api/kit/review/skill/{keep['id']}", json={"decision": "confirm"})
    assert r.status_code == 200
    got = (await owner_client.get(f"/api/kit/skills/{keep['id']}")).json()
    assert got["review_state"] == "confirmed" and got["confirmed_at"] and got["note"] == "edited by owner"
    # drop
    assert (await owner_client.post(f"/api/kit/review/skill/{drop['id']}",
                                    json={"decision": "drop", "note": "not mine"})).status_code == 200
    assert (await owner_client.get(f"/api/kit/skills/{drop['id']}")).status_code == 404
    # a decided item cannot be decided twice
    again = await owner_client.post(f"/api/kit/review/skill/{keep['id']}", json={"decision": "confirm"})
    assert again.status_code == 409
    gone = await owner_client.post(f"/api/kit/review/skill/{drop['id']}", json={"decision": "drop"})
    assert gone.status_code == 404
    left = (await owner_client.get("/api/kit/review", params={"entity": "skill"})).json()["items"]
    assert keep["id"] not in {i["id"] for i in left} and drop["id"] not in {i["id"] for i in left}
    acts = set(await audit_actions(session))
    assert {"kit.skill.review_confirm", "kit.skill.review_drop", "kit.skill.updated", "kit.loaded"} <= acts


async def test_dropped_fact_is_retired_and_code_kept(owner_client, session):
    await load_example(session)
    facts = (await owner_client.get("/api/kit/review", params={"entity": "fact"})).json()["items"]
    target = facts[0]
    await owner_client.post(f"/api/kit/review/fact/{target['id']}", json={"decision": "drop"})
    fact = (await owner_client.get(f"/api/kit/facts/{target['id']}")).json()
    assert fact["status"] == "retired" and fact["review_state"] == "confirmed"
    new = (await owner_client.post("/api/kit/facts", json=fact_body("Fresh"))).json()
    existing = {f["code"] for f in (await owner_client.get("/api/kit/facts", params={"limit": 500})).json()["items"]}
    assert new["code"] in existing and sum(1 for f in existing if f == new["code"]) == 1


async def test_drop_vault_document_removes_file(owner_client, session, files_dir):
    await load_example(session)
    assert [p for p in files_dir.rglob("*") if p.is_file()]
    item = (await owner_client.get("/api/kit/review", params={"entity": "vault_document"})).json()["items"][0]
    await owner_client.post(f"/api/kit/review/vault_document/{item['id']}", json={"decision": "drop"})
    assert not [p for p in files_dir.rglob("*") if p.is_file()]


async def test_conflicting_pending_answers_are_flagged(owner_client, session):
    await load_example(session)
    q = "What is your notice period?"
    r = await owner_client.post("/api/kit/answers", json={"patterns": {"canonical": q}, "value": "Two months",
                                                           "answer_class": "auto"})
    new_id = r.json()["id"]
    items = (await owner_client.get("/api/kit/review", params={"entity": "answer"})).json()["items"]
    notice = [i for i in items if i["title"] == q]
    assert notice and new_id in notice[0]["conflicts_with"]


async def test_loader_is_repeatable_and_flags_changes(owner_client, session):
    first = await load_example(session)
    second = await load_example(session)
    assert not second.created and not second.updated
    assert sum(second.unchanged.values()) == sum(first.created.values())
    counts = {p: (await owner_client.get(f"/api/kit/{p}")).json()["total"]
              for p in ("facts", "skills", "tracks", "answers", "guardrails", "templates", "vault",
                        "experiences", "references")}
    assert all(counts.values())
    # a confirmed row whose source changed goes back to review
    fact = (await owner_client.get("/api/kit/facts")).json()["items"][0]
    await owner_client.post(f"/api/kit/review/fact/{fact['id']}", json={"decision": "confirm"})
    kit = KitFile.model_validate(json.loads((KIT / "kit.json").read_text(encoding="utf-8")))
    kit.facts[0].text = kit.facts[0].text + " (revised)"
    report = await load_kit(session, kit)
    await session.commit()
    assert report.updated["fact"] == 1
    again = (await owner_client.get(f"/api/kit/facts/{fact['id']}")).json()
    assert again["review_state"] == "needs_review" and (await owner_client.get("/api/kit/facts")).json()[
        "total"] == len(kit.facts)
