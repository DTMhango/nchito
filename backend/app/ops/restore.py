"""Restore a backup into a database and a files folder. DESIGN.md 14, 18.3.

Order of work, so a bad backup never half-replaces a good instance:
1. Decrypt and unpack to a temporary folder; check the vault hash against the manifest.
2. ``pg_restore`` in one transaction (``--clean --if-exists``), then compare every table's row count
   with the manifest.
3. Only then move the current files folder aside (never deleted) and put the backup's files in place.
4. Pause the instance: ``automation.paused`` is set, audited as ``backup.restored``. A restored
   instance reconciles its outbox against the mailbox's sent items before the owner resumes it.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from app.core.clock import utcnow
from app.core.config import get_config
from app.ops.backup import (
    BackupError,
    _countable,
    _run,
    decrypt_file,
    libpq_args,
    pg_tool,
    sync_url,
    table_counts,
    vault_hash,
)


@dataclass
class RestoreResult:
    created_at: str
    app_revision: str | None
    tables_checked: int
    files_restored: int
    files_moved_to: str | None
    paused: bool
    warnings: list[str] = field(default_factory=list)


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
            raise BackupError(f"unsafe entry in the backup: {m.name!r}")
        members.append(m)
    return members


def _pause(url: str, reason: str) -> None:
    """Set ``automation.paused`` and audit it, with plain SQL (works before the app is migrated or running)."""
    with psycopg.connect(sync_url(url)) as conn:
        row = conn.execute("SELECT version FROM setting WHERE key = 'automation.paused'").fetchone()
        version = (row[0] + 1) if row else 1
        conn.execute(
            "INSERT INTO setting (key, value, version, updated_by) VALUES ('automation.paused', 'true'::jsonb, %s, "
            "'restore') ON CONFLICT (key) DO UPDATE SET value = 'true'::jsonb, version = EXCLUDED.version, "
            "updated_by = 'restore', updated_at = now()", (version,))
        conn.execute(
            "INSERT INTO setting_revision (key, version, old_value, new_value, changed_by, reason) "
            "VALUES ('automation.paused', %s, NULL, 'true'::jsonb, 'restore', %s)", (version, reason))
        conn.execute(
            "INSERT INTO audit_event (actor, action, subject_type, detail) VALUES ('restore', 'backup.restored', "
            "'backup', %s::jsonb)", (json.dumps({"reason": reason}),))
        conn.commit()


def _load_dump(url: str, dump: Path, work: Path) -> None:
    """Load the dump in one transaction. When the client tools are newer than the server, pg_restore may send
    settings the server does not know (``SET transaction_timeout`` from a v17 client to a v16 server); then the
    dump is rendered to SQL, those lines are dropped, and psql applies it. Match the client to the server
    version where you can (RUNBOOK.md)."""
    args, env = libpq_args(url)
    base = ["--clean", "--if-exists", "--no-owner", "--no-privileges"]
    try:
        _run([pg_tool("pg_restore"), *base, "--single-transaction", "--exit-on-error", *args, str(dump)], env)
        return
    except BackupError as exc:
        if "unrecognized configuration parameter" not in str(exc):
            raise
    script = work / "restore.sql"
    _run([pg_tool("pg_restore"), *base, "--file", str(script), str(dump)], env)
    lines = script.read_text(encoding="utf-8").splitlines(keepends=True)
    script.write_text("".join(ln for ln in lines if not ln.startswith("SET transaction_timeout")), encoding="utf-8")
    _run([pg_tool("psql"), "--quiet", "--single-transaction", "--set", "ON_ERROR_STOP=1", *args,
          "--file", str(script)], env)


def _restore(path: Path, url: str, files_dir: Path, pause: bool) -> RestoreResult:
    pg_tool("pg_restore")
    with tempfile.TemporaryDirectory(prefix="nchito-restore-") as tmp:
        work = Path(tmp)
        tar_path = work / "backup.tar"
        decrypt_file(path, tar_path)
        unpacked = work / "unpacked"
        with tarfile.open(tar_path) as tar:
            for m in _safe_members(tar):
                tar.extract(m, unpacked)
        manifest = json.loads((unpacked / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != 1:
            raise BackupError(f"unsupported backup format: {manifest.get('format')!r}")
        extracted_files = unpacked / "files"
        digest, nfiles = vault_hash(extracted_files)
        if digest != manifest["vault_sha256"]:
            raise BackupError("the files in the backup do not match its manifest; nothing was restored")

        _load_dump(url, unpacked / "db.dump", work)

        warnings: list[str] = []
        with psycopg.connect(sync_url(url)) as conn:
            actual = table_counts(conn)
        expected = {t: n for t, n in manifest["table_counts"].items() if _countable(t)}
        bad = {t: (n, actual.get(t)) for t, n in expected.items() if actual.get(t) != n}
        if bad:
            raise BackupError(f"restored row counts differ from the backup for: {sorted(bad)}")

        moved: str | None = None
        if files_dir.exists() and any(files_dir.iterdir()):
            moved_to = files_dir.with_name(f"{files_dir.name}.before-restore-{utcnow().strftime('%Y%m%dT%H%M%S')}")
            files_dir.rename(moved_to)
            moved = str(moved_to)
        files_dir.parent.mkdir(parents=True, exist_ok=True)
        if extracted_files.is_dir():
            shutil.copytree(extracted_files, files_dir)
        else:
            files_dir.mkdir(parents=True, exist_ok=True)
        restored_digest, restored_files = vault_hash(files_dir)
        if restored_digest != manifest["vault_sha256"]:
            raise BackupError("the restored files do not match the manifest")

        if pause:
            _pause(url, f"restored from backup made {manifest['created_at']}")
        return RestoreResult(created_at=manifest["created_at"], app_revision=manifest.get("alembic_revision"),
                             tables_checked=len(expected), files_restored=restored_files or nfiles,
                             files_moved_to=moved, paused=pause, warnings=warnings)


async def restore_backup(path: Path, *, database_url: str | None = None, files_dir: Path | None = None,
                         pause: bool = True) -> RestoreResult:
    cfg = get_config()
    return await asyncio.to_thread(_restore, Path(path), database_url or cfg.libpq_url,
                                   files_dir or cfg.files_dir, pause)


def describe(path: Path) -> dict[str, object]:
    """Read a backup's manifest without restoring anything (the CLI's ``--inspect``)."""
    with tempfile.TemporaryDirectory(prefix="nchito-inspect-") as tmp:
        tar_path = Path(tmp) / "backup.tar"
        decrypt_file(Path(path), tar_path)
        with tarfile.open(tar_path) as tar:
            member = tar.extractfile("manifest.json")
            assert member is not None
            manifest: dict[str, object] = json.loads(member.read().decode("utf-8"))
    created = datetime.fromisoformat(str(manifest["created_at"]))
    return {**manifest, "created_at": created.isoformat()}
