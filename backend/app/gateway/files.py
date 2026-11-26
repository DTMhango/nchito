"""Short-lived signed file links for runners (DESIGN.md 8.3, 18.1). Invariants, never settings:

- A download link names one task and one file hash, is signed with the server secret and expires after
  ``runners.file_url_minutes``. It works only while that task is still claimed and the file is still in
  the task's approved packet; the bytes served are checked against the packet's sha256.
- An evidence upload link names one task and one content type, expires the same way and takes one file of
  at most ``runners.evidence_max_kb``. What is uploaded is untrusted data: stored, never opened or
  interpreted by the server.
- Every download and upload is audited.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeSerializer

from app.api.deps import SessionDep
from app.core import audit
from app.core.config import get_config
from app.gateway import common
from app.models.applications import AgentTask, AgentTaskStatus, Application

router = APIRouter(prefix="/api/gateway", tags=["gateway"])

EVIDENCE_PREFIX = "evidence/"


def _serializer(purpose: str) -> URLSafeSerializer:
    return URLSafeSerializer(get_config().secret_key, salt=f"nchito-gateway-{purpose}")


def sign(purpose: str, payload: dict[str, Any], *, expires: datetime) -> str:
    return _serializer(purpose).dumps({**payload, "exp": expires.timestamp()})


def unsign(purpose: str, value: str, *, at: datetime) -> dict[str, Any]:
    try:
        data = _serializer(purpose).loads(value)
    except BadSignature as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="invalid link") from exc
    if not isinstance(data, dict) or float(data.get("exp", 0)) <= at.timestamp():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="this link has expired")
    return data


def absolute(path: str) -> str:
    return get_config().base_url.rstrip("/") + path


async def lifetime(session: Any, at: datetime) -> datetime:
    return at + timedelta(minutes=int(await common.setting(session, "runners.file_url_minutes")))


def download_path(signed: str) -> str:
    return f"/api/gateway/files/{signed}"


def upload_path(signed: str) -> str:
    return f"/api/gateway/uploads/{signed}"


async def _live_task(session: Any, task_id: str) -> AgentTask:
    task = await session.get(AgentTask, uuid.UUID(task_id))
    if task is None or task.status != AgentTaskStatus.claimed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="the task this link belongs to is no longer active")
    return task


@router.get("/files/{signed}", name="gateway_file", response_class=Response,
            responses={200: {"content": {"application/octet-stream": {}}}})
async def download(signed: str, session: SessionDep) -> Response:
    """One packet file for a runner, through a short-lived signed link."""
    from app.apply.channels.email import attachment_loader
    from app.connect.local_store import default_file_store

    at = common.now()
    data = unsign("file", signed, at=at)
    task = await _live_task(session, str(data["t"]))
    app = await session.get(Application, task.application_id) if task.application_id else None
    packet = await common.approved_packet(session, app) if app is not None else None
    match = next((f for f in (packet.contents.files if packet else []) if f.sha256 == data["f"]), None)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="the file is no longer in the approved packet")
    try:
        content = await attachment_loader(default_file_store())(match)
    except Exception as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="the file is not stored") from exc
    if hashlib.sha256(content).hexdigest() != match.sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="the stored file does not match the packet")
    await audit.record(session, actor="system", action="gateway.file_downloaded", subject_type="agent_task",
                       subject_id=task.id, detail={"sha256": match.sha256, "name": match.name})
    safe = "".join(c for c in match.name if c.isalnum() or c in "._- ")[:120] or "file"
    return Response(content, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "no-store"})


@router.put("/uploads/{signed}", name="gateway_upload", status_code=status.HTTP_201_CREATED,
            response_model=dict[str, str])
async def upload(signed: str, request: Request, session: SessionDep) -> dict[str, str]:
    """One evidence file (screenshot or confirmation) from a runner. Stored as untrusted data."""
    from app.connect.local_store import default_file_store

    at = common.now()
    data = unsign("upload", signed, at=at)
    task = await _live_task(session, str(data["t"]))
    ref = str(data["r"])
    if ref in (task.payload.get("uploads") or {}):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="this link has already been used")
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type != data["ct"]:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"expected {data['ct']}")
    limit = int(await common.setting(session, "runners.evidence_max_kb")) * 1024
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="the file is too large")
    if not body:
        raise HTTPException(422, detail="empty upload")
    stored = await default_file_store().put(f"{EVIDENCE_PREFIX}{task.id}/{ref}", bytes(body), content_type)
    task.payload = {**task.payload, "uploads": {**(task.payload.get("uploads") or {}),
                                                ref: {"sha256": stored.sha256, "type": content_type,
                                                      "bytes": len(body), "at": at.isoformat()}}}
    await audit.record(session, actor="system", action="gateway.evidence_uploaded", subject_type="agent_task",
                       subject_id=task.id, detail={"ref": ref, "sha256": stored.sha256, "bytes": len(body)})
    return {"ref": ref, "sha256": stored.sha256}
