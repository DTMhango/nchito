"""Notification pipeline: collection, idempotency, quiet hours, wording, failures, scrubbing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.connect.notifier import (
    DeliveryError,
    OutboundMessage,
    register_notifier_factory,
    unregister_notifier_factory,
)
from app.core.settings import service as settings_service
from app.models.applications import PendingActionType
from app.models.platform import AuditEvent, Notification
from app.ops import notifications
from tests.tracking.helpers import make_pending

# 12:00 UTC is 14:00 in Africa/Lusaka (UTC+2): outside the default quiet hours (21:00 to 07:00).
# Rows get the database's real clock as created_at, so the fixed times of day are on today's real date.
TODAY = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
NOON = TODAY + timedelta(hours=12)
LATE = TODAY + timedelta(hours=20, minutes=30)  # 22:30 in Lusaka: inside the default quiet hours
EARLY = TODAY + timedelta(hours=4)  # 06:00 in Lusaka: still inside


class FakeNotifier:
    channel = "telegram"

    def __init__(self, fail: DeliveryError | None = None) -> None:
        self.sent: list[OutboundMessage] = []
        self.fail = fail

    async def send(self, message: OutboundMessage) -> None:
        if self.fail:
            raise self.fail
        self.sent.append(message)


@pytest.fixture
def telegram():
    fake = FakeNotifier()

    async def factory(session):
        return fake

    register_notifier_factory("telegram", factory)
    yield fake
    from app.connect import records

    register_notifier_factory("telegram", records.telegram_factory)  # restore the real factory


async def configure(session, **changes) -> None:
    base = {"notifications.channels": ["telegram"]}
    await settings_service.set_many(session, {**base, **changes}, actor="test")
    await session.commit()


async def rows(session) -> list[Notification]:
    return list((await session.scalars(select(Notification).order_by(Notification.created_at))).all())


async def test_notify_is_idempotent_per_key(session) -> None:
    first = await notifications.notify(session, kind="pending_action", key="k1", title="One")
    again = await notifications.notify(session, kind="pending_action", key="k1", title="One again")
    await session.commit()
    assert first is not None and again is None
    assert [n.title for n in await rows(session)] == ["One"]


async def test_nothing_is_collected_until_a_channel_is_configured(session) -> None:
    await make_pending(session, title="Sign in at Acme")
    await session.commit()
    assert (await notifications.collect(session, NOON)).created == 0
    assert await rows(session) == []


async def test_collect_then_deliver_sends_once_even_if_run_repeatedly(session, telegram) -> None:
    pa = await make_pending(session, title="Sign in at Acme", type_=PendingActionType.sign_in)
    await configure(session)
    for _ in range(3):
        await notifications.collect(session, NOON)
        await session.commit()
        await notifications.deliver_due(session, NOON)
    assert len(telegram.sent) == 1
    message = telegram.sent[0]
    assert message.event_id == f"pending:{pa.id}"
    assert message.title == "Needs you: Sign in at Acme"
    assert [b.label for b in message.buttons] == ["I've signed in, continue", "Open"]
    assert message.link and message.link.endswith(f"/today?action={pa.id}")
    row = (await rows(session))[0]
    assert row.channels_sent == ["telegram"]


async def test_approve_actions_get_an_approve_deep_link_not_a_callback(session, telegram) -> None:
    await make_pending(session, title="Approve application to Acme", type_=PendingActionType.approve)
    await configure(session)
    await notifications.collect(session, NOON)
    await session.commit()
    await notifications.deliver_due(session, NOON)
    buttons = telegram.sent[0].buttons
    assert [b.label for b in buttons] == ["Approve", "Open"]
    assert buttons[0].url.endswith("&intent=approve") and buttons[0].url.startswith("http")


async def test_events_not_enabled_do_not_notify(session, telegram) -> None:
    await make_pending(session, title="Sign in")
    await configure(session, **{"notifications.events": ["run_failed"]})
    await notifications.collect(session, NOON)
    await session.commit()
    assert await rows(session) == []
    # a row made by another module for a disabled kind is skipped, not sent
    await notifications.notify(session, kind="pending_action_stale", key="s1", title="Old thing")
    await session.commit()
    await notifications.deliver_due(session, NOON)
    assert telegram.sent == []
    assert (await rows(session))[0].payload["_delivery"]["state"] == "skipped"


@pytest.mark.parametrize(("now", "start", "end", "expect_sent"), [
    (NOON, None, None, True),  # 14:00, default window 21:00 to 07:00
    (LATE, None, None, False),  # 22:30
    (EARLY, None, None, False),  # 06:00
    (LATE, "23:00", "05:00", True),  # another value: 22:30 is before a 23:00 start
    (NOON, "13:00", "15:00", False),  # a daytime window that does not wrap midnight
    (NOON, "08:00", "08:00", True),  # equal start and end means no quiet hours
])
async def test_quiet_hours_at_default_and_other_values(session, telegram, now, start, end, expect_sent) -> None:
    changes = {}
    if start:
        changes = {"notifications.quiet_hours_start": start, "notifications.quiet_hours_end": end}
    await configure(session, **changes)
    await notifications.notify(session, kind="pending_action", key="q", title="Sign in")
    await session.commit()
    await notifications.deliver_due(session, now)
    assert bool(telegram.sent) is expect_sent
    state = (await rows(session))[0].payload.get("_delivery", {}).get("state")
    assert state == ("done" if expect_sent else "pending")


async def test_a_held_message_goes_out_when_quiet_hours_end(session, telegram) -> None:
    await configure(session)
    await notifications.notify(session, kind="pending_action", key="q", title="Sign in")
    await session.commit()
    await notifications.deliver_due(session, LATE)
    assert telegram.sent == []
    await notifications.deliver_due(session, LATE + timedelta(hours=10))  # 08:30 next morning in Lusaka
    assert len(telegram.sent) == 1


async def test_quiet_hours_can_be_switched_off(session, telegram) -> None:
    await configure(session, **{"notifications.quiet_hours_enabled": False})
    await notifications.notify(session, kind="pending_action", key="q", title="Sign in")
    await session.commit()
    await notifications.deliver_due(session, LATE)
    assert len(telegram.sent) == 1


async def test_delivery_failure_never_raises_and_retries_with_backoff_then_gives_up(session, telegram) -> None:
    telegram.fail = DeliveryError("telegram answered 502: bad gateway")
    await configure(session, **{"notifications.retry_attempts": 3, "notifications.retry_minutes": 10})
    await notifications.notify(session, kind="pending_action", key="f", title="Sign in")
    await session.commit()

    result = await notifications.deliver_due(session, NOON)  # attempt 1
    assert result.failed == 1
    state = (await rows(session))[0].payload["_delivery"]
    assert state["state"] == "pending" and state["attempts"] == 1
    assert datetime.fromisoformat(state["next_attempt_at"]) == NOON + timedelta(minutes=10)

    await notifications.deliver_due(session, NOON + timedelta(minutes=5))  # too early: not tried
    assert (await rows(session))[0].payload["_delivery"]["attempts"] == 1

    await notifications.deliver_due(session, NOON + timedelta(minutes=10))  # attempt 2, next wait doubles
    state = (await rows(session))[0].payload["_delivery"]
    assert state["attempts"] == 2
    assert datetime.fromisoformat(state["next_attempt_at"]) == NOON + timedelta(minutes=30)

    await notifications.deliver_due(session, NOON + timedelta(minutes=31))  # attempt 3: gives up
    assert (await rows(session))[0].payload["_delivery"]["state"] == "gave_up"
    audited = await session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "notification.delivery_failed"))
    assert audited == 1

    telegram.fail = None
    await notifications.deliver_due(session, NOON + timedelta(hours=2))
    assert telegram.sent == [], "a message that was given up on is not sent later"


async def test_a_crashing_notifier_does_not_break_delivery(session) -> None:
    class Boom:
        channel = "telegram"

        async def send(self, message):
            raise RuntimeError("secret-token-123 leaked in an exception")

    async def factory(s):
        return Boom()

    register_notifier_factory("telegram", factory)
    try:
        await configure(session)
        await notifications.notify(session, kind="pending_action", key="b", title="Sign in")
        await session.commit()
        result = await notifications.deliver_due(session, NOON)
        assert result.failed == 1
        stored = str((await rows(session))[0].payload)
        assert "secret-token-123" not in stored, "exception text is never stored"
    finally:
        from app.connect import records

        register_notifier_factory("telegram", records.telegram_factory)


async def test_unconnected_channel_is_recorded_not_raised(session) -> None:
    unregister_notifier_factory("webhook")
    try:
        await configure(session, **{"notifications.channels": ["webhook"]})
        await notifications.notify(session, kind="pending_action", key="u", title="Sign in")
        await session.commit()
        result = await notifications.deliver_due(session, NOON)
        assert result.failed == 1
        assert (await rows(session))[0].payload["_delivery"]["errors"] == {"webhook": "not connected"}
    finally:
        from app.connect import records

        register_notifier_factory("webhook", records.webhook_factory)


async def test_messages_carry_no_payload_and_secrets_are_masked(session, telegram) -> None:
    await configure(session)
    await notifications.notify(
        session, kind="pending_action", key="s", title="Use key sk-ant-abcdefghijklmnop to sign in",
        body="Token 123456789:AAFabcdefghijklmnopqrstuvwxyz and Bearer abc.def",
        payload={"api_key": "sk-secret-payload", "answer": "ZMW 90000"})
    await session.commit()
    await notifications.deliver_due(session, NOON)
    message = telegram.sent[0]
    text = f"{message.title} {message.body} {message.link}"
    assert "sk-ant" not in text and "AAFabc" not in text and "Bearer abc" not in text
    assert "sk-secret-payload" not in text and "90000" not in text
    assert "[hidden]" in text


async def test_generic_detail_level_names_no_roles_or_employers(session, telegram) -> None:
    await configure(session, **{"notifications.detail_level": "generic"})
    await notifications.notify(session, kind="pending_action", key="g", title="Sign in at Acme Ltd",
                               body="Sign in", link="/today?action=1")
    await session.commit()
    await notifications.deliver_due(session, NOON)
    message = telegram.sent[0]
    assert "Acme" not in message.title and message.body is None
    assert message.title == "Needs you: Something needs you"


async def test_wording_is_a_setting_with_a_second_value(session, telegram) -> None:
    await configure(session, **{"notifications.needs_you_title": "{app_name} | {title}"})
    await notifications.notify(session, kind="pending_action", key="w", title="Sign in")
    await session.commit()
    await notifications.deliver_due(session, NOON)
    assert telegram.sent[0].title == "Nchito | Sign in"


async def test_old_events_outside_the_lookback_are_not_sent(session, telegram) -> None:
    await configure(session, **{"notifications.lookback_hours": 24})
    await notifications.notify(session, kind="pending_action", key="old", title="Sign in")
    await session.commit()
    await notifications.deliver_due(session, NOON + timedelta(days=3))
    assert telegram.sent == []


async def test_two_deliveries_at_once_send_a_message_only_once(session, telegram) -> None:
    from app.core.db import get_sessionmaker

    await configure(session)
    await notifications.notify(session, kind="pending_action", key="race", title="Sign in")
    await session.commit()
    import asyncio

    async def run():
        async with get_sessionmaker()() as s:
            return await notifications.deliver_due(s, NOON)

    await asyncio.gather(run(), run())
    assert len(telegram.sent) == 1


class Crash(BaseException):
    """The process dying mid-send (not an Exception: nothing in the delivery code can catch it)."""


async def test_a_crash_between_send_and_commit_never_sends_twice(session, telegram) -> None:
    await configure(session)
    await notifications.notify(session, kind="pending_action", key="crash", title="Sign in")
    await session.commit()

    async def die(message):
        telegram.sent.append(message)  # the provider accepted it ...
        raise Crash  # ... and the process died before the result was saved

    telegram.send = die  # type: ignore[method-assign]
    with pytest.raises(Crash):
        await notifications.deliver_due(session, NOON)
    await session.rollback()
    row = (await rows(session))[0]
    assert row.channels_sent == [] and "telegram" in row.payload["_delivery"]["sending"]
    assert len(telegram.sent) == 1

    # A restart soon after: another worker may still be sending, so it waits and sends nothing.
    async def forbidden(message):
        raise AssertionError("resent")

    telegram.send = forbidden  # type: ignore[method-assign]
    held = await notifications.deliver_due(session, NOON + timedelta(seconds=30))
    assert held.held == 1 and held.sent == 0
    # Later the outcome is still unknown: marked uncertain, audited, never resent.
    later = NOON + timedelta(hours=1)
    await notifications.deliver_due(session, later)
    row = (await rows(session))[0]
    state = row.payload["_delivery"]
    assert state["state"] == "done" and "telegram" in state["uncertain"] and row.channels_sent == []
    assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "notification.delivery_uncertain")) == 1
    await notifications.deliver_due(session, later + timedelta(hours=1))
    assert len(telegram.sent) == 1
