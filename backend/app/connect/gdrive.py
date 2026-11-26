"""Google Drive ``FileStore`` and its OAuth helpers. DESIGN.md 12, 14, 18.5.

- **Narrowest scope.** ``drive.file``: the app sees only files and folders it created itself, in
  one root folder. It never lists or reads anything else in the owner's Drive.
- **Tokens** are Fernet-encrypted inside the ``Connection`` row (``app.connect.stores``) and are
  never logged or returned. A refreshed access token is persisted through ``on_tokens_changed``.
- **Integrity.** ``put`` returns the sha256 of what was sent and checks Drive's md5 for the stored
  file against the local md5, so a corrupted upload is an error, not a silent success.
- **Share links are explicit.** ``share_link`` is the only call that changes permissions; each
  grant is reported to ``recorder`` (the caller writes it to the packet and the audit).
- Network goes through an injected ``HttpTransport``.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

from app.connect.filestore import StoredFile
from app.connect.http_transport import HttpResponse, HttpTransport
from app.connect.local_store import check_key
from app.schemas.json_types import BackupTargetName

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
REFRESH_MARGIN_SECONDS = 60

READS_DESCRIPTION = ("Only files and folders Nchito creates itself, inside one folder. "
                     "Nothing else in your Drive is listed or read.")


class DriveError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class DriveTokens:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds

    def to_json(self) -> dict[str, Any]:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token,
                "expires_at": self.expires_at}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> DriveTokens:
        return cls(access_token=str(raw["access_token"]), refresh_token=str(raw["refresh_token"]),
                   expires_at=float(raw.get("expires_at", 0)))


@dataclass(frozen=True)
class ShareRecord:
    """A permission granted by ``share_link``, recorded by the caller (packet ``link_permissions``, audit)."""

    key: str
    file_id: str
    audience: str
    role: str
    url: str


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                       "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
                       "include_granted_scopes": "false"})
    return f"{AUTH_URL}?{query}"


async def exchange_code(transport: HttpTransport, *, client_id: str, client_secret: str, redirect_uri: str,
                        code: str, now: Callable[[], float] = time.time) -> DriveTokens:
    resp = await transport.request("POST", TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"})
    if not resp.ok:
        raise DriveError("Google refused the authorisation code", resp.status)
    body = resp.json() or {}
    if not body.get("refresh_token"):
        raise DriveError("Google returned no refresh token; connect again and accept the consent screen")
    granted = str(body.get("scope", ""))
    if SCOPE not in granted.split():
        raise DriveError("the Drive permission was not granted")
    return DriveTokens(access_token=body["access_token"], refresh_token=body["refresh_token"],
                       expires_at=now() + float(body.get("expires_in", 3600)))


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveStore:
    kind: BackupTargetName = "gdrive"

    def __init__(
        self,
        transport: HttpTransport,
        tokens: DriveTokens,
        *,
        client_id: str,
        client_secret: str,
        root_folder_name: str,
        root_folder_id: str | None = None,
        on_tokens_changed: Callable[[DriveTokens], Awaitable[None]] | None = None,
        on_root_created: Callable[[str], Awaitable[None]] | None = None,
        recorder: Callable[[ShareRecord], Awaitable[None]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._http = transport
        self._tokens = tokens
        self._client_id = client_id
        self._client_secret = client_secret
        self._root_name = root_folder_name
        self._root_id = root_folder_id
        self._on_tokens = on_tokens_changed
        self._on_root = on_root_created
        self._recorder = recorder
        self._now = now
        self._folders: dict[tuple[str, str], str] = {}

    # ----- auth and requests --------------------------------------------------------------

    async def _refresh(self) -> None:
        resp = await self._http.request("POST", TOKEN_URL, data={
            "client_id": self._client_id, "client_secret": self._client_secret,
            "refresh_token": self._tokens.refresh_token, "grant_type": "refresh_token"})
        if not resp.ok:
            raise DriveError("Drive access was revoked or expired; reconnect Google Drive", resp.status)
        body = resp.json() or {}
        self._tokens = DriveTokens(access_token=body["access_token"], refresh_token=self._tokens.refresh_token,
                                   expires_at=self._now() + float(body.get("expires_in", 3600)))
        if self._on_tokens is not None:
            await self._on_tokens(self._tokens)

    async def _call(self, method: str, url: str, *, params: dict[str, str] | None = None, json_body: Any = None,
                    content: bytes | None = None, content_type: str | None = None) -> HttpResponse:
        if self._tokens.expires_at - self._now() < REFRESH_MARGIN_SECONDS:
            await self._refresh()
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._tokens.access_token}"}
            if content_type:
                headers["Content-Type"] = content_type
            resp = await self._http.request(method, url, headers=headers, params=params, json=json_body,
                                            content=content)
            if resp.status == 401 and attempt == 1:
                await self._refresh()
                continue
            return resp
        raise DriveError("unreachable")  # pragma: no cover

    @staticmethod
    def _need(resp: HttpResponse, what: str) -> Any:
        if not resp.ok:
            raise DriveError(f"Drive {what} failed", resp.status)
        return resp.json()

    # ----- folders --------------------------------------------------------------------------

    async def _find(self, parent_id: str, name: str, *, folder: bool | None = None) -> dict[str, Any] | None:
        q = f"name = '{_q(name)}' and '{parent_id}' in parents and trashed = false"
        if folder is True:
            q += f" and mimeType = '{FOLDER_MIME}'"
        elif folder is False:
            q += f" and mimeType != '{FOLDER_MIME}'"
        resp = await self._call("GET", f"{API}/files", params={
            "q": q, "fields": "files(id,name,md5Checksum,size,mimeType)", "pageSize": "2", "spaces": "drive"})
        files = (self._need(resp, "search") or {}).get("files", [])
        return files[0] if files else None

    async def _create_folder(self, parent_id: str, name: str) -> str:
        resp = await self._call("POST", f"{API}/files", params={"fields": "id"}, json_body={
            "name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]})
        return str(self._need(resp, "folder create")["id"])

    async def _root(self, create: bool) -> str | None:
        if self._root_id:
            return self._root_id
        found = await self._find("root", self._root_name, folder=True)
        if found:
            self._root_id = str(found["id"])
        elif create:
            self._root_id = await self._create_folder("root", self._root_name)
        else:
            return None
        if self._on_root is not None:
            await self._on_root(self._root_id)
        return self._root_id

    async def _parent_of(self, key: str, *, create: bool) -> tuple[str | None, str]:
        parts = check_key(key).split("/")
        parent = await self._root(create)
        for name in parts[:-1]:
            if parent is None:
                return None, parts[-1]
            cached = self._folders.get((parent, name))
            if cached is None:
                found = await self._find(parent, name, folder=True)
                if found:
                    cached = str(found["id"])
                elif create:
                    cached = await self._create_folder(parent, name)
                else:
                    return None, parts[-1]
                self._folders[(parent, name)] = cached
            parent = cached
        return parent, parts[-1]

    async def _locate(self, key: str) -> dict[str, Any] | None:
        parent, name = await self._parent_of(key, create=False)
        return await self._find(parent, name, folder=False) if parent else None

    # ----- FileStore ------------------------------------------------------------------------

    async def put(self, key: str, content: bytes, mime_type: str) -> StoredFile:
        parent, name = await self._parent_of(key, create=True)
        assert parent is not None
        existing = await self._find(parent, name, folder=False)
        fields = "id,md5Checksum,size"
        if existing:
            resp = await self._call("PATCH", f"{UPLOAD}/files/{existing['id']}",
                                    params={"uploadType": "media", "fields": fields}, content=content,
                                    content_type=mime_type)
        else:
            boundary = uuid.uuid4().hex
            meta = json.dumps({"name": name, "parents": [parent], "mimeType": mime_type}).encode()
            body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta
                    + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode() + content
                    + f"\r\n--{boundary}--".encode())
            resp = await self._call("POST", f"{UPLOAD}/files", params={"uploadType": "multipart", "fields": fields},
                                    content=body, content_type=f"multipart/related; boundary={boundary}")
        stored = self._need(resp, "upload")
        local_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
        if stored.get("md5Checksum") and stored["md5Checksum"] != local_md5:
            raise DriveError("Drive stored different bytes than were sent (checksum mismatch)")
        return StoredFile(key=key, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                          mime_type=mime_type)

    async def get(self, key: str) -> bytes:
        found = await self._locate(key)
        if found is None:
            raise KeyError(key)
        resp = await self._call("GET", f"{API}/files/{found['id']}", params={"alt": "media"})
        if resp.status == 404:
            raise KeyError(key)
        if not resp.ok:
            raise DriveError("Drive download failed", resp.status)
        return resp.body

    async def delete(self, key: str) -> None:
        found = await self._locate(key)
        if found is None:
            return
        resp = await self._call("DELETE", f"{API}/files/{found['id']}")
        if resp.status not in (204, 404):
            raise DriveError("Drive delete failed", resp.status)

    async def exists(self, key: str) -> bool:
        return await self._locate(key) is not None

    async def share_link(self, key: str, *, audience: Literal["anyone_with_link"]) -> str:
        if audience != "anyone_with_link":
            raise DriveError(f"unsupported audience: {audience!r}")
        found = await self._locate(key)
        if found is None:
            raise KeyError(key)
        file_id = str(found["id"])
        self._need(await self._call("POST", f"{API}/files/{file_id}/permissions", params={"fields": "id"},
                                    json_body={"role": "reader", "type": "anyone"}), "share")
        meta = self._need(await self._call("GET", f"{API}/files/{file_id}", params={"fields": "webViewLink"}),
                          "link lookup")
        url = str(meta.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view")
        if self._recorder is not None:
            await self._recorder(ShareRecord(key=key, file_id=file_id, audience=audience, role="reader", url=url))
        return url

    async def check(self) -> str:
        """Cheap connection test: the root folder exists (or can be made). Returns its name."""
        await self._root(create=True)
        return self._root_name
