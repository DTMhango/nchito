"""Scan a share-setup kit for personal details before it leaves the machine (DESIGN.md 18.5).

Two checks: patterns (emails, phone numbers, ID-number shapes, profile links) and the owner's own
known values (name, email, phone, places, referee names, ID fields), matched case-insensitively
anywhere in any text. A hit never blocks by itself: the owner sees the list in the preview and
either removes it or acknowledges it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d ()-]{7,}\d(?![\w])")
ID_NUMBER = re.compile(r"\b\d{6}/\d{2}/\d\b")
PROFILE_URL = re.compile(r"https?://(?:[\w-]+\.)?(?:linkedin\.com/in|github\.com|x\.com|twitter\.com|facebook\.com)/[\w./%-]+",
                         re.I)
MIN_KNOWN_LEN = 4


@dataclass(frozen=True)
class Hit:
    path: str
    kind: str
    excerpt: str


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _excerpt(text: str, start: int, end: int) -> str:
    lo, hi = max(0, start - 20), min(len(text), end + 20)
    return ("..." if lo else "") + text[lo:hi].replace("\n", " ") + ("..." if hi < len(text) else "")


def scan(data: Any, known_values: Iterable[tuple[str, str]] = ()) -> list[Hit]:
    """``known_values`` is ``(kind, value)`` pairs taken from the owner's Kit."""
    known = [(k, v.strip()) for k, v in known_values if v and len(v.strip()) >= MIN_KNOWN_LEN]
    hits: list[Hit] = []
    for path, text in _walk(data):
        if path in ("kind", "app_version", "exported_at"):
            continue
        for kind, rx in (("email", EMAIL), ("phone", PHONE), ("id_number", ID_NUMBER), ("url", PROFILE_URL)):
            for m in rx.finditer(text):
                hits.append(Hit(path, kind, _excerpt(text, m.start(), m.end())))
        low = text.casefold()
        for kind, value in known:
            at = low.find(value.casefold())
            if at >= 0:
                hits.append(Hit(path, kind, _excerpt(text, at, at + len(value))))
    seen: set[tuple[str, str, str]] = set()
    unique: list[Hit] = []
    for h in hits:
        key = (h.path, h.kind, h.excerpt)
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique
