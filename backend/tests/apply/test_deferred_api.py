"""A send postponed by quiet hours says so on the dispatch itself (invented data only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.apply import approval, dispatch, packets
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from tests.apply.helpers import email_draft, setup_app, setup_campaign
from tests.apply.test_dispatch_api import channel  # noqa: F401 (fixture)


async def test_quiet_hours_deferral_is_exposed_until_it_is_sent(owner_client, channel):  # noqa: F811
    now = datetime.now(UTC).replace(hour=10, minute=0, second=0, microsecond=0)  # 12:00 in Lusaka
    async with get_sessionmaker()() as s:
        await settings_service.set_value(s, "automation.quiet_hours_start", "12:05", actor="owner")
        await settings_service.set_value(s, "automation.quiet_hours_end", "13:00", actor="owner")
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, now=now)
        built = await packets.build(s, app, email_draft(), actor="owner", now=now)
        await approval.approve(s, app, packet_version=1, packet_hash=built.packet.content_hash, channel="email",
                               actor="owner", now=now)
        queued = await dispatch.queue(s, app.id, now=now)
        assert queued.queued, queued.reason
        await s.commit()
        attempt_id = queued.attempt.id
        due = now + timedelta(minutes=20)  # 12:20 local: inside quiet hours
        assert await dispatch.run(s, attempt_id, now=due) is None

    listed = (await owner_client.get(f"/api/applications/{app.id}/dispatches")).json()
    assert listed[0]["status"] == "reserved" and listed[0]["deferred_reason"] == "quiet_hours"
    assert listed[0]["deferred_until"].startswith(now.date().isoformat()) and "T11:00" in listed[0]["deferred_until"]
    async with get_sessionmaker()() as s:
        await dispatch.run(s, attempt_id, now=now + timedelta(hours=1, minutes=5))
    listed = (await owner_client.get(f"/api/applications/{app.id}/dispatches")).json()
    assert listed[0]["status"] == "sent" and listed[0]["deferred_reason"] is None
