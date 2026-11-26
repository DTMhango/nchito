"""Document endpoints and the render service: auth, content types, idempotency, hashes, warnings."""

from __future__ import annotations

import hashlib
import io

import pytest
from docx import Document
from pypdf import PdfReader
from sqlalchemy import func, select

from app.connect.filestore import FileStore
from app.connect.local_store import LocalFileStore, default_file_store
from app.core.settings import service as settings_service
from app.models.documents import ApplicationDocument
from app.models.kit import Template, TemplateKind
from app.models.platform import AuditEvent
from app.schemas.json_types import TemplateLimits
from tests.docs.helpers import example_spec, load_example, make_application


@pytest.fixture
def store(app, tmp_path):
    fs = LocalFileStore(tmp_path / "files")
    app.dependency_overrides[default_file_store] = lambda: fs
    yield fs
    app.dependency_overrides.pop(default_file_store, None)


async def _setup(session, **kw):
    exp = await load_example(session)
    return await make_application(session, example_spec(exp, **kw))


async def _count(session) -> int:
    return await session.scalar(select(func.count()).select_from(ApplicationDocument))


def test_local_store_satisfies_the_protocol_and_rejects_bad_keys(tmp_path):
    assert isinstance(LocalFileStore(tmp_path), FileStore)
    with pytest.raises(ValueError, match="invalid key"):
        LocalFileStore(tmp_path)._path("../escape")


async def test_endpoints_need_the_owner(client, store):
    zero = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/applications/{zero}/documents")).status_code == 401
    assert (await client.get(f"/api/applications/{zero}/documents/cv")).status_code == 401
    assert (await client.post(f"/api/applications/{zero}/documents/render", json={"kind": "cv"})).status_code == 401
    assert (await client.get(f"/api/applications/{zero}/document-files/{zero}")).status_code == 401


async def test_render_stores_pdf_docx_and_text_with_hashes(owner_client, session, store):
    app = await _setup(session)
    r = await owner_client.post(f"/api/applications/{app.id}/documents/render", json={"kind": "cv"})
    assert r.status_code == 200, r.text
    body = r.json()
    docs = {d["fmt"]: d for d in body["documents"]}
    assert set(docs) == {"pdf", "docx", "txt"}
    assert body["warnings"] == []
    for fmt, d in docs.items():
        row = await session.get(ApplicationDocument, d["id"])
        stored = await store.get(row.file_key)
        assert hashlib.sha256(stored).hexdigest() == d["content_hash"] and len(stored) == d["size_bytes"]
        assert d["template_key"] == "classic" and d["page_count"] == 1, fmt
    assert (await settings_service.get_value(session, "documents.cv_template")) == "classic"
    pdf = await store.get((await session.get(ApplicationDocument, docs["pdf"]["id"])).file_key)
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Mutale Example" in text and "Cut monthly reporting time from 5 days to 1 day" in text
    assert "BSc Mathematics and Statistics" in text and "Kafue Analytics Ltd (fictional)" in text
    docx = await store.get((await session.get(ApplicationDocument, docs["docx"]["id"])).file_key)
    assert "Forecasting" in " ".join(p.text for p in Document(io.BytesIO(docx)).paragraphs)


async def test_rendering_the_same_spec_and_template_is_idempotent(owner_client, session, store):
    app = await _setup(session)
    url = f"/api/applications/{app.id}/documents/render"
    first = (await owner_client.post(url, json={"kind": "cv"})).json()["documents"]
    second = (await owner_client.post(url, json={"kind": "cv"})).json()["documents"]
    assert [d["id"] for d in first] == [d["id"] for d in second]
    assert [d["content_hash"] for d in first] == [d["content_hash"] for d in second]
    assert await _count(session) == 3
    assert len((await owner_client.get(f"/api/applications/{app.id}/documents")).json()) == 3
    audits = await session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "documents.rendered"))
    assert audits == 3


