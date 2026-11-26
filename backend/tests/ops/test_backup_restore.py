# ruff: noqa: ASYNC240  (tests read small local files directly)
"""Backup and restore: dump, wipe a scratch database, restore, compare row counts and the vault hash.

Needs ``pg_dump`` and ``pg_restore`` on PATH (or PG_BIN_DIR); the tests skip with a clear reason otherwise.
They use their own scratch databases on the test server, never the shared test database.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import audit
from app.models.applications import Application, Stage
from app.models.platform import AuditEvent, Setting
from app.models.search import Job
from app.ops import backup, restore
from tests.conftest import BASE, recreate_database, run_migrations

pytestmark = [
    pytest.mark.nodb,
    pytest.mark.skipif(not backup.pg_available(),
                       reason="pg_dump / pg_restore are not on PATH; install the PostgreSQL client tools"),
]


@pytest.fixture
def scratch_db():
    name = f"nchito_bk_{uuid.uuid4().hex[:8]}"
    url = recreate_database(name)
    run_migrations(url)
    yield name, url
    with psycopg.connect(BASE + "/postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def seed(url: str) -> None:
    engine = create_async_engine("postgresql+asyncpg://" + url.split("://", 1)[1])
    async with AsyncSession(engine) as s:
        jobs = [Job(title=f"Analyst {i}", employer="Acme Ltd", canonical_employer="Acme Ltd",
                    content_hash=uuid.uuid4().hex.ljust(64, "0"), raw_text=f"posting {i}") for i in range(3)]
        s.add_all(jobs)
        await s.flush()
        s.add(Application(job_id=jobs[0].id, stage=Stage.submitted, applied_at=datetime.now(UTC)))
        s.add(Setting(key="scoring.threshold_shortlist", value=61, version=1, updated_by="test"))
        await audit.record(s, actor="owner", action="job.viewed", subject_type="job", subject_id=jobs[0].id)
        await s.commit()
    await engine.dispose()


def write_vault(root: Path) -> None:
    (root / "vault").mkdir(parents=True)
    (root / "vault" / "cv.pdf").write_bytes(b"%PDF cv " * 1000)
    (root / "applications" / "a1").mkdir(parents=True)
    (root / "applications" / "a1" / "snapshot.json").write_text('{"submitted": true}', encoding="utf-8")
    (root / "tmp").mkdir()
    (root / "tmp" / "scratch.bin").write_bytes(b"temporary")


def counts(url: str) -> dict[str, int]:
    with psycopg.connect(url) as conn:
        return backup.table_counts(conn)


async def test_backup_wipe_restore_round_trip(scratch_db, tmp_path) -> None:
    name, url = scratch_db
    await seed(url)
    files = tmp_path / "files"
    write_vault(files)
    before_counts = counts(url)
    before_hash, before_n = backup.vault_hash(files)
    assert before_counts["job"] == 3 and before_counts["application"] == 1 and before_n == 2

    info = await backup.create_backup(database_url=url, files_dir=files, directory=tmp_path / "backups",
                                      now=datetime(2026, 11, 26, 2, 0, tzinfo=UTC))
    archive = Path(info.path)
    assert archive.name == "nchito-20261126T020000Z.backup" and info.files == 2
    raw = archive.read_bytes()
    assert raw.startswith(backup.MAGIC) and b"%PDF" not in raw and b"Analyst" not in raw, "the archive is encrypted"
    assert info.tables["job"] == 3

    # wipe: a brand new empty database and a new, empty files folder
    recreate_database(name)
    assert not [t for t in counts(url)]  # no tables at all
    restored_files = tmp_path / "restored-files"

    result = await restore.restore_backup(archive, database_url=url, files_dir=restored_files)

    assert result.paused and result.tables_checked == len([t for t in before_counts])
    after = counts(url)
    for table, n in before_counts.items():
        if table == "audit_event":
            assert after[table] == n + 1, "the restore itself is audited"
        elif table in ("setting", "setting_revision"):
            assert after[table] >= n  # pausing adds a setting and its revision
        else:
            assert after[table] == n, table
    after_hash, after_n = backup.vault_hash(restored_files)
    assert (after_hash, after_n) == (before_hash, before_n)
    assert not (restored_files / "tmp").exists(), "temporary files are not part of a backup"
    assert (restored_files / "vault" / "cv.pdf").read_bytes() == b"%PDF cv " * 1000

    engine = create_async_engine("postgresql+asyncpg://" + url.split("://", 1)[1])
    async with AsyncSession(engine) as s:
        paused = await s.scalar(select(Setting).where(Setting.key == "automation.paused"))
        assert paused is not None and paused.value is True and paused.updated_by == "restore"
        assert await s.scalar(select(AuditEvent).where(AuditEvent.action == "backup.restored")) is not None
        job = await s.scalar(select(Job).where(Job.title == "Analyst 1"))
        assert job is not None and job.raw_text == "posting 1"
    await engine.dispose()


async def test_restore_moves_existing_files_aside_and_can_skip_pausing(scratch_db, tmp_path) -> None:
    _, url = scratch_db
    files = tmp_path / "files"
    write_vault(files)
    info = await backup.create_backup(database_url=url, files_dir=files, directory=tmp_path / "b")
    target = tmp_path / "live"
    target.mkdir()
    (target / "old.txt").write_text("keep me", encoding="utf-8")

    result = await restore.restore_backup(Path(info.path), database_url=url, files_dir=target, pause=False)

    assert not result.paused
    assert result.files_moved_to and (Path(result.files_moved_to) / "old.txt").read_text(encoding="utf-8") == "keep me"
    assert not (target / "old.txt").exists() and (target / "vault" / "cv.pdf").exists()


async def test_a_wrong_key_or_a_damaged_file_restores_nothing(scratch_db, tmp_path, monkeypatch) -> None:
    _, url = scratch_db
    await seed(url)
    files = tmp_path / "files"
    write_vault(files)
    info = await backup.create_backup(database_url=url, files_dir=files, directory=tmp_path / "b")
    before = counts(url)

    monkeypatch.setattr(backup, "fernet", lambda: Fernet(Fernet.generate_key()))
    with pytest.raises(backup.BackupError, match="ENCRYPTION_KEY"):
        await restore.restore_backup(Path(info.path), database_url=url, files_dir=tmp_path / "x")
    monkeypatch.undo()

    damaged = Path(info.path)
    data = bytearray(damaged.read_bytes())
    data[len(data) // 2] ^= 0xFF
    damaged.write_bytes(bytes(data))
    with pytest.raises(backup.BackupError):
        await restore.restore_backup(damaged, database_url=url, files_dir=tmp_path / "x")
    assert counts(url) == before and not (tmp_path / "x").exists()

    not_a_backup = tmp_path / "junk.backup"
    not_a_backup.write_bytes(b"hello")
    with pytest.raises(backup.BackupError, match="not an Nchito backup"):
        await restore.restore_backup(not_a_backup, database_url=url, files_dir=tmp_path / "x")


async def test_prune_keeps_the_newest_n_and_their_records(scratch_db, tmp_path) -> None:
    _, url = scratch_db
    files = tmp_path / "files"
    write_vault(files)
    directory = tmp_path / "b"
    base = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)
    for day in range(4):
        await backup.create_backup(database_url=url, files_dir=files, directory=directory,
                                   now=base + timedelta(days=day))
    removed = await backup.prune_backups(2, directory=directory)
    assert sorted(removed) == ["nchito-20261120T020000Z", "nchito-20261121T020000Z"]
    left = backup.list_backups(directory)
    assert [i.id for i in left] == ["nchito-20261123T020000Z", "nchito-20261122T020000Z"]
    assert sorted(p.name for p in directory.iterdir()) == sorted(
        [i.id + ".backup" for i in left] + [i.id + ".backup.json" for i in left])


async def test_remote_copy_and_its_failure_do_not_lose_the_local_backup(scratch_db, tmp_path) -> None:
    from app.connect.local_store import LocalFileStore

    _, url = scratch_db
    files = tmp_path / "files"
    write_vault(files)
    remote = LocalFileStore(tmp_path / "remote")
    info = await backup.create_backup(database_url=url, files_dir=files, directory=tmp_path / "b", store=remote,
                                      remote_label="gdrive")
    assert info.remote_target == "gdrive" and info.remote_key and await remote.exists(info.remote_key)
    assert await remote.get(info.remote_key) == Path(info.path).read_bytes()

    class Broken:
        kind = "gdrive"

        async def put(self, *a, **k):
            raise RuntimeError("drive is down")

    bad = await backup.create_backup(database_url=url, files_dir=files, directory=tmp_path / "b2", store=Broken(),
                                     now=datetime(2026, 11, 27, tzinfo=UTC))
    assert Path(bad.path).is_file() and bad.remote_error and "drive is down" in bad.remote_error

    # pruning removes the remote copy with the local one
    await backup.prune_backups(0, directory=tmp_path / "b", store=remote)
    assert not await remote.exists(info.remote_key)


def test_restore_inspect_reads_the_manifest_only(scratch_db, tmp_path) -> None:
    _, url = scratch_db
    import asyncio

    files = tmp_path / "files"
    write_vault(files)
    info = asyncio.run(backup.create_backup(database_url=url, files_dir=files, directory=tmp_path / "b"))
    manifest = restore.describe(Path(info.path))
    assert manifest["vault_files"] == 2 and "job" in manifest["table_counts"]  # type: ignore[operator]
    shutil.rmtree(files)  # inspecting needs nothing else
    assert restore.describe(Path(info.path))["format"] == 1
