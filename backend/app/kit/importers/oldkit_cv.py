"""A CV written as plain text (a Word file, a PDF's text, a .txt) turned into the headed layout the profile
parser reads. Nothing here decides what is true: it only recognises section titles and dated job lines, so
the same ``parse_profile`` reads a hand-made profile and a CV. Everything it yields is unconfirmed."""

from __future__ import annotations

import io
import re

SECTION_TITLES = (
    (r"summary|profile|objective|about me|personal statement", "Summary"),
    (r"work experience|professional experience|experience|employment(?: history)?|career history", "Work experience"),
    (r"education|qualifications|academic background", "Education"),
    (r"(?:key |technical |core )?skills|competenc(?:e|ies)", "Skills"),
    (r"certifications?|licen[cs]es|training", "Certifications"),
    (r"projects", "Projects"),
    (r"achievements|accomplishments", "Achievements"),
    (r"referees|references", "Referees"),
    (r"languages|interests|hobbies|declaration|personal details", "Other"),
)
_TITLE = re.compile(r"^\W*(?P<t>[A-Za-z][A-Za-z &/]{2,40}?)\s*:?\W*$")
_BULLET = re.compile(r"^\s*(?:[-*+•–▪●]|\d+[.)])\s+")  # noqa: RUF001
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d ()-]{7,}\d")
_RANGE = re.compile(r"(?:\d{4}|[A-Za-z]{3,9}\.?,?\s+\d{4}|\d{1,2}[/.-]\d{4})\s*(?:-|–|—|to|until)\s*"  # noqa: RUF001
                    r"(?:\d{4}|[A-Za-z]{3,9}\.?,?\s+\d{4}|\d{1,2}[/.-]\d{4}|present|current|now|date)", re.I)
BULLET_SECTIONS = ("Education", "Certifications", "Projects", "Achievements", "Referees", "Skills")


def _section_of(line: str) -> str | None:
    m = _TITLE.match(line)
    if not m:
        return None
    word = m.group("t").strip().casefold()
    for pattern, title in SECTION_TITLES:
        if re.fullmatch(pattern, word):
            return title
    return None


def cv_to_markdown(text: str) -> str:
    """Headed layout: ``Name:``, ``Email:``, ``Phone:`` lines, ``##`` sections, ``###`` dated jobs, ``-`` bullets."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    section: str | None = None
    head_done = False
    head: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):  # a Word file already carries its headings
            stripped = stripped.lstrip("#").strip()
            title = _section_of(stripped)
            if title is None and section is None:
                head.append(stripped)
                continue
        title = _section_of(stripped) if stripped else None
        if title is not None:
            head_done = True
            section = title
            out.append(f"## {title}")
            continue
        if not head_done:
            if stripped:
                head.append(stripped)
            continue
        if not stripped:
            out.append("")
            continue
        body = _BULLET.sub("", stripped)
        if section == "Work experience" and _RANGE.search(body) and not _BULLET.match(stripped):
            out.append(f"### {body}")
        elif section in BULLET_SECTIONS or section == "Work experience" or _BULLET.match(stripped):
            out.append(f"- {body}")
        else:
            out.append(body)
    header: list[str] = []
    name = next((h for h in head if len(h.split()) <= 5 and not re.search(r"[\d@]", h)
                 and not re.search(r"curriculum|resume|cv", h, re.I)), None)
    if name:
        header.append(f"Name: {name}")
    blob = "\n".join(head)
    if email := _EMAIL.search(blob):
        header.append(f"Email: {email.group(0)}")
    if phone := _PHONE.search(blob):
        header.append(f"Phone: {phone.group(0).strip()}")
    return "\n".join([*header, "", *out]) + "\n"


def pdf_text(data: bytes, *, max_pages: int) -> str:
    """Text of a PDF's first pages. Raises ``ValueError`` when it cannot be read (scanned, damaged, locked)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("the PDF is locked")
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])
    except ValueError:
        raise
    except Exception as exc:  # a damaged PDF can raise anything; never leak parser detail
        raise ValueError("the PDF could not be read") from exc
    if not text.strip():
        raise ValueError("the PDF holds no text (a scan?)")
    return text
