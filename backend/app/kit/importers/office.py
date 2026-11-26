"""Plain text out of .docx and .xlsx notes, with the standard library only.

Both formats are zips of XML. The files are untrusted: XML that declares a DOCTYPE or entities is
refused (no entity expansion), and the zip is read through ``read_zip`` limits by the caller's
size caps. Output is markdown-ish text for ``.docx`` (headings and bullets kept) and CSV for the
first sheet of a ``.xlsx``.
"""

from __future__ import annotations

import csv
import io
import re
from xml.etree import ElementTree as ET

from app.kit.zipsafe import UnsafeZip, ZipLimits, read_zip

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_HEADING = re.compile(r"^heading\s*([1-6])$", re.I)


class OfficeError(ValueError):
    pass


def _xml(data: bytes) -> ET.Element:
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise OfficeError("XML with a DOCTYPE or entities is refused")
    try:
        return ET.fromstring(data)  # noqa: S314
    except ET.ParseError as exc:
        raise OfficeError("unreadable XML") from exc


def _members(data: bytes, limits: ZipLimits, wanted: set[str]) -> dict[str, bytes]:
    try:
        files, _ = read_zip(data, limits, allow=lambda n: n in wanted or n.startswith("xl/worksheets/sheet"),
                            skip_unallowed=True)
    except UnsafeZip as exc:
        raise OfficeError(str(exc)) from exc
    return files


def docx_text(data: bytes, limits: ZipLimits) -> str:
    files = _members(data, limits, {"word/document.xml"})
    if "word/document.xml" not in files:
        raise OfficeError("not a Word document")
    root = _xml(files["word/document.xml"])
    lines: list[str] = []
    for p in root.iter(f"{W}p"):
        style = p.find(f"{W}pPr/{W}pStyle")
        style_name = style.get(f"{W}val", "") if style is not None else ""
        text = "".join(
            (" " if n.tag == f"{W}tab" else "\n" if n.tag == f"{W}br" else (n.text or ""))
            for n in p.iter() if n.tag in (f"{W}t", f"{W}tab", f"{W}br")).strip()
        if not text:
            lines.append("")
            continue
        m = _HEADING.match(style_name.replace("_", " "))
        if m:
            lines.append("#" * int(m.group(1)) + " " + text)
        elif p.find(f"{W}pPr/{W}numPr") is not None or style_name.lower().startswith("list"):
            lines.append("- " + text)
        else:
            lines.append(text)
    return "\n".join(lines).strip() + "\n"


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx_csv(data: bytes, limits: ZipLimits) -> str:
    files = _members(data, limits, {"xl/sharedStrings.xml"})
    sheets = sorted(n for n in files if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    if not sheets:
        raise OfficeError("not an Excel workbook")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in files:
        for si in _xml(files["xl/sharedStrings.xml"]).iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in _xml(files[sheets[0]]).iter(f"{S}row"):
        cells: dict[int, str] = {}
        for c in row.findall(f"{S}c"):
            ref = c.get("r") or ""
            if not re.match(r"[A-Z]+\d+$", ref):
                continue
            kind = c.get("t")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{S}t"))
            else:
                v = c.find(f"{S}v")
                raw = v.text if v is not None and v.text is not None else ""
                value = shared[int(raw)] if kind == "s" and raw.isdigit() and int(raw) < len(shared) else raw
            cells[_col(ref)] = value
        if cells:
            writer.writerow([cells.get(i, "") for i in range(max(cells) + 1)])
    return out.getvalue()


def is_office(name: str) -> bool:
    return name.lower().endswith((".docx", ".xlsx"))


def to_text(name: str, data: bytes, limits: ZipLimits) -> str:
    lower = name.lower()
    if lower.endswith(".docx"):
        return docx_text(data, limits)
    if lower.endswith(".xlsx"):
        return xlsx_csv(data, limits)
    raise OfficeError("unsupported file type")


__all__ = ["OfficeError", "docx_text", "is_office", "to_text", "xlsx_csv"]
