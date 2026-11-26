"""Read an uploaded zip without trusting it (kit files and old-kit folders).

Refuses: not a zip, encrypted members, too many members, a member or the total unpacked size over
the limit (checked on the declared size and again while reading, so a lying header cannot get
past), names that escape the folder (absolute, drive letters, ``..``, backslashes, NUL),
symbolic links, duplicate names, and names the caller does not allow. Nothing is written to disk.
"""

from __future__ import annotations

import io
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass


class UnsafeZip(ValueError):
    """The archive must not be read (the message is safe to show the owner)."""


@dataclass(frozen=True)
class ZipLimits:
    max_zip_bytes: int
    max_file_bytes: int
    max_files: int

    @property
    def max_total_bytes(self) -> int:
        return self.max_file_bytes * 4


def clean_name(raw: str) -> str:
    """The normalised member name, or ``UnsafeZip``."""
    if not raw or "\x00" in raw or "\\" in raw:
        raise UnsafeZip(f"unsafe file name {raw[:80]!r}")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise UnsafeZip(f"absolute path in zip: {raw[:80]!r}")
    parts = raw.split("/")
    if any(p in ("..", "") for p in parts[:-1]) or parts[-1] == "..":
        raise UnsafeZip(f"path traversal in zip: {raw[:80]!r}")
    return "/".join(p for p in parts if p not in (".",))


def read_zip(data: bytes, limits: ZipLimits, *, allow: Callable[[str], bool] | None = None,
             skip_unallowed: bool = False) -> tuple[dict[str, bytes], list[str]]:
    """Return ``({name: bytes}, skipped_names)``. Directories are dropped.

    ``allow(name)`` false: refuse the archive, or with ``skip_unallowed`` skip that member (still
    size-checked by header, never read).
    """
    if len(data) > limits.max_zip_bytes:
        raise UnsafeZip("the zip is larger than the upload limit")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsafeZip("not a valid zip file") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > limits.max_files:
        raise UnsafeZip(f"the zip holds more than {limits.max_files} files")
    out: dict[str, bytes] = {}
    skipped: list[str] = []
    total = 0
    for info in infos:
        name = clean_name(info.filename)
        if not name:
            continue
        if info.flag_bits & 0x1:
            raise UnsafeZip(f"{name} is encrypted")
        mode = info.external_attr >> 16
        if mode and (stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))):
            raise UnsafeZip(f"{name} is a link or special file")
        if name in out or name in skipped:
            raise UnsafeZip(f"duplicate entry {name}")
        if info.file_size > limits.max_file_bytes:
            raise UnsafeZip(f"{name} is larger than the per-file limit")
        if allow is not None and not allow(name):
            if skip_unallowed:
                skipped.append(name)
                continue
            raise UnsafeZip(f"unexpected file in zip: {name}")
        with zf.open(info) as fh:
            content = fh.read(limits.max_file_bytes + 1)
        if len(content) > limits.max_file_bytes:
            raise UnsafeZip(f"{name} is larger than the per-file limit")
        total += len(content)
        if total > limits.max_total_bytes:
            raise UnsafeZip("the zip is too large once unpacked")
        out[name] = content
    return out, skipped
