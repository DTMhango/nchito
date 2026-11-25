"""Vault files on the local files volume, and PDF text-layer detection (no extra dependency)."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
import uuid
import zlib
from pathlib import Path

VAULT_DIR = "vault"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_TEXT_OPERATORS = re.compile(rb"\)\s*Tj|\]\s*TJ|>\s*Tj|>\s*TJ")
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
TEXT_MIME_PREFIXES = ("text/",)
OFFICE_TEXT_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}


def safe_name(name: str) -> str:
    base = Path(name or "file").name
    return _SAFE.sub("_", base).strip("._") or "file"


def guess_mime(name: str, content: bytes, declared: str | None) -> str:
    if content[:5] == b"%PDF-":
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(name)
    if guessed:
        return guessed
    return declared if declared and declared != "application/octet-stream" else "application/octet-stream"


def pdf_has_text_layer(content: bytes) -> bool:
    """True when the PDF draws text (a Tj or TJ operator in a page content stream).

    A scanned PDF holds only images, so it has none. Streams are inflated when compressed
    with Flate; other filters are skipped (they report False, which routes to OCR or review).
    """
    if _TEXT_OPERATORS.search(content):
        return True
    for m in _STREAM.finditer(content):
        raw = m.group(1)
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            continue
        if _TEXT_OPERATORS.search(data):
            return True
    return False


def has_text_layer(mime: str, content: bytes) -> bool:
    if mime == "application/pdf":
        return pdf_has_text_layer(content)
    return mime.startswith(TEXT_MIME_PREFIXES) or mime in OFFICE_TEXT_MIMES


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def new_key(sha: str, filename: str) -> str:
    return f"{VAULT_DIR}/{sha[:2]}/{uuid.uuid4().hex}_{safe_name(filename)}"


def resolve(files_dir: Path, key: str) -> Path:
    root = files_dir.resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("path escapes the files directory")
    return path


async def write(files_dir: Path, key: str, content: bytes) -> None:
    path = resolve(files_dir, key)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    await asyncio.to_thread(_write)


async def remove(files_dir: Path, key: str) -> None:
    path = resolve(files_dir, key)
    await asyncio.to_thread(lambda: path.unlink(missing_ok=True))
