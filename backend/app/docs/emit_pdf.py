"""PDF emitter (ReportLab). Real text in an embedded or standard font, one column, no images.

Output is byte-stable for the same input: ReportLab's ``invariant`` mode drops the creation
date and the random document id.
"""

from __future__ import annotations

import io
from functools import cache
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from app.docs.layouts import TemplateDef
from app.docs.model import DocModel

_STANDARD = {"sans": ("Helvetica", "Helvetica-Bold"), "serif": ("Times-Roman", "Times-Bold")}
_FALLBACK = ("NchitoVera", "NchitoVera-Bold")


@cache
def _register_fallback() -> tuple[str, str]:
    fonts = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont(_FALLBACK[0], str(fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(_FALLBACK[1], str(fonts / "VeraBd.ttf")))
    return _FALLBACK


def _all_text(doc: DocModel) -> str:
    parts = [doc.name, doc.headline or "", *doc.contact, doc.salutation or "", *doc.paragraphs, doc.signoff or ""]
    for s in doc.sections:
        parts += [s.title, *s.paragraphs, *s.bullets]
        for e in s.entries:
            parts += [e.title, e.subtitle or "", *e.bullets]
    return "".join(parts)


def needs_fallback_font(doc: DocModel) -> bool:
    """True when the text has characters the standard PDF fonts (Windows Latin-1) cannot show."""
    try:
        _all_text(doc).encode("cp1252")
    except UnicodeEncodeError:
        return True
    return False


def to_pdf(doc: DocModel, template: TemplateDef, title: str) -> tuple[bytes, int]:
    """Render and return (bytes, page count)."""
    lay = template.layout
    regular, bold = _register_fallback() if needs_fallback_font(doc) else _STANDARD[lay.font]
    lead = lay.base_pt * lay.line_height
    ink = colors.HexColor("#111111")
    accent = colors.HexColor(lay.accent)
    align = TA_CENTER if lay.centered_header else TA_LEFT
    body = ParagraphStyle("body", fontName=regular, fontSize=lay.base_pt, leading=lead, textColor=ink,
                          spaceAfter=lay.paragraph_gap_pt)
    name = ParagraphStyle("name", parent=body, fontName=bold, fontSize=lay.name_pt, leading=lay.name_pt * 1.15,
                          alignment=align, spaceAfter=2)
    meta = ParagraphStyle("meta", parent=body, alignment=align, spaceAfter=2)
    heading = ParagraphStyle("heading", parent=body, fontName=bold, fontSize=lay.heading_pt,
                             leading=lay.heading_pt * 1.2, textColor=accent, spaceBefore=lay.section_gap_pt,
                             spaceAfter=2 if lay.heading_rule else lay.paragraph_gap_pt, keepWithNext=1)
    entry = ParagraphStyle("entry", parent=body, fontName=bold, spaceAfter=0, keepWithNext=1)
    sub = ParagraphStyle("sub", parent=body, spaceAfter=1, keepWithNext=1)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2, spaceAfter=1.5)

    def para(text: str, style: ParagraphStyle, bullet_text: str | None = None) -> Paragraph:
        return Paragraph(escape(text), style, bulletText=bullet_text)

    flow: list = []
    if doc.name:
        flow.append(para(doc.name, name))
    if doc.headline:
        flow.append(para(doc.headline, meta))
    if doc.contact:
        flow.append(para(" | ".join(doc.contact), meta))
    if doc.kind == "letter":
        flow.append(Spacer(1, lay.section_gap_pt * 2))
        if doc.salutation:
            flow.append(para(doc.salutation, body))
        flow += [para(p, body) for p in doc.paragraphs]
        if doc.signoff:
            flow += [Spacer(1, lay.paragraph_gap_pt), para(doc.signoff, body)]
            if doc.name:
                flow.append(para(doc.name, body))
    for s in doc.sections:
        head: list = [para(s.title.upper() if lay.upper_headings else s.title, heading)]
        if lay.heading_rule:
            head.append(HRFlowable(width="100%", thickness=0.6, color=accent, spaceAfter=3))
        flow.append(KeepTogether(head))
        flow += [para(p, body) for p in s.paragraphs]
        flow += [para(b, bullet, lay.bullet) for b in s.bullets]
        for e in s.entries:
            flow.append(Spacer(1, 2))
            flow.append(para(e.title, entry))
            if e.subtitle:
                flow.append(para(e.subtitle, sub))
            flow += [para(b, bullet, lay.bullet) for b in e.bullets]
    buf = io.BytesIO()
    margin = lay.margin_mm * mm
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin,
                            bottomMargin=margin, title=title, author=doc.name, invariant=1)
    pdf.build(flow)
    return buf.getvalue(), pdf.page
