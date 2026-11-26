"""Local-volume ``FileStore`` (the default store; cloud stores live in ``app/connect``)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Literal

from app.connect.filestore import FileStore, StoredFile
from app.core.config import get_config


class LocalFileStore:
    kind: Literal["local"] = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or PurePosixPath(key).is_absolute() or ".." in parts or "\\" in key:
            raise ValueError(f"invalid file key: {key!r}")
        return self.root.joinpath(*parts)

    async def put(self, key: str, content: bytes, mime_type: str) -> StoredFile:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_bytes(content)
            os.replace(tmp, path)

        await asyncio.to_thread(write)
        return StoredFile(key=key, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                          mime_type=mime_type)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def share_link(self, key: str, *, audience: Literal["anyone_with_link"]) -> str:
        raise NotImplementedError("the local files volume cannot make share links")


def default_file_store() -> FileStore:
    return LocalFileStore(get_config().files_dir)
