"""Export the pack (current version of each section, with the owner's notes) through the document renderers
(``app/docs``, built-in template ``pack``). A flagged section is exported with its warning, never as fine.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.docs.emit_docx import to_docx
from app.docs.emit_pdf import to_pdf
from app.docs.emit_text import to_text
from app.docs.layouts import pack_template
from app.docs.model import DocModel, Entry, Section
from app.models.applications import InterviewSectionVersion
from app.models.search import Job
from app.pipeline.interview import shapes as sh

ExportFmt = Literal["pdf", "docx", "txt"]
MIME: dict[str, str] = {
    "pdf": "application/pdf", "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
FLAG_LINE = "Flagged: this section failed the truth checks. Do not rely on it until it is fixed or regenerated."


def _cites(ids: list[str]) -> str:
    return f" [{', '.join(ids)}]" if ids else ""


def section_body(content: sh.Shape) -> Section:
    s = Section(key="", title="")
    if isinstance(content, sh.RoleBrief):
        s.paragraphs = [p for p in (content.summary, content.level_notes, content.research_note) if p]
        s.entries = [Entry(title=t, bullets=b) for t, b in (("Emphasised", content.emphasised),
                                                             ("Requirements", content.requirements),
                                                             ("Company notes", content.company_notes)) if b]
    elif isinstance(content, sh.WhyYou):
        s.bullets = [f"{p.point.text}{_cites(p.point.fact_ids)}" for p in content.points]
    elif isinstance(content, sh.Questions):
        s.entries = [Entry(title=f"{q.category.title()}: {q.question}", subtitle=q.why_asked or None,
                           bullets=[f"{q.answer.text}{_cites(q.answer.fact_ids)}"]) for q in content.items]
    elif isinstance(content, sh.Stories):
        s.entries = [Entry(title=f"{'* ' if st.favourite else ''}{st.title}{_cites(st.fact_ids)}",
                           subtitle=st.requirement or None,
                           bullets=[f"Situation: {st.situation}", f"Task: {st.task}", f"Action: {st.action}",
                                    f"Result: {st.result}"]) for st in content.items]
    elif isinstance(content, sh.QuestionsToAsk):
        s.bullets = [f"{q.question}{f' ({q.why})' if q.why else ''}" for q in content.items]
    elif isinstance(content, sh.Gaps):
        s.entries = [Entry(title=g.requirement, subtitle=g.gap,
                           bullets=[f"{g.answer.text}{_cites(g.answer.fact_ids)}"]) for g in content.items]
    elif isinstance(content, sh.PaySheet):
        if content.posting_pay:
            s.paragraphs = [f"Posting: {content.posting_pay}"]
        s.entries = [Entry(title=line.topic, subtitle=line.question, bullets=[b for b in (
            f"Your answer: {line.kit_answer}" if line.kit_answer else "",
            f"You told them: {line.told_them}" if line.told_them else "", line.note) if b])
            for line in content.lines]
    elif isinstance(content, sh.CribSheet):
        if content.role:
            s.paragraphs = [content.role]
        s.entries = [Entry(title=t, bullets=b) for t, b in (
            ("Why you", content.points), ("Stories", content.stories), ("Ask them", content.questions_to_ask),
            ("Pay and logistics", content.pay), ("Gaps", content.gaps), ("Flagged sections", content.flagged)) if b]
    return s


def build(job: Job, order: list[str], current: Mapping[str, InterviewSectionVersion],
          notes: Mapping[str, str]) -> DocModel:
    sections: list[Section] = []
    for key in [k for k in order if k in current]:
        row = current[key]
        body = section_body(sh.validate(key, row.content))
        body.key, body.title = key, sh.TITLES[key]
        if row.flagged:
            body.paragraphs = [FLAG_LINE, *body.paragraphs]
        if notes.get(key):
            body.entries.append(Entry(title="Your notes", bullets=[notes[key]]))
        sections.append(body)
    return DocModel(kind="pack", name=f"Interview pack: {job.title}", headline=job.employer, sections=sections)


def render(doc: DocModel, fmt: ExportFmt) -> bytes:
    template = pack_template()
    if fmt == "pdf":
        return to_pdf(doc, template, doc.name)[0]
    if fmt == "docx":
        return to_docx(doc, template, doc.name)
    return to_text(doc, upper_headings=False).encode("utf-8")
