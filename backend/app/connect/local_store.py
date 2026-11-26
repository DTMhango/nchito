"""The local file store: the default ``FileStore``, rooted at ``FILES_DIR``.

Keys are relative POSIX paths without ``..``. ``share_link`` is refused: a local file has no
public link, and a link is only ever created explicitly on a cloud store.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from pathlib import Path
from typing import Literal

from app.connect.filestore import StoredFile


class LocalStoreError(RuntimeError):
    pass


def check_key(key: str) -> str:
    """Return ``key`` if it is a safe relative POSIX path; raise otherwise."""
    if not key or key.startswith("/") or "\\" in key or "\x00" in key:
        raise LocalStoreError(f"invalid key: {key!r}")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise LocalStoreError(f"invalid key: {key!r}")
    return key


class LocalFileStore:
    kind: Literal["local", "gdrive", "onedrive", "s3"] = "local"

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        root = self._root.resolve()
        path = (root / check_key(key)).resolve()
        if root != path and root not in path.parents:
            raise LocalStoreError(f"key escapes the store: {key!r}")
        return path

    async def put(self, key: str, content: bytes, mime_type: str) -> StoredFile:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(content)
            tmp.replace(path)

        await asyncio.to_thread(write)
        return StoredFile(key=key, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                          mime_type=mime_type or mimetypes.guess_type(key)[0] or "application/octet-stream")

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise KeyError(key) from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def share_link(self, key: str, *, audience: Literal["anyone_with_link"]) -> str:
        raise LocalStoreError("the local store cannot create share links; use a cloud store")