async def test_a_changed_spec_makes_new_rows_and_keeps_the_old_files(owner_client, session, store):
    app = await _setup(session)
    url = f"/api/applications/{app.id}/documents/render"
    old = (await owner_client.post(url, json={"kind": "cv", "formats": ["pdf"]})).json()["documents"][0]
    app.spec = app.spec.model_copy(update={"skills": ["Python"]})
    await session.commit()
    new = (await owner_client.post(url, json={"kind": "cv", "formats": ["pdf"]})).json()["documents"][0]
    assert new["id"] != old["id"] and new["spec_hash"] != old["spec_hash"]
    assert new["content_hash"] != old["content_hash"]
    frozen = await owner_client.get(f"/api/applications/{app.id}/document-files/{old['id']}")
    assert frozen.status_code == 200 and hashlib.sha256(frozen.content).hexdigest() == old["content_hash"]
    assert frozen.headers["x-content-sha256"] == old["content_hash"]


async def test_download_content_types_and_filenames(owner_client, session, store):
    app = await _setup(session)
    base = f"/api/applications/{app.id}/documents"
    pdf = await owner_client.get(f"{base}/cv")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF") and "Mutale_Example_CV.pdf" in pdf.headers["content-disposition"]
    assert pdf.headers["x-content-sha256"] == hashlib.sha256(pdf.content).hexdigest()
    docx = await owner_client.get(f"{base}/cv", params={"fmt": "docx"})
    assert docx.headers["content-type"].endswith("wordprocessingml.document") and docx.content[:2] == b"PK"
    txt = await owner_client.get(f"{base}/cv", params={"fmt": "txt"})
    assert txt.headers["content-type"].startswith("text/plain") and txt.text.startswith("Mutale Example\n")
    html = await owner_client.get(f"{base}/letter", params={"fmt": "html"})
    assert html.headers["content-type"].startswith("text/html") and "Dear Hiring Manager," in html.text
    again = await owner_client.get(f"{base}/cv")
    assert again.content == pdf.content and again.headers["x-document-id"] == pdf.headers["x-document-id"]


async def test_plain_text_export_is_paste_ready(owner_client, session, store):
    app = await _setup(session)
    text = (await owner_client.get(f"/api/applications/{app.id}/documents/letter", params={"fmt": "txt"})).text
    lines = text.splitlines()
    assert "Dear Hiring Manager," in lines and lines[-2:] == ["Kind regards,", "Mutale Example"]
    assert "I am applying for the Senior Data Analyst role at Acme Ltd." in lines


async def test_letter_wording_comes_from_settings(owner_client, session, store):
    app = await _setup(session)
    await settings_service.set_value(session, "documents.letter_salutation", "Dear Hiring Team,", actor="owner")
    await settings_service.set_value(session, "documents.letter_signoff", "Yours sincerely,", actor="owner")
    await session.commit()
    text = (await owner_client.get(f"/api/applications/{app.id}/documents/letter", params={"fmt": "txt"})).text
    assert "Dear Hiring Team," in text and "Yours sincerely," in text and "Dear Hiring Manager," not in text


async def test_page_limit_overflow_is_a_render_warning(owner_client, session, store):
    app = await _setup(session, extra_bullets=45)
    r = await owner_client.post(f"/api/applications/{app.id}/documents/render", json={"kind": "cv"})
    warning = next(w for w in r.json()["warnings"] if w["code"] == "page_limit")
    assert warning["detail"]["limit"] == 2 and warning["detail"]["pages"] > 2 and warning["severity"] == "warn"
    assert all(d["page_count"] == warning["detail"]["pages"] for d in r.json()["documents"])
    assert any(w["code"] == "page_limit" for w in r.json()["documents"][0]["warnings"])
    # the limit is a setting: raising it clears the warning
    await settings_service.set_value(session, "documents.cv_pages", 6, actor="owner")
    await session.commit()
    again = await owner_client.post(f"/api/applications/{app.id}/documents/render", json={"kind": "cv"})
    assert not [w for w in again.json()["warnings"] if w["code"] == "page_limit"]
    dl = await owner_client.get(f"/api/applications/{app.id}/documents/cv")
    assert dl.headers["x-render-warnings"] == "0"


