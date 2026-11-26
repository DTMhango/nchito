"""HTML view of a document: a sandboxed Jinja2 render of the template's HTML plus generated CSS."""

from __future__ import annotations

from html import escape

from jinja2.sandbox import SandboxedEnvironment

from app.docs.layouts import TemplateDef
from app.docs.model import DocModel

_ENV = SandboxedEnvironment(autoescape=True)
_FONTS = {"sans": "Arial, Helvetica, sans-serif", "serif": "'Times New Roman', Times, serif"}


def _css(t: TemplateDef) -> str:
    lay = t.layout
    transform = "uppercase" if lay.upper_headings else "none"
    rule = f"border-bottom: 1px solid {lay.accent};" if lay.heading_rule else ""
    align = "center" if lay.centered_header else "left"
    return (
        f"body {{ font-family: {_FONTS[lay.font]}; font-size: {lay.base_pt}pt; line-height: {lay.line_height};"
        f" margin: {lay.margin_mm}mm; color: #111; }}\n"
        f"h1 {{ font-size: {lay.name_pt}pt; margin: 0; text-align: {align}; }}\n"
        f"header p {{ margin: 2pt 0; text-align: {align}; }}\n"
        f"h2 {{ font-size: {lay.heading_pt}pt; text-transform: {transform}; color: {lay.accent};"
        f" margin: {lay.section_gap_pt}pt 0 {lay.paragraph_gap_pt}pt; {rule} }}\n"
        f"h3 {{ font-size: {lay.base_pt}pt; margin: {lay.paragraph_gap_pt}pt 0 0; }}\n"
        f"p {{ margin: 0 0 {lay.paragraph_gap_pt}pt; }}\n"
        f"ul {{ margin: 0 0 {lay.paragraph_gap_pt}pt; padding-left: 16pt; }}\n"
    )


def to_html(doc: DocModel, template: TemplateDef, title: str) -> str:
    body = _ENV.from_string(template.html).render(doc=doc.model_dump())
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f"<title>{escape(title)}</title><style>\n{_css(template)}</style></head>\n<body>\n{body}</body></html>\n")
