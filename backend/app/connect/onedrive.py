"""OneDrive ``FileStore`` over Microsoft Graph. DESIGN.md 12, 14, 18.5.

- **Narrowest scope.** ``Files.ReadWrite.AppFolder``: every path below is under the app's own folder
  (``/me/drive/special/approot``, ``Apps/<app name>`` in the owner's OneDrive). Nothing else in the
  OneDrive is listed or read. Microsoft offers the app folder on personal OneDrive accounts only.
- **Tokens** are Fernet-encrypted in the ``Connection`` row and never logged or returned; a refreshed
  access token is persisted through ``on_tokens_changed``.
- **Integrity.** ``put`` returns the sha256 of what was sent and checks the size and Microsoft's hash
  (sha256 or sha1, whichever it reports) of the stored file, so a corrupt upload is an error.
- **Large files** (over about 4 MB) go through an upload session in chunks.
- **Share links are explicit.** ``share_link`` is the only call that changes who can see a file; each
  grant is reported to ``recorder`` (the caller writes it to the packet and the audit).
- Network goes through an injected ``HttpTransport``. A 429 waits ``Retry-After`` and repeats the call.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.connect import msgraph_auth
from app.connect.filestore import StoredFile
from app.connect.gdrive import ShareRecord
from app.connect.http_transport import HttpResponse, HttpTransport
from app.connect.local_store import check_key

APPROOT = f"{msgraph_auth.GRAPH}/me/drive/special/approot"
SIMPLE_UPLOAD_LIMIT = 4_000_000  # Graph's single-request upload ceiling is 4 MB
CHUNK_BYTES = 320 * 1024 * 10  # upload session chunks must be multiples of 320 KiB
MAX_THROTTLE_RETRIES = 3
MAX_RETRY_WAIT_SECONDS = 30.0
DEFAULT_RETRY_WAIT_SECONDS = 2.0
REFRESH_MARGIN_SECONDS = 60

READS_DESCRIPTION = ("Only files and folders Nchito creates itself, inside its own app folder. "
                     "Nothing else in your OneDrive is listed or read.")

Sleep = Callable[[float], Awaitable[None]]


class OneDriveError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class OneDriveTokens:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds

    def to_json(self) -> dict[str, Any]:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token,
                "expires_at": self.expires_at}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> OneDriveTokens:
        return cls(access_token=str(raw["access_token"]), refresh_token=str(raw["refresh_token"]),
                   expires_at=float(raw.get("expires_at", 0)))


def authorize_url(*, tenant: str, client_id: str, redirect_uri: str, state: str) -> str:
    return msgraph_auth.authorize_url(tenant=tenant, client_id=client_id, redirect_uri=redirect_uri, state=state,
                                      scopes=msgraph_auth.ONEDRIVE_SCOPES)


async def exchange_code(transport: HttpTransport, *, tenant: str, client_id: str, client_secret: str,
                        redirect_uri: str, code: str, now: Callable[[], float] = time.time) -> OneDriveTokens:
    try:
        resp = await transport.request("POST", msgraph_auth.token_url(tenant), data=msgraph_auth.code_form(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, code=code,
            scopes=msgraph_auth.ONEDRIVE_SCOPES))
    except httpx.HTTPError as exc:
        raise OneDriveError("Microsoft did not answer; try again") from exc
    body = _json(resp)
    if not resp.ok or not body.get("access_token"):
        raise OneDriveError("Microsoft refused the authorisation code", resp.status)
    if not body.get("refresh_token"):
        raise OneDriveError("Microsoft returned no refresh token; connect again and accept the consent screen")
    granted = [s.rsplit("/", 1)[-1].lower() for s in str(body.get("scope", "")).split()]
    if msgraph_auth.FILES_APP_FOLDER.lower() not in granted:
        raise OneDriveError("the OneDrive app folder permission was not granted")
    return OneDriveTokens(access_token=str(body["access_token"]), refresh_token=str(body["refresh_token"]),
                          expires_at=now() + float(body.get("expires_in", 3600)))


def _json(resp: HttpResponse) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _item(key: str) -> str:
    """The Graph address of the file ``key`` inside the app folder (path segments percent-encoded)."""
    return f"{APPROOT}:/{'/'.join(quote(part, safe='') for part in check_key(key).split('/'))}:"


class OneDriveStore:
    kind: Literal["local", "gdrive", "onedrive", "s3"] = "onedrive"

    def __init__(self, transport: HttpTransport, tokens: OneDriveTokens, *, client_id: str, client_secret: str,
                 tenant: str = "common",
                 on_tokens_changed: Callable[[OneDriveTokens], Awaitable[None]] | None = None,
                 recorder: Callable[[ShareRecord], Awaitable[None]] | None = None,
                 now: Callable[[], float] = time.time, sleep: Sleep = asyncio.sleep) -> None:
        self._http = transport
        self._tokens = tokens
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant = tenant
        self._on_tokens = on_tokens_changed
        self._recorder = recorder
        self._now = now
        self._sleep = sleep

    # ----- auth and requests --------------------------------------------------------------

    async def _refresh(self) -> None:
        try:
            form = msgraph_auth.refresh_form(client_id=self._client_id, client_secret=self._client_secret,
                                             refresh_token=self._tokens.refresh_token,
                                             scopes=msgraph_auth.ONEDRIVE_SCOPES)
            resp = await self._http.request("POST", msgraph_auth.token_url(self._tenant), data=form)
        except httpx.HTTPError as exc:
            raise OneDriveError("could not reach Microsoft to refresh the sign-in") from exc
        body = _json(resp)
        if not resp.ok or not body.get("access_token"):
            raise OneDriveError("OneDrive access was revoked or expired; reconnect OneDrive", resp.status)
        self._tokens = OneDriveTokens(
            access_token=str(body["access_token"]), refresh_token=str(body.get("refresh_token") or
                                                                      self._tokens.refresh_token),
            expires_at=self._now() + float(body.get("expires_in", 3600)))
        if self._on_tokens is not None:
            await self._on_tokens(self._tokens)

    async def _send(self, method: str, url: str, *, headers: dict[str, str], auth: bool, **kw: Any) -> HttpResponse:
        waits = 0
        refreshed = False
        while True:
            if auth and self._tokens.expires_at - self._now() < REFRESH_MARGIN_SECONDS and not refreshed:
                await self._refresh()
                refreshed = True
            sent = {**headers, "Authorization": f"Bearer {self._tokens.access_token}"} if auth else headers
            try:
                resp = await self._http.request(method, url, headers=sent, **kw)
            except httpx.HTTPError as exc:
                raise OneDriveError("could not reach OneDrive") from exc
            if resp.status == 401 and auth and not refreshed:
                await self._refresh()
                refreshed = True
                continue
            if resp.status == 429 and waits < MAX_THROTTLE_RETRIES:
                wait = _retry_after(resp)
                if wait <= MAX_RETRY_WAIT_SECONDS:
                    waits += 1
                    await self._sleep(wait)
                    continue
            return resp

    async def _call(self, method: str, url: str, *, params: dict[str, str] | None = None, json_body: Any = None,
                    content: bytes | None = None, content_type: str | None = None) -> HttpResponse:
        if not url.startswith(msgraph_auth.GRAPH + "/"):
            raise OneDriveError("refusing a request outside Microsoft Graph")
        headers = {"Content-Type": content_type} if content_type else {}
        return await self._send(method, url, headers=headers, auth=True, params=params, json=json_body,
                                content=content)

    @staticmethod
    def _need(resp: HttpResponse, what: str) -> dict[str, Any]:
        if resp.status == 429:
            raise OneDriveError(f"OneDrive is throttling requests; {what} failed, try again later", 429)
        if not resp.ok:
            raise OneDriveError(f"OneDrive {what} failed", resp.status)
        return _json(resp)

    # ----- FileStore ------------------------------------------------------------------------

    async def put(self, key: str, content: bytes, mime_type: str) -> StoredFile:
        base = _item(key)
        if len(content) <= SIMPLE_UPLOAD_LIMIT:
            resp = await self._call("PUT", f"{base}/content", params={"@microsoft.graph.conflictBehavior": "replace"},
                                    content=content, content_type=mime_type)
            stored = self._need(resp, "upload")
        else:
            stored = await self._upload_session(base, content)
        self._verify(stored, content)
        return StoredFile(key=key, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
                          mime_type=mime_type)

    async def _upload_session(self, base: str, content: bytes) -> dict[str, Any]:
        opened = self._need(await self._call("POST", f"{base}/createUploadSession", json_body={
            "item": {"@microsoft.graph.conflictBehavior": "replace"}}), "upload start")
        upload_url = str(opened.get("uploadUrl") or "")
        if not upload_url.startswith("https://"):
            raise OneDriveError("OneDrive gave no upload address")
        total = len(content)
        last: HttpResponse | None = None
        for start in range(0, total, CHUNK_BYTES):
            chunk = content[start:start + CHUNK_BYTES]
            # The upload address carries its own authorisation: the bearer token is not sent to it.
            last = await self._send("PUT", upload_url, auth=False, content=chunk, headers={
                "Content-Range": f"bytes {start}-{start + len(chunk) - 1}/{total}",
                "Content-Type": "application/octet-stream"})
            if last.status not in (200, 201, 202):
                raise OneDriveError("OneDrive upload failed", last.status)
        if last is None or last.status not in (200, 201):
            raise OneDriveError("OneDrive did not finish the upload", last.status if last else None)
        return _json(last)

    @staticmethod
    def _verify(stored: dict[str, Any], content: bytes) -> None:
        if stored.get("size") is not None and int(stored["size"]) != len(content):
            raise OneDriveError("OneDrive stored a different size than was sent")
        hashes = (stored.get("file") or {}).get("hashes") or {}
        local = {"sha256Hash": hashlib.sha256(content).hexdigest(),
                 "sha1Hash": hashlib.sha1(content, usedforsecurity=False).hexdigest()}
        for name, digest in local.items():
            remote = hashes.get(name)
            if remote and str(remote).lower() != digest:
                raise OneDriveError("OneDrive stored different bytes than were sent (checksum mismatch)")

    async def get(self, key: str) -> bytes:
        resp = await self._call("GET", f"{_item(key)}/content")
        if resp.status in (301, 302, 303, 307, 308):
            location = next((v for k, v in resp.headers.items() if k.lower() == "location"), "")
            if not location.startswith("https://"):
                raise OneDriveError("OneDrive gave no download address")
            resp = await self._send("GET", location, auth=False, headers={})  # pre-authorised link
        if resp.status == 404:
            raise KeyError(key)
        if not resp.ok:
            raise OneDriveError("OneDrive download failed", resp.status)
        return resp.body

    async def delete(self, key: str) -> None:
        resp = await self._call("DELETE", _item(key))
        if resp.status not in (200, 204, 404):
            raise OneDriveError("OneDrive delete failed", resp.status)

    async def exists(self, key: str) -> bool:
        resp = await self._call("GET", _item(key), params={"$select": "id,file"})
        if resp.status == 404:
            return False
        return "file" in self._need(resp, "lookup")

    async def share_link(self, key: str, *, audience: Literal["anyone_with_link"]) -> str:
        if audience != "anyone_with_link":
            raise OneDriveError(f"unsupported audience: {audience!r}")
        resp = await self._call("GET", _item(key), params={"$select": "id,file"})
        if resp.status == 404:
            raise KeyError(key)
        file_id = str(self._need(resp, "lookup").get("id") or "")
        if not file_id:
            raise KeyError(key)
        made = await self._call("POST", f"{msgraph_auth.GRAPH}/me/drive/items/{quote(file_id, safe='')}/createLink",
                                json_body={"type": "view", "scope": "anonymous"})
        if made.status in (400, 403):
            raise OneDriveError("this OneDrive does not allow links anyone can open", made.status)
        link = self._need(made, "share").get("link") or {}
        url = str(link.get("webUrl") or "")
        if not url.startswith("https://"):
            raise OneDriveError("OneDrive returned no share link")
        if self._recorder is not None:
            await self._recorder(ShareRecord(key=key, file_id=file_id, audience=audience, role="reader", url=url))
        return url

    async def check(self) -> str:
        """Cheap connection test: the app folder exists (Microsoft creates it on first use). Returns its name."""
        resp = await self._call("GET", APPROOT, params={"$select": "id,name"})
        if resp.status in (400, 403, 404):
            raise OneDriveError("this OneDrive has no app folder (work and school accounts do not offer one)",
                                resp.status)
        return str(self._need(resp, "check").get("name") or "the app folder")


def _retry_after(resp: HttpResponse) -> float:
    raw = next((v for k, v in resp.headers.items() if k.lower() == "retry-after"), None)
    try:
        return max(float(str(raw)), 0.0)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_WAIT_SECONDS
