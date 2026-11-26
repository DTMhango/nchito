"""Retention: what it removes, and the guarantee that it never touches protected history."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update

from app.core import audit
from app.core.config import get_config
from app.core.settings import service as settings_service
from app.models.applications import Application, Contact, Stage
from app.models.platform import Notification
from app.models.search import Job, Run, RunKind, RunStatus
from app.ops import retention
from tests.tracking.helpers import make_app, make_job

DAY = timedelta(days=1)


async def age(session, model, row_id, days: int) -> None:
    then = datetime.now(UTC) - days * DAY
    await session.execute(update(model).where(model.id == row_id).values(created_at=then, updated_at=then))


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "files_dir", tmp_path / "files")
    monkeypatch.setattr(cfg, "backup_dir", tmp_path / "backups")
    (tmp_path / "files").mkdir()
    return tmp_path


async def seed(session):
    below = await make_job(session, "Old below threshold", "Acme Ltd")
    below.triage, below.raw_text = "below_threshold", "full posting text"
    applied_below = await make_job(session, "Applied, below threshold", "Beta Ltd")
    applied_below.triage, applied_below.raw_text = "below_threshold", "text I applied with"
    stale = await make_job(session, "Never touched", "Gamma Ltd")
    applied = await make_job(session, "Applied role", "Delta Ltd")
    pinned = await make_job(session, "Pinned role", "Epsilon Ltd")
    pinned.pinned = True
    application = await make_app(session, applied, Stage.submitted, applied_at=datetime.now(UTC) - 90 * DAY)
    await make_app(session, applied_below, Stage.submitted, applied_at=datetime.now(UTC) - 90 * DAY)
    session.add(Contact(job_id=applied.id, name="Chola Mwansa"))
    await audit.record(session, actor="owner", action="application.sent", subject_type="application",
                       subject_id=application.id)
    await session.commit()
    for job in (below, applied_below, stale, applied, pinned):
        await age(session, Job, job.id, 100)
    await session.commit()
    return {"below": below.id, "applied_below": applied_below.id, "stale": stale.id, "applied": applied.id,
            "pinned": pinned.id}


async def test_retention_applies_its_rules_and_leaves_protected_history_alone(session, dirs) -> None:
    ids = await seed(session)
    old_note = Notification(kind="x", title="old", dedupe_key="old")
    new_note = Notification(kind="x", title="new", dedupe_key="new")
    session.add_all([old_note, new_note])
    await session.commit()
    await age(session, Notification, old_note.id, 120)
    tmp = dirs / "files" / "tmp"
    tmp.mkdir()
    (tmp / "old.bin").write_bytes(b"old")
    (tmp / "new.bin").write_bytes(b"new")
    old_time = (datetime.now(UTC) - 30 * DAY).timestamp()
    os.utime(tmp / "old.bin", (old_time, old_time))
    (dirs / "files" / "vault").mkdir()
    (dirs / "files" / "vault" / "cv.pdf").write_bytes(b"cv")
    await session.commit()
    before = await retention.protected_counts(session)

    run = await retention.run_all(session, trigger="manual")

    assert run.status == RunStatus.succeeded and run.kind == RunKind.retention
    after = await retention.protected_counts(session)
    assert all(after[t] >= before[t] for t in before), "no protected row was removed"
    assert {t: n for t, n in after.items() if t != "audit_event"} == {t: n for t, n in before.items()
                                                                        if t != "audit_event"}
    jobs = {j.id: j for j in (await session.scalars(select(Job))).all()}
    assert jobs[ids["below"]].raw_text is None and jobs[ids["below"]].triage == "archived"
    assert jobs[ids["applied_below"]].raw_text == "text I applied with", "a role with an application keeps its text"
    assert jobs[ids["applied_below"]].triage == "below_threshold"
    assert jobs[ids["stale"]].triage == "archived"
    assert jobs[ids["applied"]].triage == "new" and jobs[ids["pinned"]].triage == "new"
    assert {n.dedupe_key for n in await session.scalars(select(Notification))} == {"new"}
    assert not (tmp / "old.bin").exists() and (tmp / "new.bin").exists()
    assert (dirs / "files" / "vault" / "cv.pdf").read_bytes() == b"cv"
    assert run.counts["notifications_deleted"] == 1 and run.counts["temp_files_deleted"] == 1


async def test_a_run_that_would_remove_protected_rows_is_rolled_back(session, dirs, monkeypatch) -> None:
    await seed(session)
    before = await retention.protected_counts(session)

    async def greedy(session, **kwargs):
        await session.execute(text("DELETE FROM contact"))
        return retention.Counter()

    monkeypatch.setattr(retention, "run_ops_retention", greedy)
    with pytest.raises(retention.ProtectedDataError, match="contact"):
        await retention.run_all(session)

    after = await retention.protected_counts(session)
    assert after["contact"] == before["contact"] == 1, "the delete was rolled back"
    assert all(after[t] >= before[t] for t in before)
    run = await session.scalar(select(Run).where(Run.kind == RunKind.retention))
    assert run is not None and run.status == RunStatus.failed and "protected" in (run.error or "")


async def test_dry_run_reports_but_changes_nothing(session, dirs) -> None:
    ids = await seed(session)
    session.add(old := Notification(kind="x", title="old", dedupe_key="old"))
    await session.commit()
    await age(session, Notification, old.id, 120)
    run = await retention.run_all(session, dry_run=True)
    assert run.counts["notifications_deleted"] == 1 and run.counts["text_dropped"] == 2 - 1
    job = await session.get(Job, ids["below"])
    assert job.raw_text == "full posting text" and job.triage == "below_threshold"
    assert await session.scalar(select(Notification).where(Notification.dedupe_key == "old")) is not None


async def test_notification_age_is_a_setting(session, dirs) -> None:
    session.add(note := Notification(kind="x", title="forty-five days", dedupe_key="k"))
    await session.commit()
    await age(session, Notification, note.id, 45)
    await retention.run_all(session)
    assert await session.scalar(select(Notification)) is not None, "default 90 days keeps it"
    await settings_service.set_many(session, {"retention.notifications_days": 30}, actor="test")
    await session.commit()
    await retention.run_all(session)
    assert await session.scalar(select(Notification)) is None


async def test_old_backups_are_pruned_to_the_keep_setting(session, dirs) -> None:
    from app.ops import backup

    directory = get_config().backup_dir
    directory.mkdir()
    for i in range(3):
        stamp = datetime(2026, 11, 20 + i, tzinfo=UTC)
        name = f"nchito-{stamp.strftime('%Y%m%dT%H%M%SZ')}.backup"
        (directory / name).write_bytes(b"x")
        info = backup.BackupInfo(id=name.removesuffix(".backup"), path=str(directory / name), created_at=stamp,
                                 size_bytes=1, sha256="0")
        (directory / (name + ".json")).write_text(__import__("json").dumps(info.to_json()), encoding="utf-8")
    await settings_service.set_many(session, {"backups.keep": 2}, actor="test")
    await session.commit()
    run = await retention.run_all(session)
    assert run.counts["backups_pruned"] == 1
    assert [i.id for i in backup.list_backups(directory)] == ["nchito-20261122T000000Z", "nchito-20261121T000000Z"]


def test_protected_tables_include_the_duplicate_protection_and_audit_history() -> None:
    for table in ("application", "dispatch_attempt", "audit_event", "submit_permit", "application_packet",
                  "job_sighting", "ledger_entry"):
        assert table in retention.PROTECTED_TABLES


async def test_retention_leaves_applications_untouched(session, dirs) -> None:
    ids = await seed(session)
    await retention.run_all(session)
    apps = (await session.scalars(select(Application))).all()
    assert len(apps) == 2 and all(a.stage == Stage.submitted for a in apps)
    assert await session.get(Job, ids["applied"]) is not None
