"""The one-minute scheduler tick.

Reads enabled ``Schedule`` rows and turns due fire times into ``Run`` rows plus queued jobs.

Rules (DESIGN.md 3, 14):
- Cron expressions are evaluated in the schedule's time zone (default ``general.timezone``).
- **Overlap prevention:** a schedule whose previous run is still queued or running does not
  start another; the skipped fire is recorded as a ``skipped`` run so the owner can see it.
- **One catch-up:** after downtime that spans several fire times, at most one run is enqueued
  (``trigger="catch_up"``) when ``schedule.missed_run`` is ``catch_up_once``; with ``skip``
  nothing runs until the next fire time.
- A new schedule (no ``next_run_at``) is armed for its next fire time; it does not fire at once.
- The job is deferred before the transaction commits: if deferring fails nothing is recorded;
  if the commit fails the job finds no run and exits.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import Clock
from app.core.settings import service as settings_service
from app.models.search import Run, RunStatus, Schedule

ACTIVE_STATUSES = (RunStatus.queued, RunStatus.running)
# A fire time this close to "now" is on time, not missed (the tick may run a little late).
ON_TIME_GRACE_SECONDS = 150

Enqueue = Callable[[Run], Awaitable[None]]


@dataclass
class TickResult:
    enqueued: list[Run] = field(default_factory=list)
    skipped_overlap: list[Schedule] = field(default_factory=list)
    skipped_missed: list[Schedule] = field(default_factory=list)
    armed: list[Schedule] = field(default_factory=list)


def next_fire(cron: str, tz: ZoneInfo, after: datetime) -> datetime:
    """First fire time strictly after ``after`` (aware UTC in, aware UTC out)."""
    local = after.astimezone(tz)
    nxt: datetime = croniter(cron, local).get_next(datetime)
    return nxt.astimezone(ZoneInfo("UTC"))


def missed_fire_times(cron: str, tz: ZoneInfo, first_due: datetime, now: datetime) -> list[datetime]:
    """All fire times from ``first_due`` up to and including ``now``."""
    times = [first_due]
    cursor = first_due
    while True:
        cursor = next_fire(cron, tz, cursor)
        if cursor > now:
            return times
        times.append(cursor)
        if len(times) > 10_000:  # pathological cron after very long downtime
            return times


async def _has_active_run(session: AsyncSession, schedule: Schedule) -> bool:
    found = await session.scalar(
        select(Run.id).where(Run.schedule_id == schedule.id, Run.status.in_(ACTIVE_STATUSES)).limit(1)
    )
    return found is not None


async def tick(session: AsyncSession, clock: Clock, enqueue: Enqueue) -> TickResult:
    """Process every enabled schedule once. The caller commits."""
    now = clock.now()
    settings = await settings_service.values(session)
    default_tz = ZoneInfo(settings["general.timezone"])
    missed_policy: str = settings["schedule.missed_run"]
    result = TickResult()

    schedules = (
        await session.scalars(
            select(Schedule).where(Schedule.enabled.is_(True)).order_by(Schedule.created_at)
            .with_for_update(skip_locked=True)
        )
    ).all()

    for schedule in schedules:
        tz = ZoneInfo(schedule.timezone) if schedule.timezone else default_tz
        if schedule.next_run_at is None:
            schedule.next_run_at = next_fire(schedule.cron, tz, now)
            result.armed.append(schedule)
            continue
        if schedule.next_run_at > now:
            continue

        fires = missed_fire_times(schedule.cron, tz, schedule.next_run_at, now)
        latest = fires[-1]
        late = len(fires) > 1 or (now - latest).total_seconds() > ON_TIME_GRACE_SECONDS
        schedule.next_run_at = next_fire(schedule.cron, tz, now)

        if late and missed_policy == "skip":
            result.skipped_missed.append(schedule)
            await audit.record(session, actor="system", action="schedule.missed_skipped", subject_type="schedule",
                               subject_id=schedule.id, detail={"missed": len(fires)})
            continue

        if await _has_active_run(session, schedule):
            session.add(Run(kind=schedule.kind, trigger="schedule", campaign_id=schedule.campaign_id,
                            schedule_id=schedule.id, scheduled_for=latest, dry_run=schedule.dry_run,
                            status=RunStatus.skipped, error="previous run still active"))
            result.skipped_overlap.append(schedule)
            continue

        run = Run(kind=schedule.kind, trigger="catch_up" if late else "schedule", campaign_id=schedule.campaign_id,
                  schedule_id=schedule.id, scheduled_for=latest, dry_run=schedule.dry_run, status=RunStatus.queued)
        session.add(run)
        await session.flush()
        await enqueue(run)
        schedule.last_enqueued_at = now
        schedule.last_run_id = run.id
        result.enqueued.append(run)

    await session.flush()
    return result
