"""S3-compatible object storage as a ``FileStore`` (backups copy here). DESIGN.md 12, 14.

Works with any S3-compatible service (AWS S3, Backblaze B2, Cloudflare R2, MinIO, Wasabi): an endpoint, a
bucket, and a key id and secret held as an encrypted Connection. ``boto3`` does the signing; tests inject a
fake client through :func:`set_client_factory`, so nothing touches the network. Keys the store writes live
under the connection's optional ``prefix``. It never lists or reads outside that prefix, and share links
are refused (a backup is never shared).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any, Literal

from app.connect.filestore import StoredFile
from app.schemas.json_types import BackupTargetName


class S3Error(RuntimeError):
    """The storage service refused or could not be reached (the message is safe to show)."""


ClientFactory = Callable[[str, str, str, str], Any]  # endpoint, region, key id, secret -> client


def _boto_client(endpoint: str, region: str, key_id: str, secret: str) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=endpoint, region_name=region or None, aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"},
                      connect_timeout=10, read_timeout=60))


_factory: ClientFactory | None = None


def set_client_factory(factory: ClientFactory | None) -> None:
    """Tests install a fake; ``None`` restores boto3."""
    global _factory
    _factory = factory


def make_client(endpoint: str, region: str, key_id: str, secret: str) -> Any:
    return (_factory or _boto_client)(endpoint, region, key_id, secret)


def _code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", ""))
    return ""


class S3Store:
    kind: BackupTargetName = "s3"

    def __init__(self, client: Any, bucket: str, prefix: str = "") -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        if key.startswith("/") or ".." in key.split("/"):
            raise S3Error("unsafe key")
        return f"{self._prefix}/{key}" if self._prefix else key

    async def _call(self, method: str, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(getattr(self._client, method), **kwargs)
        except Exception as exc:  # boto3 raises ClientError and friends; never leak their detail
            code = _code(exc)
            raise S3Error(f"{method} failed ({code or type(exc).__name__})") from exc

    async def check(self) -> str:
        await self._call("head_bucket", Bucket=self._bucket)
        return self._bucket

    async def put(self, key: str, content: bytes, mime_type: str) -> StoredFile:
        await self._call("put_object", Bucket=self._bucket, Key=self._key(key), Body=content, ContentType=mime_type)
        return StoredFile(key=key, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                          mime_type=mime_type)

    async def get(self, key: str) -> bytes:
        out = await self._call("get_object", Bucket=self._bucket, Key=self._key(key))
        return bytes(await asyncio.to_thread(out["Body"].read))

    async def delete(self, key: str) -> None:
        await self._call("delete_object", Bucket=self._bucket, Key=self._key(key))

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=self._key(key))
        except Exception as exc:
            if _code(exc) in ("404", "NoSuchKey", "NotFound"):
                return False
            raise S3Error(f"head_object failed ({_code(exc) or type(exc).__name__})") from exc
        return True

    async def share_link(self, key: str, *, audience: Literal["anyone_with_link"]) -> str:
        raise S3Error("share links are not offered for backup storage")
