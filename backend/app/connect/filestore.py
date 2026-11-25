"""File store interface: the local files volume, Google Drive, OneDrive, S3-compatible. DESIGN.md 12, 14.

Invariants:
- **Content-addressed integrity.** ``put`` returns the sha256 of what was stored; packets bind
  to these hashes, so a file that changes is a packet change.
- **App-folder scope only** for cloud stores; nothing outside the app's own folder is read.
- **Share links are explicit.** ``share_link`` creates a link only when a posting asks for
  links, and the permission granted is recorded in the packet (``link_permissions``).
- **Deleting temporary files never deletes duplicate-protection history or submitted snapshots.**
- Keys are relative POSIX paths with no ``..`` segments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class StoredFile:
    key: str
    sha256: str
    size_bytes: int
    mime_type: str


@runtime_checkable
class FileStore(Protocol):
    kind: Literal["local", "gdrive", "onedrive", "s3"]

    async def put(self, key: str, content: bytes, mime_type: str) -> StoredFile:
        ...

    async def get(self, key: str) -> bytes:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def exists(self, key: str) -> bool:
        ...

    async def share_link(self, key: str, *, audience: Literal["anyone_with_link"]) -> str:
        ...
