"""Scheduler tick with a fake clock: arming, on-time fires, overlap prevention, one catch-up."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.clock import FakeClock
from app.core.settings import service
from app.models.search import Run, RunKind, RunStatus, Schedule
from app.worker.scheduler import tick


class Recorder:
    def __init__(self) -> None:
        self.runs: list[Run] = []

    async def __call__(self, run: Run) -> None:
        self.runs.append(run)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def _schedule(session, cron="0 6 * * *", tz=None) -> Schedule:
    s = Schedule(name="Daily sweep", kind=RunKind.sweep, cron=cron, timezone=tz)
    session.add(s)
    await session.flush()
    return s


async def test_new_schedule_is_armed_not_fired(session):
    clock = FakeClock(utc(2026, 11, 26, 3, 0))  # 05:00 in Lusaka (UTC+2)
    s = await _schedule(session)
    rec = Recorder()
    result = await tick(session, clock, rec)
    assert result.armed == [s] and rec.runs == []
    assert s.next_run_at == utc(2026, 11, 26, 4, 0)  # 06:00 Africa/Lusaka


async def test_fires_on_time_once(session):
    clock = FakeClock(utc(2026, 11, 26, 3, 0))
    s = await _schedule(session)
    rec = Recorder()
    await tick(session, clock, rec)
    clock.set(utc(2026, 11, 26, 3, 59))
    await tick(session, clock, rec)
    assert rec.runs == []
    clock.set(utc(2026, 11, 26, 4, 0, 30))
    result = await tick(session, clock, rec)
    assert len(result.enqueued) == 1
    run = rec.runs[0]
    assert run.trigger == "schedule" and run.scheduled_for == utc(2026, 11, 26, 4, 0)
    assert run.status == RunStatus.queued and run.schedule_id == s.id
    assert s.next_run_at == utc(2026, 11, 27, 4, 0)
    clock.advance(minutes=1)
    await tick(session, clock, rec)
    assert len(rec.runs) == 1


async def test_overlap_prevented(session):
    clock = FakeClock(utc(2026, 11, 26, 0, 0))
    s = await _schedule(session, cron="*/15 * * * *")
    rec = Recorder()
    await tick(session, clock, rec)
    clock.set(utc(2026, 11, 26, 0, 15))
    await tick(session, clock, rec)
    assert len(rec.runs) == 1  # still queued
    clock.set(utc(2026, 11, 26, 0, 30))
    result = await tick(session, clock, rec)
    assert result.skipped_overlap == [s] and len(rec.runs) == 1
    skipped = (await session.scalars(select(Run).where(Run.status == RunStatus.skipped))).all()
    assert len(skipped) == 1 and skipped[0].error == "previous run still active"

    rec.runs[0].status = RunStatus.succeeded
    clock.set(utc(2026, 11, 26, 0, 45))
    await tick(session, clock, rec)
    assert len(rec.runs) == 2


async def test_one_catch_up_after_downtime(session):
    clock = FakeClock(utc(2026, 11, 26, 0, 0))
    s = await _schedule(session, cron="0 * * * *")
    rec = Recorder()
    await tick(session, clock, rec)
    clock.set(utc(2026, 11, 26, 5, 20))  # down for five fire times
    result = await tick(session, clock, rec)
    assert len(result.enqueued) == 1
    assert rec.runs[0].trigger == "catch_up"
    assert rec.runs[0].scheduled_for == utc(2026, 11, 26, 5, 0)
    assert s.next_run_at == utc(2026, 11, 26, 6, 0)


async def test_skip_policy_after_downtime(session):
    await service.set_value(session, "schedule.missed_run", "skip", actor="owner")
    clock = FakeClock(utc(2026, 11, 26, 0, 0))
    s = await _schedule(session, cron="0 * * * *")
    rec = Recorder()
    await tick(session, clock, rec)
    clock.set(utc(2026, 11, 26, 5, 20))
    result = await tick(session, clock, rec)
    assert result.skipped_missed == [s] and rec.runs == []
    clock.set(utc(2026, 11, 26, 6, 0, 10))
    await tick(session, clock, rec)
    assert len(rec.runs) == 1 and rec.runs[0].trigger == "schedule"


async def test_disabled_schedule_ignored_and_timezone_override(session):
    clock = FakeClock(utc(2026, 11, 26, 0, 0))
    off = await _schedule(session)
    off.enabled = False
    london = await _schedule(session, tz="Europe/London")
    rec = Recorder()
    await tick(session, clock, rec)
    assert off.next_run_at is None
    assert london.next_run_at == utc(2026, 11, 26, 6, 0)  # 06:00 GMT


async def test_enqueue_failure_records_nothing(session):
    clock = FakeClock(utc(2026, 11, 26, 0, 0))
    await _schedule(session, cron="* * * * *")
    await tick(session, clock, Recorder())
    await session.commit()

    async def broken(run: Run) -> None:
        raise ConnectionError("queue down")

    clock.set(utc(2026, 11, 26, 0, 1))
    try:
        await tick(session, clock, broken)
    except ConnectionError:
        await session.rollback()
    assert (await session.scalars(select(Run))).all() == []
