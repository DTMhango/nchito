"""Plain-text export: form paste, checks, and the text the other formats must carry."""

from __future__ import annotations

from app.docs.model import DocModel


def to_text(doc: DocModel, *, upper_headings: bool = True) -> str:
    out: list[str] = []
    if doc.name:
        out.append(doc.name)
    if doc.headline:
        out.append(doc.headline)
    if doc.contact:
        out.append(" | ".join(doc.contact))
    if doc.kind == "letter":
        out.append("")
        if doc.salutation:
            out += [doc.salutation, ""]
        for p in doc.paragraphs:
            out += [p, ""]
        if doc.signoff:
            out += [doc.signoff, doc.name] if doc.name else [doc.signoff]
        return _tidy(out)
    for s in doc.sections:
        out += ["", s.title.upper() if upper_headings else s.title]
        out += s.paragraphs
        out += [f"- {b}" for b in s.bullets]
        for e in s.entries:
            out += ["", e.title]
            if e.subtitle:
                out.append(e.subtitle)
            out += [f"- {b}" for b in e.bullets]
    return _tidy(out)


def _tidy(lines: list[str]) -> str:
    return "\n".join(lines).strip("\n") + "\n"
