"""Data: the two exports (share setup / personal backup), kit import with diff, old-kit
importer, application-history import, backups, retention, config history. Waves 1-2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Ok, Page, not_implemented
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.models.platform import ConfigKind, ConfigRevision, SettingRevision
from app.ops import backup as ops_backup
from app.ops import jobs as ops_jobs
from app.ops import retention as ops_retention

router = APIRouter(prefix="/api/data", tags=["data"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)


class ExportIn(BaseModel):
    kind: Literal["share_setup", "personal_backup"]


class PersonalDetailHit(BaseModel):
    path: str
    kind: str = Field(description="email, phone, name, id_number, url, ...")
    excerpt: str


class ExportPreviewOut(BaseModel):
    """Share setup is scanned for personal details and previewed before download (18.5)."""

    kind: Literal["share_setup", "personal_backup"]
    counts: dict[str, int]
    personal_details_found: list[PersonalDetailHit]


class ExportOut(BaseModel):
    download_url: str
    file_name: str
    sha256: str
    expires_at: datetime


class ImportDiffItem(BaseModel):
    entity: str
    key: str
    change: Literal["add", "update", "unchanged", "conflict"]
    before: Any = None
    after: Any = None


class ImportPreviewOut(BaseModel):
    import_id: uuid.UUID
    source: Literal["kit_file", "old_kit_zip", "history_csv", "free_form"]
    diff: list[ImportDiffItem]
    notices: list[str] = Field(description="e.g. 'free-form text will be sent to <provider>'")


class ImportCommitIn(BaseModel):
    import_id: uuid.UUID
    exclude_keys: list[str] = Field(default_factory=list)


class ImportCommitOut(BaseModel):
    created: int
    updated: int
    needs_review: int


class BackupOut(BaseModel):
    id: str
    created_at: datetime
    size_bytes: int
    target: Literal["local", "s3", "gdrive"]
    encrypted: bool


class ConfigRevisionOut(BaseModel):
    id: uuid.UUID
    kind: str
    subject_id: uuid.UUID | None
    version: int
    author: str
    created_at: datetime
    diff: dict[str, Any] | None
    rollback_of: uuid.UUID | None
    note: str | None


class RollbackIn(BaseModel):
    note: str | None = None


@router.post("/export/preview", response_model=ExportPreviewOut, name="data_export_preview")
async def export_preview(body: ExportIn) -> ExportPreviewOut:
    not_implemented(2, "kit_io")


@router.post("/export", response_model=ExportOut, name="data_export")
async def export(body: ExportIn) -> ExportOut:
    not_implemented(2, "kit_io")


@router.post("/import", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED,
             name="data_import_preview")
async def import_preview(
    file: Annotated[UploadFile, File()],
    source: Annotated[Literal["kit_file", "old_kit_zip", "history_csv", "free_form"], Form()],
) -> ImportPreviewOut:
    """Validate and diff; nothing is written until commit. Imported items land as needs_review."""
    not_implemented(2, "kit_io")


@router.post("/import/commit", response_model=ImportCommitOut, name="data_import_commit")
async def import_commit(body: ImportCommitIn) -> ImportCommitOut:
    not_implemented(2, "kit_io")


CONFIG_HISTORY_PAGE = 50
SETTING_KIND = "setting"


def _backup_rows(info: ops_backup.BackupInfo) -> list[BackupOut]:
    rows = [BackupOut(id=info.id, created_at=info.created_at, size_bytes=info.size_bytes, target="local",
                      encrypted=info.encrypted)]
    if info.remote_key and info.remote_target in ("gdrive", "s3"):
        rows.append(BackupOut(id=f"{info.id}:{info.remote_target}", created_at=info.created_at,
                              size_bytes=info.size_bytes, target=info.remote_target,  # type: ignore[arg-type]
                              encrypted=info.encrypted))
    return rows


@router.get("/backups", response_model=list[BackupOut], name="data_backups_list")
async def backups() -> list[BackupOut]:
    """Backups on this server (newest first), plus the copy in the remote store where one was made."""
    return [row for info in ops_backup.list_backups() for row in _backup_rows(info)]


@router.post("/backups", response_model=BackupOut, status_code=status.HTTP_202_ACCEPTED, name="data_backups_create")
async def create_backup(session: SessionDep, principal: PrincipalDep) -> BackupOut:
    """Back up now (the same job as the nightly one). Returns when the archive is written."""
    if not ops_backup.pg_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="pg_dump is not installed on this server; install the PostgreSQL client tools")
    run, info = await ops_jobs.run_backup_job(session, trigger="manual", actor=principal.actor)
    if info is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=run.error or "backup failed")
    return _backup_rows(info)[0]


@router.post("/retention/run", response_model=Ok, status_code=status.HTTP_202_ACCEPTED, name="data_retention_run")
async def run_retention(session: SessionDep) -> Ok:
    """Run retention now: role text and archive rules, old notifications, temp files, surplus backups.
    Duplicate-protection history, the audit and applications are never deleted."""
    try:
        await ops_jobs.run_retention_job(session, trigger="manual")
    except ops_retention.ProtectedDataError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return Ok()


def _cursor_of(created_at: datetime, row_id: uuid.UUID) -> str:
    return f"{created_at.isoformat()}|{row_id}"


def _parse_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        stamp, raw_id = cursor.split("|", 1)
        return datetime.fromisoformat(stamp), uuid.UUID(raw_id)
    except ValueError as exc:
        raise HTTPException(422, detail="bad cursor") from exc


@router.get("/config-history", response_model=Page[ConfigRevisionOut], name="data_config_history")
async def config_history(session: SessionDep, kind: str | None = None, subject_id: uuid.UUID | None = None,
                         cursor: str | None = None) -> Page[ConfigRevisionOut]:
    """Versioned configuration changes, newest first: rules, prompts, rubrics, routing, automation policy
    (``kind`` = their kinds) and every settings change (``kind=setting``)."""
    after = _parse_cursor(cursor)
    items: list[tuple[datetime, uuid.UUID, ConfigRevisionOut]] = []
    if kind in (None, SETTING_KIND) and subject_id is None:
        q = select(SettingRevision).order_by(SettingRevision.created_at.desc(), SettingRevision.id.desc())
        if after:
            q = q.where((SettingRevision.created_at < after[0]) | (
                (SettingRevision.created_at == after[0]) & (SettingRevision.id < after[1])))
        for r in await session.scalars(q.limit(CONFIG_HISTORY_PAGE + 1)):
            items.append((r.created_at, r.id, ConfigRevisionOut(
                id=r.id, kind=SETTING_KIND, subject_id=None, version=r.version, author=r.changed_by,
                created_at=r.created_at, diff={"key": r.key, "old": r.old_value, "new": r.new_value},
                rollback_of=None, note=r.reason)))
    if kind != SETTING_KIND:
        cq = select(ConfigRevision).order_by(ConfigRevision.created_at.desc(), ConfigRevision.id.desc())
        if kind is not None:
            try:
                cq = cq.where(ConfigRevision.kind == ConfigKind(kind))
            except ValueError as exc:
                raise HTTPException(422, detail=f"unknown kind: {kind}") from exc
        if subject_id is not None:
            cq = cq.where(ConfigRevision.subject_id == subject_id)
        if after:
            cq = cq.where((ConfigRevision.created_at < after[0]) | (
                (ConfigRevision.created_at == after[0]) & (ConfigRevision.id < after[1])))
        for c in await session.scalars(cq.limit(CONFIG_HISTORY_PAGE + 1)):
            items.append((c.created_at, c.id, ConfigRevisionOut(
                id=c.id, kind=c.kind.value, subject_id=c.subject_id, version=c.version, author=c.author,
                created_at=c.created_at, diff=c.diff, rollback_of=c.rollback_of, note=c.note)))
    items.sort(key=lambda t: (t[0], t[1]), reverse=True)
    page = items[:CONFIG_HISTORY_PAGE]
    more = len(items) > CONFIG_HISTORY_PAGE
    return Page[ConfigRevisionOut](items=[i[2] for i in page],
                                   next_cursor=_cursor_of(page[-1][0], page[-1][1]) if more and page else None)


@router.post("/config-history/{revision_id}/rollback", response_model=ConfigRevisionOut,
             name="data_config_rollback")
async def rollback(revision_id: uuid.UUID, body: RollbackIn) -> ConfigRevisionOut:
    """Rollback affects future work only."""
    not_implemented(1, "config")
