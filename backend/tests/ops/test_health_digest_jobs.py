"""Health (stale worker, overdue backup, alerts), the digest, and the scheduled ops tick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.connect.notifier import OutboundMessage, register_notifier_factory
from app.core.settings import service as settings_service
from app.models.applications import Stage
from app.models.platform import Connection, ConnectionProvider, Notification, Owner, WorkerHeartbeat
from app.models.search import (
    Assessment,
    AssessmentState,
    Campaign,
    CampaignStatus,
    Run,
    RunKind,
    RunStatus,
)
from app.ops import digest, health, jobs, notifications
from tests.tracking.helpers import make_app, make_job, make_pending

NOW = datetime.now(UTC).replace(microsecond=0)


async def beat(session, age_seconds: float, name: str = "w1") -> None:
    session.add(WorkerHeartbeat(worker_name=name, beat_at=NOW - timedelta(seconds=age_seconds), version="t"))
    await session.commit()


async def run_ok(session, kind: RunKind, hours_ago: float, status: RunStatus = RunStatus.succeeded) -> None:
    finished = NOW - timedelta(hours=hours_ago)
    session.add(Run(kind=kind, trigger="schedule", status=status, started_at=finished, finished_at=finished))
    await session.commit()


def comp(report: health.DetailedHealth, name: str) -> health.Component:
    return next(c for c in report.components if c.name == name)


async def test_health_reports_a_stale_worker(session) -> None:
    await beat(session, age_seconds=600)  # default stale threshold is 180 s
    report = await health.detailed(session, NOW)
    worker = comp(report, "worker")
    assert worker.status == "down" and "no heartbeat" in (worker.detail or "")
    assert report.status == "degraded"
    assert report.workers and not report.workers[0].ok


async def test_health_with_a_fresh_worker_and_no_worker_at_all(session) -> None:
    assert comp(await health.detailed(session, NOW), "worker").detail == "no worker has reported"
    await beat(session, age_seconds=5)
    report = await health.detailed(session, NOW)
    assert comp(report, "worker").status == "ok" and comp(report, "database").status == "ok"


async def test_backup_and_sweep_age_use_settings_and_the_setup_grace(session) -> None:
    session.add(Owner(email="o@example.com", display_name="O", password_hash="x"))
    await session.commit()
    await beat(session, 5)
    # a brand new instance has not missed a backup yet
    assert comp(await health.detailed(session, NOW), "backup").status == "unknown"
    await run_ok(session, RunKind.backup, hours_ago=40, status=RunStatus.succeeded)
    stale = comp(await health.detailed(session, NOW), "backup")
    assert stale.status == "warn" and "40 h ago" in (stale.detail or "")
    await settings_service.set_many(session, {"health.backup_stale_hours": 72}, actor="test")
    await session.commit()
    assert comp(await health.detailed(session, NOW), "backup").status == "ok"
    await run_ok(session, RunKind.sweep, hours_ago=2)
    sweep = comp(await health.detailed(session, NOW), "sweep")
    assert sweep.status == "ok" and sweep.value == 2.0


async def test_a_failed_run_does_not_count_as_the_last_successful_backup(session) -> None:
    await run_ok(session, RunKind.backup, hours_ago=1, status=RunStatus.failed)
    assert await health.last_success(session, RunKind.backup) is None


async def test_disk_queue_and_connections_are_reported(session, tmp_path, monkeypatch) -> None:
    from app.core.config import get_config

    monkeypatch.setattr(get_config(), "files_dir", tmp_path)
    session.add(Connection(provider=ConnectionProvider.telegram, label="Bot", config={}, health="failing",
                           scopes_granted=[]))
    session.add(Connection(provider=ConnectionProvider.webhook, label="Hook", config={}, health="ok",
                           scopes_granted=[]))
    await session.execute(text(
        "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status) "
        "VALUES ('runs', 'run_pipeline', '{}', 'todo'), ('runs', 'run_pipeline', '{}', 'todo')"))
    await session.commit()
    report = await health.detailed(session, NOW)
    assert report.queue.waiting == 2
    assert comp(report, "disk").value and comp(report, "disk").status == "ok"
    assert comp(report, "connections").status == "warn" and "telegram" in (comp(report, "connections").detail or "")
    assert {c.provider: c.health for c in report.connections} == {"telegram": "failing", "webhook": "ok"}
    await settings_service.set_many(session, {"health.disk_min_free_mb": 10_000_000}, actor="test")
    await session.commit()
    assert comp(await health.detailed(session, NOW), "disk").status == "warn"


async def test_one_alert_per_persistent_failure_and_one_on_recovery(session) -> None:
    await beat(session, 600)  # stale worker
    first = await health.alert_transitions(session, await health.detailed(session, NOW))
    await session.commit()
    again = await health.alert_transitions(session, await health.detailed(session, NOW + timedelta(minutes=5)))
    await session.commit()
    assert len(first) == 1 and "worker:failing" in first[0] and again == []

    await session.execute(text("DELETE FROM worker_heartbeat"))
    await beat(session, 1)
    recovered = await health.alert_transitions(session, await health.detailed(session, NOW + timedelta(minutes=10)))
    await session.commit()
    assert len(recovered) == 1 and "worker:recovered" in recovered[0]
    quiet = await health.alert_transitions(session, await health.detailed(session, NOW + timedelta(minutes=15)))
    assert quiet == []
    titles = [n.title for n in await session.scalars(select(Notification).order_by(Notification.created_at))]
    assert titles == ["Worker needs attention", "Worker is back to normal"]


async def test_a_healthy_system_raises_no_alerts(session) -> None:
    await beat(session, 1)
    assert await health.alert_transitions(session, await health.detailed(session, NOW)) == []


async def test_live_ready_and_detail_endpoints(owner_client, session) -> None:
    assert (await owner_client.get("/api/health/live")).json() == {"alive": True}
    ready = await owner_client.get("/api/health/ready")
    assert ready.status_code == 200 and ready.json() == {"ready": True, "database": True, "migrated": True}
    await beat(session, 1)
    detail = await owner_client.get("/api/health/detail")
    assert detail.status_code == 200
    names = {c["name"] for c in detail.json()["components"]}
    assert {"database", "worker", "sweep", "backup", "disk", "connections"} <= names
    assert set(detail.json()["queue"]) == {"waiting", "running", "failed"}


async def test_detail_requires_the_owner(client) -> None:
    assert (await client.get("/api/health/detail")).status_code == 401
    assert (await client.get("/api/health/live")).status_code == 200


# ----- digest ------------------------------------------------------------------------------------


async def seed_digest_data(session) -> None:
    job = await make_job(session, "Senior Actuary", "Acme Ltd")
    quiet = await make_job(session, "Intern", "Beta Ltd")
    campaign = Campaign(name="C", status=CampaignStatus.active)
    session.add(campaign)
    await session.flush()
    session.add(Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored, score=88))
    session.add(Assessment(job_id=quiet.id, campaign_id=campaign.id, state=AssessmentState.scored, score=20))
    await make_pending(session, title="Sign in at Acme")
    sent_job = await make_job(session, "Data Analyst", "Gamma Ltd")
    await make_app(session, sent_job, Stage.submitted, applied_at=NOW - timedelta(hours=3))
    await session.commit()


async def test_render_digest_lists_matches_needs_you_sent_and_spend(session) -> None:
    await seed_digest_data(session)
    result = await digest.render_digest(session, since=NOW - timedelta(days=1), until=NOW + timedelta(minutes=1))
    assert result.counts["matches"] == 1 and result.counts["needs_you"] == 1 and result.counts["sent"] == 1
    assert "88  Senior Actuary, Acme Ltd" in result.body and "Intern" not in result.body
    assert "Sign in at Acme" in result.body and "Data Analyst, Gamma Ltd" in result.body
    assert "AI spend this period: 0.00 USD" in result.body
    assert result.title.startswith("Nchito digest for ") and not result.is_empty


async def test_generic_detail_level_leaves_names_out_of_the_digest(session) -> None:
    await seed_digest_data(session)
    await settings_service.set_many(session, {"notifications.detail_level": "generic"}, actor="test")
    await session.commit()
    result = await digest.render_digest(session, since=NOW - timedelta(days=1), until=NOW + timedelta(minutes=1))
    assert "Acme" not in result.body and "Needs you: 1" in result.body


async def test_digest_list_length_is_a_setting(session) -> None:
    for i in range(4):
        await make_pending(session, title=f"Action {i}")
    await session.commit()
    two = await digest.render_digest(session, since=NOW - timedelta(days=1), until=NOW,
                                     values={**await settings_service.values(session),
                                             "notifications.digest_max_items": 2})
    assert two.body.count("  Action") == 2 and "and 2 more" in two.body


async def test_empty_digest_is_skipped_unless_the_setting_says_otherwise(session) -> None:
    await settings_service.set_many(session, {"notifications.channels": ["telegram"]}, actor="test")
    await run_ok(session, RunKind.sweep, hours_ago=0.1)
    assert not await digest.send_digest_if_due(session, NOW)
    await settings_service.set_many(session, {"notifications.digest_skip_empty": False}, actor="test")
    await session.commit()
    assert await digest.send_digest_if_due(session, NOW)


async def test_digest_after_sweep_is_sent_once_per_day_through_the_notifier(session) -> None:
    await seed_digest_data(session)
    await settings_service.set_many(session, {"notifications.channels": ["telegram"],
                                              "notifications.quiet_hours_enabled": False}, actor="test")
    await session.commit()
    soon = datetime.now(UTC) + timedelta(minutes=1)  # rows carry the real clock
    sent: list[OutboundMessage] = []

    class Capture:
        channel = "telegram"

        async def send(self, message: OutboundMessage) -> None:
            sent.append(message)

    async def factory(s):
        return Capture()

    register_notifier_factory("telegram", factory)
    try:
        assert not await digest.send_digest_if_due(session, soon), "no sweep has run yet today"
        await run_ok(session, RunKind.sweep, hours_ago=0)
        assert await digest.send_digest_if_due(session, soon)
        await session.commit()
        assert not await digest.send_digest_if_due(session, soon + timedelta(minutes=1)), "once per day"
        await notifications.deliver_due(session, soon)
        await notifications.deliver_due(session, soon)
    finally:
        from app.connect import records

        register_notifier_factory("telegram", records.telegram_factory)
    assert len(sent) == 1 and sent[0].kind == "digest" and "Senior Actuary" in (sent[0].body or "")
    assert sent[0].title.startswith("Nchito digest for")


async def test_morning_digest_waits_for_its_time_and_the_time_is_a_setting(session) -> None:
    tz = ZoneInfo("Africa/Lusaka")
    day = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    at_0700, at_0800 = (day + timedelta(hours=7)).astimezone(UTC), (day + timedelta(hours=8)).astimezone(UTC)
    await settings_service.set_many(session, {"notifications.channels": ["telegram"],
                                              "notifications.digest": "morning",
                                              "notifications.digest_skip_empty": False}, actor="test")
    await session.commit()
    values = await settings_service.values(session)
    assert await digest.digest_due(session, at_0700, values) is None, "default time is 07:30"
    assert await digest.digest_due(session, at_0800, values) == day.date().isoformat()
    values["notifications.digest_time"] = "08:15"
    assert await digest.digest_due(session, at_0800, values) is None
    values["notifications.digest"] = "off"
    assert await digest.digest_due(session, at_0800 + timedelta(hours=5), values) is None


# ----- the tick ----------------------------------------------------------------------------------


def test_cron_due_uses_the_owners_time_zone() -> None:
    tz = ZoneInfo("Africa/Lusaka")  # UTC+2: 02:00 local is 00:00 UTC
    now = datetime(2026, 11, 26, 0, 30, tzinfo=UTC)
    assert jobs.cron_due("0 2 * * *", tz, now, datetime(2026, 11, 25, 0, 5, tzinfo=UTC))
    assert not jobs.cron_due("0 2 * * *", tz, now, datetime(2026, 11, 26, 0, 5, tzinfo=UTC)), "already ran at 02:00"
    assert not jobs.cron_due("0 2 * * *", tz, now - timedelta(hours=1), datetime(2026, 11, 25, 0, 5, tzinfo=UTC))
    assert jobs.cron_due("30 3 * * *", tz, datetime(2026, 11, 26, 2, 0, tzinfo=UTC),
                         datetime(2026, 11, 25, 2, 0, tzinfo=UTC)), "another cron value"
    assert not jobs.cron_due("0 2 * * *", tz, now, None)


async def test_tick_runs_every_step_and_isolates_a_failing_one(session, monkeypatch) -> None:
    from app.core.db import get_sessionmaker

    await settings_service.set_many(session, {"notifications.channels": ["telegram"],
                                              "notifications.quiet_hours_enabled": False}, actor="test")
    pa = await make_pending(session, title="Sign in at Acme")
    await session.commit()
    delivered: list[OutboundMessage] = []

    class Capture:
        channel = "telegram"

        async def send(self, message: OutboundMessage) -> None:
            delivered.append(message)

    async def factory(s):
        return Capture()

    async def broken(*a, **k):
        raise RuntimeError("health exploded")

    register_notifier_factory("telegram", factory)
    monkeypatch.setattr(health, "detailed", broken)
    try:
        done = await jobs.tick(get_sessionmaker(), datetime.now(UTC))
    finally:
        from app.connect import records

        register_notifier_factory("telegram", records.telegram_factory)
    assert done["health"] == "error", "a failing step is isolated"
    assert done["collect"] == 1 and done["deliver"] == 1
    assert [m.event_id for m in delivered] == [f"pending:{pa.id}"]
    assert await session.scalar(select(func.count()).select_from(Notification)) == 1
