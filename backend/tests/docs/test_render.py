"""Renderers: text round-trips through the real files, output is byte-stable, limits are reported."""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from docx import Document
from pypdf import PdfReader

from app.docs.emit_docx import to_docx
from app.docs.emit_html import to_html
from app.docs.emit_pdf import to_pdf
from app.docs.emit_text import to_text
from app.docs.layouts import builtin_keys, resolve_template
from app.docs.model import ExperienceView, PersonView, build_cv, build_letter, person_view
from app.schemas.json_types import (
    ApplicationSpec,
    PersonField,
    SpecExperience,
    SpecItem,
    TemplateLimits,
    TitleSpan,
)

pytestmark = pytest.mark.nodb

PERSON = PersonView(name="Mutale Example", contact=["mutale.example@example.com", "+260 970 000 000"])
EXPERIENCES = {
    "e1": ExperienceView(id="e1", org="Kafue Analytics Ltd (fictional)", location="Lusaka, Zambia", start="2021-02",
                         titles=[TitleSpan(title="Senior Data Analyst")]),
    "e2": ExperienceView(id="e2", org="Zambezi Mutual Assurance (fictional)", start="2015-01", end="2018-05",
                         titles=[TitleSpan(title="Actuarial Assistant")]),
}
SPEC = ApplicationSpec(
    headline=SpecItem(text="Senior Data Analyst"),
    summary=SpecItem(text="Data analyst with eight years in insurance."),
    competencies=[SpecItem(text="Forecasting")],
    experience=[SpecExperience(experience_id="e1",
                               bullets=[SpecItem(text="Cut reporting time from 5 days to 1 day.")]),
                SpecExperience(experience_id="e2", bullets=[SpecItem(text="Built reserving workbooks.")])],
    skills=["Python", "SQL"],
    letter=[SpecItem(text="I am applying for the role."), SpecItem(text="I cut reporting time from 5 days to 1.")],
)
EDU = ["BSc Mathematics and Statistics, Example University (fictional), 2014."]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cv(key: str, spec: ApplicationSpec = SPEC, **limits):
    t = resolve_template(key, "cv")
    t = t.model_copy(update={"limits": TemplateLimits(**limits)})
    model, warnings = build_cv(spec, PERSON, EXPERIENCES, EDU, t)
    return t, model, warnings


def _pdf_text(data: bytes) -> str:
    return _norm(" ".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages))


def _docx_text(data: bytes) -> str:
    return _norm(" ".join(p.text for p in Document(io.BytesIO(data)).paragraphs))


def _expected(model) -> list[str]:
    out = [model.name, *model.contact]
    for s in model.sections:
        out += s.paragraphs + s.bullets
        for e in s.entries:
            out += [e.title, *e.bullets]
    return out


def test_three_cv_templates_and_a_letter_template_ship():
    assert builtin_keys("cv") == ["classic", "compact", "modern"]
    assert builtin_keys("letter") == ["letter-plain"]


@pytest.mark.parametrize("key", ["classic", "compact", "modern"])
def test_cv_text_round_trips_through_pdf_docx_and_text(key):
    t, model, warnings = _cv(key)
    assert warnings == []
    expected = [_norm(x) for x in _expected(model)]
    assert any("Cut reporting time from 5 days to 1 day." in x for x in expected)
    pdf, pages = to_pdf(model, t, "CV")
    assert pages == 1
    pdf_text, docx_text, txt = _pdf_text(pdf), _docx_text(to_docx(model, t, "CV")), _norm(to_text(model))
    for piece in expected:
        assert piece in pdf_text, f"pdf lacks {piece!r}"
        assert piece in docx_text, f"docx lacks {piece!r}"
        assert piece in txt, f"txt lacks {piece!r}"
    assert "Feb 2021 to Present" in pdf_text and "Jan 2015 to May 2018" in docx_text


def test_section_order_comes_from_the_template():
    t = resolve_template("classic", "cv")
    t = t.model_copy(update={"section_order": ["skills", "experience", "summary"]})
    model, warnings = build_cv(SPEC, PERSON, EXPERIENCES, EDU, t)
    assert [s.key for s in model.sections] == ["skills", "experience", "summary"]
    assert {w.code for w in warnings} == {"section_omitted"}
    assert {w.detail["section"] for w in warnings} == {"competencies", "education"}