async def test_templates_are_chosen_by_key_and_owner_rows_override(owner_client, session, store):
    app = await _setup(session)
    url = f"/api/applications/{app.id}/documents/render"
    keys = {}
    for key in ("classic", "compact", "modern"):
        r = await owner_client.post(url, json={"kind": "cv", "formats": ["pdf"], "template_key": key})
        keys[key] = r.json()["documents"][0]
        assert keys[key]["template_key"] == key
    assert len({d["content_hash"] for d in keys.values()}) == 3
    session.add(Template(key="classic", kind=TemplateKind.cv, name="Classic", html="", section_order=["skills"],
                         limits=TemplateLimits(pages=1), builtin=True))
    session.add(Template(key="mine", kind=TemplateKind.cv, name="Mine", html="", accent="#aa0000", builtin=False))
    await session.commit()
    narrowed = (await owner_client.post(url, json={"kind": "cv", "formats": ["txt"]})).json()
    assert [w["code"] for w in narrowed["warnings"]].count("section_omitted") == 4
    text = (await owner_client.get(f"/api/applications/{app.id}/documents/cv", params={"fmt": "txt"})).text
    assert "SKILLS" in text and "EXPERIENCE" not in text
    mine = (await owner_client.post(url, json={"kind": "cv", "formats": ["pdf"], "template_key": "mine"})).json()
    assert mine["documents"][0]["template_key"] == "mine" and mine["warnings"] == []


async def test_unknown_template_and_wrong_kind_are_404(owner_client, session, store):
    app = await _setup(session)
    r = await owner_client.post(f"/api/applications/{app.id}/documents/render",
                                json={"kind": "cv", "template_key": "nope"})
    assert r.status_code == 404
    r = await owner_client.post(f"/api/applications/{app.id}/documents/render",
                                json={"kind": "letter", "template_key": "classic"})
    assert r.status_code == 404
    bad = await owner_client.get(f"/api/applications/{app.id}/documents/cv", params={"template": "x"})
    assert bad.status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await owner_client.get(f"/api/applications/{missing}/documents/cv")).status_code == 404
    assert (await owner_client.get(f"/api/applications/{app.id}/document-files/{missing}")).status_code == 404


async def test_answers_sheet_comes_from_the_current_packet(owner_client, session, store):
    from app.apply import packets
    from app.schemas.json_types import PacketEmail

    app = await _setup(session)
    r = await owner_client.get(f"/api/applications/{app.id}/documents/answers")
    assert r.status_code == 404  # no packet yet
    draft = packets.PacketDraft(channel="manual", destination_url="https://careers.example.com/apply",
                                sending_identity="me@example.com",
                                answers=[packets.DraftAnswer(question="Notice period", value="One month")],
                                email=PacketEmail(to=["hr@example.com"], subject="s", body="b"))
    await packets.build(session, app, draft, actor="owner")
    await session.commit()
    r = await owner_client.get(f"/api/applications/{app.id}/documents/answers")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "Notice period" + chr(10) + "One month" in r.text


async def test_missing_file_is_restored_from_the_same_bytes(owner_client, session, store):
    app = await _setup(session)
    url = f"/api/applications/{app.id}/documents/render"
    doc = (await owner_client.post(url, json={"kind": "cv", "formats": ["pdf"]})).json()["documents"][0]
    row = await session.get(ApplicationDocument, doc["id"])
    await store.delete(row.file_key)
    again = (await owner_client.post(url, json={"kind": "cv", "formats": ["pdf"]})).json()["documents"][0]
    assert again["id"] == doc["id"]
    assert hashlib.sha256(await store.get(row.file_key)).hexdigest() == doc["content_hash"]
