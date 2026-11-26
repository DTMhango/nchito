"""DOCX emitter (python-docx). Real styles (Title, Heading 1-2, List Bullet), one column, no images.

The package is rewritten with fixed timestamps and core properties so equal input gives equal bytes.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from app.docs.layouts import TemplateDef
from app.docs.model import DocModel

_FONT = {"sans": "Arial", "serif": "Times New Roman"}
_FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)
_ZIP_TIME = (2000, 1, 1, 0, 0, 0)


def _rgb(hex_colour: str) -> RGBColor:
    return RGBColor.from_string(hex_colour.lstrip("#").upper())


def _style(doc, name: str, font: str, size: float, bold: bool, colour: RGBColor, before: float, after: float,
           line: float) -> None:
    st = doc.styles[name]
    st.font.name = font
    st.element.rPr.rFonts.set(qn("w:eastAsia"), font)
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.italic = False
    st.font.color.rgb = colour
    st.paragraph_format.space_before = Pt(before)
    st.paragraph_format.space_after = Pt(after)
    st.paragraph_format.line_spacing = line


def _bottom_rule(paragraph, colour: str) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", colour.lstrip("#"))):
        bottom.set(qn(f"w:{key}"), value)
    border.append(bottom)
    ppr.append(border)


def to_docx(doc: DocModel, template: TemplateDef, title: str) -> bytes:
    lay = template.layout
    font, ink, accent = _FONT[lay.font], RGBColor(0x11, 0x11, 0x11), _rgb(lay.accent)
    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Mm(lay.margin_mm)
    _style(d, "Normal", font, lay.base_pt, False, ink, 0, lay.paragraph_gap_pt, lay.line_height)
    _style(d, "Title", font, lay.name_pt, True, ink, 0, 2, 1.1)
    _style(d, "Heading 1", font, lay.heading_pt, True, accent, lay.section_gap_pt, 3, 1.1)
    _style(d, "Heading 2", font, lay.base_pt, True, ink, 3, 0, lay.line_height)
    _style(d, "List Bullet", font, lay.base_pt, False, ink, 0, 1.5, lay.line_height)
    align = WD_ALIGN_PARAGRAPH.CENTER if lay.centered_header else WD_ALIGN_PARAGRAPH.LEFT

    def add(text: str, style: str = "Normal", alignment=None):
        p = d.add_paragraph(text, style=style)
        if alignment is not None:
            p.alignment = alignment
        return p

    if doc.name:
        add(doc.name, "Title", align)
    for line in (doc.headline, " | ".join(doc.contact) if doc.contact else None):
        if line:
            add(line, alignment=align).paragraph_format.space_after = Pt(2)
    if doc.kind == "letter":
        if doc.salutation:
            add(doc.salutation).paragraph_format.space_before = Pt(lay.section_gap_pt * 2)
        for text in doc.paragraphs:
            add(text)
        if doc.signoff:
            add(doc.signoff)
            if doc.name:
                add(doc.name)
    for s in doc.sections:
        h = add(s.title.upper() if lay.upper_headings else s.title, "Heading 1")
        if lay.heading_rule:
            _bottom_rule(h, lay.accent)
        for text in s.paragraphs:
            add(text)
        for text in s.bullets:
            add(text, "List Bullet")
        for e in s.entries:
            add(e.title, "Heading 2")
            if e.subtitle:
                add(e.subtitle).paragraph_format.space_after = Pt(1)
            for text in e.bullets:
                add(text, "List Bullet")
    props = d.core_properties
    props.title, props.author, props.last_modified_by = title, doc.name, ""
    props.created = props.modified = props.last_printed = _FIXED_TIME
    props.revision, props.comments, props.keywords, props.subject = 1, "", "", ""
    raw = io.BytesIO()
    d.save(raw)
    return _stable_zip(raw.getvalue())


def _stable_zip(data: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(src.namelist()):
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            dst.writestr(info, src.read(name))
    return out.getvalue()