def test_docx_has_real_structure_and_no_images():
    t, model, _ = _cv("modern")
    data = to_docx(model, t, "CV")
    doc = Document(io.BytesIO(data))
    styles = {p.style.name for p in doc.paragraphs}
    assert {"Title", "Heading 1", "Heading 2", "List Bullet"} <= styles
    assert not doc.tables and not doc.inline_shapes
    assert not [n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("word/media")]


def test_pdf_has_text_and_no_images():
    t, model, _ = _cv("classic")
    reader = PdfReader(io.BytesIO(to_pdf(model, t, "CV")[0]))
    assert all(not page.images for page in reader.pages)
    assert reader.metadata.title == "CV"


@pytest.mark.parametrize("key", ["classic", "compact", "modern"])
def test_output_is_byte_stable(key):
    t, model, _ = _cv(key)
    assert to_pdf(model, t, "CV") == to_pdf(model, t, "CV")
    assert to_docx(model, t, "CV") == to_docx(model, t, "CV")
    assert to_html(model, t, "CV") == to_html(model, t, "CV")


def test_page_count_is_measured_from_the_layout():
    long = SPEC.model_copy(update={"experience": [
        SpecExperience(experience_id="e1", bullets=[SpecItem(text=f"Delivered result number {i} " * 6)
                                                    for i in range(40)])]})
    t, model, _ = _cv("classic", long, pages=1)
    assert to_pdf(model, t, "CV")[1] > t.limits.pages


def test_bullets_per_role_cap_warns_and_keeps_every_bullet():
    spec = SPEC.model_copy(update={"experience": [
        SpecExperience(experience_id="e1", bullets=[SpecItem(text=f"Bullet {i}") for i in range(4)])]})
    _, model, warnings = _cv("classic", spec, bullets_per_role=3)
    assert [w.code for w in warnings] == ["bullets_per_role"]
    assert warnings[0].detail == {"count": 4, "limit": 3}
    experience = next(s for s in model.sections if s.key == "experience")
    assert len(experience.entries[0].bullets) == 4


def test_unknown_experience_is_reported_not_hidden():
    spec = SPEC.model_copy(update={"experience": [
        SpecExperience(experience_id="gone", title="Analyst", bullets=[SpecItem(text="Did work.")])]})
    _, model, warnings = _cv("classic", spec)
    assert [w.code for w in warnings] == ["unknown_experience"]
    experience = next(s for s in model.sections if s.key == "experience")
    assert experience.entries[0].title == "Analyst"


def test_only_show_on_cv_person_fields_reach_a_document():
    view = person_view(PersonField(value="Secret Name", visibility="forms_only"),
                       [PersonField(value="x@example.com", visibility="hidden"),
                        PersonField(value="+260 000", visibility="show_on_cv"), None])
    assert view.name is None and view.contact == ["+260 000"]


def test_letter_round_trip_and_paragraph_limit():
    t = resolve_template("letter-plain", "letter").model_copy(update={"limits": TemplateLimits(paragraphs=2)})
    model, warnings = build_letter(SPEC, PERSON, "Dear Hiring Manager,", "Kind regards,", t)
    assert warnings == []
    long = SPEC.model_copy(update={"letter": [*SPEC.letter, SpecItem(text="Third paragraph.")]})
    _, warnings = build_letter(long, PERSON, "Dear Hiring Manager,", "Kind regards,", t)
    assert [w.code for w in warnings] == ["paragraph_limit"]
    pdf_text, docx_text = _pdf_text(to_pdf(model, t, "Letter")[0]), _docx_text(to_docx(model, t, "Letter"))
    for piece in ("Dear Hiring Manager,", "I am applying for the role.", "Kind regards,", "Mutale Example"):
        assert piece in pdf_text and piece in docx_text
    assert to_text(model).splitlines()[-2:] == ["Kind regards,", "Mutale Example"]


def test_html_escapes_text_and_sandboxes_templates():
    spec = SPEC.model_copy(update={"summary": SpecItem(text="<script>alert(1)</script> & more")})
    t, model, _ = _cv("classic", spec)
    html = to_html(model, t, "CV <x>")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;x&gt;" in html
    evil = t.model_copy(update={"html": "{{ doc.__class__.__mro__ }}"})
    with pytest.raises(Exception, match=r"unsafe|undefined|access"):
        to_html(model, evil, "x")


def test_characters_outside_latin1_use_an_embedded_font_and_still_extract():
    spec = SPEC.model_copy(update={"summary": SpecItem(text="Analyst based in Lusaka, Łódź office.")})
    t, model, _ = _cv("modern", spec)
    assert "Analyst based in Lusaka" in _pdf_text(to_pdf(model, t, "CV")[0])
