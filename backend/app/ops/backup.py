"""Backups: ``pg_dump`` plus the files volume, one encrypted archive. DESIGN.md 14, 18.3.

Archive: ``nchito-<UTC timestamp>.backup``, a Fernet-encrypted tar (``manifest.json``, ``db.dump``,
``files/...``). The key is ``ENCRYPTION_KEY`` and is never stored in a backup: restoring on a
new server needs the same key (RUNBOOK.md). The dump and the row counts in the manifest come from
one exported snapshot, so a restore can be checked against the manifest exactly.

Encryption is chunked (4 MiB per Fernet token, length-prefixed) so a large vault is never held in
memory twice. Local copies are always written; the configured remote store gets the same file.
Retention here prunes old backups to ``backups.keep``; it never touches application data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import struct
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import psycopg

from app import __version__
from app.connect.filestore import FileStore
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.crypto import fernet

log = logging.getLogger(__name__)

MAGIC = b"NCHBK1\n"
CHUNK = 4 * 1024 * 1024
MANIFEST_FORMAT = 1
BACKUP_SUFFIX = ".backup"
TEMP_DIR_NAME = "tmp"  # under FILES_DIR; never archived
VOLATILE_TABLE_PREFIXES = ("procrastinate_",)
VOLATILE_TABLES = frozenset({"worker_heartbeat"})


class BackupError(RuntimeError):
    pass


# ----- tools ---------------------------------------------------------------------------------


def pg_tool(name: str) -> str:
    folder = get_config().pg_bin_dir
    candidates = [str(folder / name), str(folder / f"{name}.exe")] if folder else []
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return found
    raise BackupError(f"{name} was not found: install the PostgreSQL client tools or set PG_BIN_DIR")


def pg_available() -> bool:
    try:
        pg_tool("pg_dump")
        pg_tool("pg_restore")
    except BackupError:
        return False
    return True


def libpq_args(url: str) -> tuple[list[str], dict[str, str]]:
    """Connection arguments and environment for pg_dump/pg_restore, keeping the password out of argv."""
    parts = urlsplit(url)
    env = dict(os.environ)
    if parts.password:
        env["PGPASSWORD"] = unquote(parts.password)
    args = ["--host", parts.hostname or "localhost", "--port", str(parts.port or 5432),
            "--username", unquote(parts.username or "postgres"), "--dbname", (parts.path or "/").lstrip("/")]
    return args, env


def sync_url(url: str) -> str:
    """A psycopg-style URL for either an asyncpg SQLAlchemy URL or a plain libpq URL."""
    return "postgresql://" + url.split("://", 1)[1]


def _run(cmd: list[str], env: dict[str, str]) -> None:
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise BackupError(f"{Path(cmd[0]).name} failed: {' | '.join(tail)}"[:500])


# ----- encryption ----------------------------------------------------------------------------


def encrypt_file(src: Path, dst: Path) -> None:
    f = fernet()
    with src.open("rb") as fin, dst.open("wb") as fout:
        fout.write(MAGIC)
        while chunk := fin.read(CHUNK):
            token = f.encrypt(chunk)
            fout.write(struct.pack(">I", len(token)) + token)


def decrypt_file(src: Path, dst: Path) -> None:
    from cryptography.fernet import InvalidToken

    f = fernet()
    with src.open("rb") as fin, dst.open("wb") as fout:
        if fin.read(len(MAGIC)) != MAGIC:
            raise BackupError("not an Nchito backup file")
        while header := fin.read(4):
            (size,) = struct.unpack(">I", header)
            token = fin.read(size)
            if len(token) != size:
                raise BackupError("the backup file is truncated")
            try:
                fout.write(f.decrypt(token))
            except InvalidToken as exc:
                raise BackupError("cannot decrypt the backup: wrong ENCRYPTION_KEY or a damaged file") from exc


# ----- the vault -----------------------------------------------------------------------------


def iter_vault(files_dir: Path) -> list[tuple[str, Path]]:
    """Files to archive, as (POSIX relative path, absolute path), sorted; the temp folder is skipped."""
    if not files_dir.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for path in sorted(files_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(files_dir).as_posix()
        if rel.split("/", 1)[0] == TEMP_DIR_NAME or rel.endswith(".part"):
            continue
        out.append((rel, path))
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def vault_hash(files_dir: Path) -> tuple[str, int]:
    """One hash over every archived file's path and content, and the file count."""
    h = hashlib.sha256()
    files = iter_vault(files_dir)
    for rel, path in files:
        h.update(rel.encode() + b"\0" + _sha256(path).encode() + b"\n")
    return h.hexdigest(), len(files)


# ----- snapshot: dump and counts from the same moment ----------------------------------------


def _countable(table: str) -> bool:
    return table not in VOLATILE_TABLES and not table.startswith(VOLATILE_TABLE_PREFIXES)


def table_counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables if _countable(t)}  # noqa: S608


def dump_database(url: str, dump_path: Path) -> tuple[dict[str, int], str | None]:
    """Dump with pg_dump under an exported snapshot; return the table counts at that snapshot and the revision."""
    args, env = libpq_args(url)
    with psycopg.connect(sync_url(url), autocommit=True) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        _run([pg_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}",
              "--file", str(dump_path), *args], env)
        counts = table_counts(conn)
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone() if conn.execute(
            "SELECT to_regclass('public.alembic_version')").fetchone()[0] else None
        conn.execute("COMMIT")
    return counts, (row[0] if row else None)


