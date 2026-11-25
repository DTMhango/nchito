"""Health, worker heartbeat, SSE event hub, run task, audit redaction, crypto."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.core import audit, crypto
from app.core.clock import FakeClock, utcnow
from app.core.events import Event, EventHub, publish
from app.models.search import Run, RunKind, RunStatus
from app.pipeline import runs as run_registry
from app.worker.heartbeat import beat
from app.worker.queue import run_pipeline


async def test_health_degraded_without_worker_then_ok(client, session):
    body = (await client.get("/api/health")).json()
    assert body["status"] == "degraded" and body["db"]["ok"] is True and body["worker"]["ok"] is False
    assert body["version"]

    await beat(session, "test-worker", FakeClock(utcnow()))
    await session.commit()
    body = (await client.get("/api/health")).json()
    assert body["status"] == "ok" and body["worker"]["workers"] == 1

    await beat(session, "test-worker", FakeClock(utcnow() - timedelta(hours=1)))
    await session.commit()
    assert (await client.get("/api/health")).json()["worker"]["ok"] is False


async def test_event_hub_hears_committed_events(session):
    hub = EventHub()
    await hub.start()
    try:
        async with hub.subscribe() as queue:
            await publish(session, "settings.changed", {"key": "x"})
            await asyncio.sleep(0.2)
            assert queue.empty()  # not delivered before commit
            await session.commit()
            event = await asyncio.wait_for(queue.get(), timeout=5)
            assert event.type == "settings.changed" and event.data == {"key": "x"}
            assert event.to_sse().startswith("event: settings.changed\ndata: ")
    finally:
        await hub.stop()


async def test_events_endpoint_requires_owner(client):
    assert (await client.get("/api/events")).status_code == 401


@pytest.mark.nodb
def test_slow_subscriber_drops_oldest():
    hub = EventHub(queue_size=2)

    async def scenario() -> list[str]:
        async with hub.subscribe() as q:
            for i in range(3):
                hub.dispatch(Event(type=f"e{i}", data={}, at=""))
            return [q.get_nowait().type, q.get_nowait().type]

    assert asyncio.run(scenario()) == ["e1", "e2"]


async def test_run_without_handler_is_skipped_not_succeeded(session):
    run = Run(kind=RunKind.digest, trigger="manual", status=RunStatus.queued)
    session.add(run)
    await session.commit()
    await run_pipeline.func(run_id=str(run.id))
    await session.refresh(run)
    assert run.status == RunStatus.skipped and "no handler" in run.error


async def test_run_with_handler(session):
    async def handler(s, run: Run) -> RunStatus:
        run.counts = {"found": 3}
        return RunStatus.succeeded

    run_registry.register(RunKind.retention, handler)
    try:
        run = Run(kind=RunKind.retention, trigger="manual", status=RunStatus.queued)
        session.add(run)
        await session.commit()
        await run_pipeline.func(run_id=str(run.id))
        session.expunge_all()
        loaded = await session.get(Run, run.id)
        assert loaded.status == RunStatus.succeeded and loaded.counts == {"found": 3}
        assert loaded.started_at and loaded.finished_at
    finally:
        run_registry.unregister(RunKind.retention)


@pytest.mark.nodb
def test_audit_redacts_secrets():
    assert audit.redact({"api_key": "sk-1", "nested": [{"password": "p", "ok": 1}], "note": "fine"}) == {
        "api_key": "***", "nested": [{"password": "***", "ok": 1}], "note": "fine"}


@pytest.mark.nodb
def test_crypto_round_trip_and_mask():
    token = crypto.encrypt("refresh-token-value")
    assert token != "refresh-token-value"
    assert crypto.decrypt(token) == "refresh-token-value"
    assert crypto.mask("sk-abcdef123456") == "********3456"
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt("not-a-token")
