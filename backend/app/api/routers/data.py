"""Data: the two exports (share setup / personal backup), kit import with diff, old-kit
importer, application-history import, backups, retention, config history. Waves 1-2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Ok, Page
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.kit import export as kit_export
from app.kit import onboarding, service
from app.kit.importers import history, kitfile, office, oldkit, staging
from app.kit.zipsafe import ZipLimits
from app.llm.client import LLMClient
from app.llm.deps import llm_service
from app.models.kit import Fact
from app.models.platform import ConfigKind, ConfigRevision, SettingRevision
from app.ops import backup as ops_backup
from app.ops import config_rollback as rollback_lib
from app.ops import jobs as ops_jobs
from app.ops import retention as ops_retention

router = APIRouter(prefix="/api/data", tags=["data"], dependencies=[RequireOwner],
                   responses=NOT_IMPLEMENTED_RESPONSES)


class ExportIn(BaseModel):
    kind: Literal["share_setup", "personal_backup"]
    acknowledge_personal_details: bool = Field(
        default=False, description="Share setup only: export even though the preview found personal details")


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


class OnboardingStepOut(BaseModel):
    key: str
    label: str
    done: bool
    detail: str


class OnboardingOut(BaseModel):
    steps: list[OnboardingStepOut]
    complete: bool
    next_step: str | None = Field(description="Key of the first step not done, or null")


MB = 1024 * 1024


async def _limits(session: SessionDep) -> ZipLimits:
    values = await settings_service.values(session)
    return ZipLimits(max_zip_bytes=values["data.import_max_zip_mb"] * MB,
                     max_file_bytes=values["data.import_max_file_mb"] * MB,
                     max_files=values["data.import_max_files"])


@router.post("/export/preview", response_model=ExportPreviewOut, name="data_export_preview")
async def export_preview(body: ExportIn, session: SessionDep) -> ExportPreviewOut:
    """What would be exported. A share setup is scanned for personal details first (18.5)."""
    bundle = await kit_export.prepare(session, body.kind)
    hits = kit_export.personal_details(bundle) if body.kind == "share_setup" else []
    return ExportPreviewOut(kind=body.kind, counts=kit_export.counts(bundle.kit),
                            personal_details_found=[PersonalDetailHit(path=h.path, kind=h.kind, excerpt=h.excerpt)
                                                    for h in hits])


@router.post("/export", response_model=ExportOut, name="data_export",
             responses={409: {"description": "Personal details found in a share setup"}})
async def export(body: ExportIn, session: SessionDep, principal: PrincipalDep) -> ExportOut:
    now = utcnow()
    bundle = await kit_export.prepare(session, body.kind, exported_at=now)
    hits = kit_export.personal_details(bundle) if body.kind == "share_setup" else []
    if hits and not body.acknowledge_personal_details:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=(
            f"the preview found {len(hits)} personal detail(s); remove them or export with "
            "acknowledge_personal_details"))
    minutes = await settings_service.get_value(session, "data.export_link_minutes")
    stored = kit_export.store_export(get_config().files_dir, kit_export.build_zip(bundle),
                                     kit_export.file_name(body.kind, now), lifetime_minutes=minutes, now=now)
    await audit.record(session, actor=principal.actor, action="kit.exported", subject_type="kit",
                       detail={"kind": body.kind, "sha256": stored.sha256, "personal_details": len(hits),
                               "counts": kit_export.counts(bundle.kit)})
    return ExportOut(download_url=f"/api/data/exports/{stored.export_id}", file_name=stored.file_name,
                     sha256=stored.sha256, expires_at=stored.expires_at)


@router.get("/exports/{export_id}", name="data_export_download", response_class=FileResponse,
            responses={404: {"description": "Unknown or expired export"}})
async def download_export(export_id: str) -> FileResponse:
    stored = kit_export.find_export(get_config().files_dir, export_id)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="this export has expired; prepare it again")
    return FileResponse(stored.path, media_type="application/zip", filename=stored.file_name)


@router.get("/onboarding", response_model=OnboardingOut, name="data_onboarding")
async def onboarding_state(session: SessionDep) -> OnboardingOut:
    """Which wizard steps are done, computed from the data (13)."""
    steps = await onboarding.compute(session)
    pending = next((st.key for st in steps if not st.done), None)
    return OnboardingOut(steps=[OnboardingStepOut(key=st.key, label=st.label, done=st.done, detail=st.detail)
                                for st in steps], complete=pending is None, next_step=pending)


def _diff_items(rows: list[kitfile.DiffRow]) -> list[ImportDiffItem]:
    return [ImportDiffItem(entity=r.entity, key=r.key, change=r.change, before=r.before, after=r.after)
            for r in rows]


def _history_items(plan: history.ImportPlan) -> tuple[list[ImportDiffItem], list[str]]:
    change = {"create": "add", "update": "update", "unchanged": "unchanged"}
    items = [ImportDiffItem(entity="application_history", key=r.key, change=change[r.action],  # type: ignore[arg-type]
                            before=[{"field": c.field, "before": c.before} for c in r.changes] or None,
                            after={"company": r.company, "role": r.role, "stage": r.stage.value,
                                   "changes": [{"field": c.field, "after": c.after} for c in r.changes]})
             for r in plan.rows if r.action in change]
    notices = [f"history line {e.line}: {e.message}" for e in plan.errors]
    return items, notices


async def _existing_facts(session: SessionDep) -> tuple[dict[str, str], int]:
    codes = {" ".join(t.casefold().split()): c for t, c in (await session.execute(
        select(Fact.text, Fact.code))).all()}
    return codes, int((await service.next_fact_code(session))[2:])


@router.post("/import", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED,
             name="data_import_preview", responses={413: {"description": "Upload too large"},
                                                    422: {"description": "Not importable"}})
async def import_preview(
    file: Annotated[UploadFile, File()],
    source: Annotated[Literal["kit_file", "old_kit_zip", "history_csv", "free_form"], Form()],
    session: SessionDep,
    llm: Annotated[LLMClient, Depends(llm_service)],
) -> ImportPreviewOut:
    """Validate and diff; nothing is written to the database until commit. Imported items land as needs_review."""
    limits = await _limits(session)
    data = await file.read(limits.max_zip_bytes + 1)
    if len(data) > limits.max_zip_bytes:
        raise HTTPException(413, detail="the upload is larger than the limit")
    values = await settings_service.values(session)
    files_dir, hours = get_config().files_dir, values["data.import_staging_hours"]
    notices: list[str] = []
    diff: list[ImportDiffItem] = []
    kit_zip: bytes | None = None
    history_csv: bytes | None = None
    try:
        if source == "kit_file":
            parsed = kitfile.parse_kit_zip(data, limits)
            diff = _diff_items(await kitfile.plan(session, parsed.kit))
            kit_zip = data
        elif source in ("old_kit_zip", "free_form"):
            codes, next_no = await _existing_facts(session)
            if source == "old_kit_zip":
                result = await oldkit.build(data, limits, existing_fact_codes=codes, next_fact_number=next_no,
                                            llm=llm, use_ai=bool(values["data.old_kit_ai_extraction"]),
                                            tracker_headers=values["data.old_kit_tracker_headers"])
            else:
                name = file.filename or "free-form text"
                text = office.to_text(name, data, limits) if office.is_office(name) else data.decode(
                    "utf-8-sig", errors="replace")
                result = await oldkit.build_free_form(text, name, llm, existing_fact_codes=codes,
                                                      next_fact_number=next_no)
            diff = _diff_items(await kitfile.plan(session, result.kit))
            notices += result.notices
            kit_zip = kit_export.build_zip(kit_export.KitBundle(kit=result.kit, vault_files=result.vault_files))
            history_csv = result.history_csv
        else:
            history_csv = data
        if history_csv is not None:
            try:
                extra, hist_notes = _history_items(await history.plan(session, history.parse_csv(history_csv)))
            except history.HistoryFormatError as exc:
                if source == "history_csv":
                    raise
                history_csv, extra, hist_notes = None, [], [f"The application log was not imported: {exc}"]
            diff += extra
            notices += hist_notes
    except (kitfile.KitImportError, oldkit.OldKitError, history.HistoryFormatError, office.OfficeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    import_id = staging.stage(files_dir, source=source, kit_zip=kit_zip, history_csv=history_csv, hours=hours)
    return ImportPreviewOut(import_id=import_id, source=source, diff=diff, notices=notices)


@router.post("/import/commit", response_model=ImportCommitOut, name="data_import_commit",
             responses={404: {"description": "Unknown or expired import"}, 422: {"description": "Not importable"}})
async def import_commit(body: ImportCommitIn, session: SessionDep, principal: PrincipalDep) -> ImportCommitOut:
    """Apply a previewed import in one transaction (everything or nothing). Re-validates the staged bytes."""
    values = await settings_service.values(session)
    files_dir = get_config().files_dir
    staged = staging.load(files_dir, body.import_id, values["data.import_staging_hours"])
    if staged is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="this import has expired; upload it again")
    created = updated = review = 0
    try:
        if staged.kit_zip is not None:
            parsed = kitfile.parse_kit_zip(staged.kit_zip, await _limits(session))
            applied = await kitfile.apply(session, parsed, exclude=set(body.exclude_keys), actor=principal.actor)
            created, updated, review = applied.created, applied.updated, applied.needs_review
        if staged.history_csv is not None and not any(k.startswith("application_history:") for k in body.exclude_keys):
            result = await history.commit(session, history.parse_csv(staged.history_csv), actor=principal.actor)
            created, updated = created + result.created, updated + result.updated
    except (kitfile.KitImportError, history.HistoryFormatError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await session.flush()
    staging.discard(files_dir, body.import_id)
    return ImportCommitOut(created=created, updated=updated, needs_review=review)


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
                rollback_of=r.rollback_of, note=r.reason)))
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


async def _revision_out(session: SessionDep, done: rollback_lib.RolledBack) -> ConfigRevisionOut:
    if done.kind == SETTING_KIND:
        r = await session.get(SettingRevision, done.new_id)
        assert r is not None
        return ConfigRevisionOut(
            id=r.id, kind=SETTING_KIND, subject_id=None, version=r.version, author=r.changed_by,
            created_at=r.created_at, diff={"key": r.key, "old": r.old_value, "new": r.new_value},
            rollback_of=r.rollback_of, note=r.reason)
    c = await session.get(ConfigRevision, done.new_id)
    assert c is not None
    return ConfigRevisionOut(id=c.id, kind=c.kind.value, subject_id=c.subject_id, version=c.version,
                             author=c.author, created_at=c.created_at, diff=c.diff, rollback_of=c.rollback_of,
                             note=c.note)


@router.post("/config-history/{revision_id}/rollback", response_model=ConfigRevisionOut,
             name="data_config_rollback")
async def rollback(revision_id: uuid.UUID, body: RollbackIn, principal: PrincipalDep,
                   session: SessionDep) -> ConfigRevisionOut:
    """Restore a revision's value as a NEW revision (history is never edited). Settings go through the settings
    validators; a setting with its own endpoint (the global pause) and a model route that has not passed a recent
    test are refused. Rollback affects future work only."""
    from app.llm import api as llm_api

    async def activate_route(snapshot: dict[str, Any], note: str | None) -> None:
        values = await settings_service.values(session)
        if snapshot.get("provider") != values["ai.provider"]:
            raise rollback_lib.RollbackError(409, "that route belongs to a different provider than the current one")
        try:
            await llm_api.activate_route(
                llm_api.RouteActivateIn(stage=str(snapshot["stage"]), model=str(snapshot["model"]),
                                        reason=note or "restored an earlier route"), session, principal)
        except HTTPException as exc:
            raise rollback_lib.RollbackError(exc.status_code, str(exc.detail)) from exc

    try:
        srev = await session.get(SettingRevision, revision_id)
        if srev is not None:
            done = await rollback_lib.rollback_setting(session, srev, actor=principal.actor, note=body.note)
        else:
            crev = await session.get(ConfigRevision, revision_id)
            if crev is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such revision")
            done = await rollback_lib.rollback_config(session, crev, actor=principal.actor, note=body.note,
                                                      route_activator=activate_route)
    except rollback_lib.RollbackError as exc:
        await session.rollback()
        raise HTTPException(exc.status, detail=exc.detail) from exc
    return await _revision_out(session, done)