# ----- records -------------------------------------------------------------------------------


@dataclass
class BackupInfo:
    id: str
    path: str
    created_at: datetime
    size_bytes: int
    sha256: str
    encrypted: bool = True
    revision: str | None = None
    files: int = 0
    remote_target: str | None = None
    remote_key: str | None = None
    remote_error: str | None = None
    tables: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["created_at"] = self.created_at.isoformat()
        return raw

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> BackupInfo:
        return cls(**{**raw, "created_at": datetime.fromisoformat(raw["created_at"])})


def backup_dir() -> Path:
    return get_config().backup_dir


def list_backups(directory: Path | None = None) -> list[BackupInfo]:
    directory = directory or backup_dir()
    if not directory.is_dir():
        return []
    out: list[BackupInfo] = []
    for meta in directory.glob(f"*{BACKUP_SUFFIX}.json"):
        try:
            info = BackupInfo.from_json(json.loads(meta.read_text(encoding="utf-8")))
        except (ValueError, TypeError, KeyError):
            continue
        if Path(info.path).is_file():
            out.append(info)
    return sorted(out, key=lambda i: i.created_at, reverse=True)


# ----- create --------------------------------------------------------------------------------


def _build_archive(url: str, files_dir: Path, now: datetime, workdir: Path) -> tuple[Path, BackupInfo]:
    dump = workdir / "db.dump"
    counts, revision = dump_database(url, dump)
    digest, nfiles = vault_hash(files_dir)
    manifest = {"format": MANIFEST_FORMAT, "app_version": __version__, "created_at": now.isoformat(),
                "alembic_revision": revision, "table_counts": counts, "vault_sha256": digest, "vault_files": nfiles}
    (workdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tar_path = workdir / "backup.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(workdir / "manifest.json", arcname="manifest.json")
        tar.add(dump, arcname="db.dump")
        for rel, path in iter_vault(files_dir):
            tar.add(path, arcname=f"files/{rel}")
    name = f"nchito-{now.strftime('%Y%m%dT%H%M%SZ')}{BACKUP_SUFFIX}"
    encrypted = workdir / name
    encrypt_file(tar_path, encrypted)
    info = BackupInfo(id=name.removesuffix(BACKUP_SUFFIX), path="", created_at=now, size_bytes=encrypted.stat().st_size,
                      sha256=_sha256(encrypted), revision=revision, files=nfiles, tables=counts)
    return encrypted, info


async def create_backup(*, database_url: str | None = None, files_dir: Path | None = None,
                        directory: Path | None = None, now: datetime | None = None,
                        store: FileStore | None = None, remote_label: str | None = None) -> BackupInfo:
    """Write one encrypted backup locally and, if ``store`` is given, to it as well. A remote failure is
    recorded on the result (``remote_error``) and does not lose the local copy."""
    cfg = get_config()
    url = database_url or cfg.libpq_url
    files_dir = files_dir or cfg.files_dir
    directory = directory or backup_dir()
    now = (now or utcnow()).replace(microsecond=0)
    directory.mkdir(parents=True, exist_ok=True)
    pg_tool("pg_dump")

    def work() -> BackupInfo:
        with tempfile.TemporaryDirectory(prefix="nchito-backup-") as tmp:
            archive, info = _build_archive(url, files_dir, now, Path(tmp))
            final = directory / archive.name
            partial = final.with_name(final.name + ".part")
            shutil.copyfile(archive, partial)
            partial.replace(final)
            info.path = str(final)
            return info

    info = await asyncio.to_thread(work)
    if store is not None:
        key = f"backups/{Path(info.path).name}"
        try:
            payload = await asyncio.to_thread(Path(info.path).read_bytes)
            await store.put(key, payload, "application/octet-stream")
            info.remote_target, info.remote_key = remote_label or store.kind, key
        except Exception as exc:  # the local copy stands; the caller reports the remote failure
            info.remote_target, info.remote_error = remote_label or store.kind, f"{type(exc).__name__}: {exc}"[:300]
    await asyncio.to_thread(Path(info.path + ".json").write_text, json.dumps(info.to_json(), indent=2), "utf-8")
    return info


def _forget(info: BackupInfo) -> None:
    Path(info.path).unlink(missing_ok=True)
    Path(info.path + ".json").unlink(missing_ok=True)


async def prune_backups(keep: int, *, directory: Path | None = None, store: FileStore | None = None) -> list[str]:
    """Delete backups beyond the newest ``keep`` (file, record, and its remote copy). Returns removed ids.
    A remote copy that cannot be deleted keeps its local record, so the delete is retried next time."""
    removed: list[str] = []
    for info in list_backups(directory)[keep:]:
        if store is not None and info.remote_key:
            try:
                await store.delete(info.remote_key)
            except Exception:
                log.warning("could not delete remote backup %s; will retry", info.id)
                continue
        await asyncio.to_thread(_forget, info)
        removed.append(info.id)
    return removed
