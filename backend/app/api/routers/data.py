"""Data: the two exports (share setup / personal backup), kit import with diff, old-kit
importer, application-history import, backups, retention, config history. Waves 1-2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, UploadFile, status
from pydantic import BaseModel, Field

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Ok, Page, not_implemented
from app.api.deps import RequireOwner

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


@router.get("/backups", response_model=list[BackupOut], name="data_backups_list")
async def backups() -> list[BackupOut]:
    not_implemented(2, "ops")


@router.post("/backups", response_model=BackupOut, status_code=status.HTTP_202_ACCEPTED, name="data_backups_create")
async def create_backup() -> BackupOut:
    not_implemented(2, "ops")


@router.post("/retention/run", response_model=Ok, status_code=status.HTTP_202_ACCEPTED, name="data_retention_run")
async def run_retention() -> Ok:
    not_implemented(2, "ops")


@router.get("/config-history", response_model=Page[ConfigRevisionOut], name="data_config_history")
async def config_history(kind: str | None = None, subject_id: uuid.UUID | None = None,
                         cursor: str | None = None) -> Page[ConfigRevisionOut]:
    not_implemented(1, "config")


@router.post("/config-history/{revision_id}/rollback", response_model=ConfigRevisionOut,
             name="data_config_rollback")
async def rollback(revision_id: uuid.UUID, body: RollbackIn) -> ConfigRevisionOut:
    """Rollback affects future work only."""
    not_implemented(1, "config")
