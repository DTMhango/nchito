"""The automatic follow-up: only the plain no-reply follow-up, to an address the application went to, within
caps and quiet hours, never after any reply; each condition is a gate (checked when queued and at dispatch).
Also the due list (reminder, snooze, not needed) and pausing a campaign until a date."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.apply import dispatch
from app.models.applications import (
    Application,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
)
from app.models.followups import FollowupDue, OutboundMessage
from app.models.search import Campaign, CampaignStatus
from app.pipeline.followups import campaigns, drafting, due, sending
from tests.followups.helpers import (
    AFTER_DELAY,
    PLAIN,
    SENT_TO,
    link_thread,
    llm,
    maker,
    message_attempts,
    sent_app,
    set_values,
)

DUE = AFTER_DELAY + timedelta(days=11)  # past the default 10 days for "submitted"; 13:00 in Lusaka
QUIET = datetime(2026, 12, 7, 21, 30)  # 23:30 in Lusaka, inside the default quiet hours


async def auto_message(app_id, *, kind="follow_up", to=None, now=DUE):
    """A message drafted and approved by the automatic path (``to`` overrides recipients)."""
    async with maker()() as s:
        app = await s.get(Application, app_id)
        msg = await drafting.create(s, llm(PLAIN), app, kind, actor=sending.AUTO_ACTOR, automatic=True, now=now)
        if to is not None:
            msg.to, msg.confirmed_recipients = to, to
            await sending.recheck_message(s, msg, now=now)
        await sending.approve(s, msg, actor=sending.AUTO_ACTOR, now=now)
        await s.commit()
        return msg.id


async def gates_for(msg_id, now=DUE) -> dict[str, str]:
    async with maker()() as s:
        msg = await s.get(OutboundMessage, msg_id)
        from app.models.applications import ApplicationPacket

        packet = await s.get(ApplicationPacket, msg.packet_id)
        return {g.gate: g.outcome for g in await sending.message_gates(s, msg, packet, now=now)}


def failing(gates: dict[str, str]) -> set[str]:
    return {k for k, v in gates.items() if v != "pass"}


async def test_the_plain_follow_up_passes_every_gate_when_switched_on(channel):
    await set_values(followups__auto_send=True)
    app_id = await sent_app()
    msg_id = await auto_message(app_id)
    assert failing(await gates_for(msg_id)) == set()


async def test_switched_off_by_default(channel):
    app_id = await sent_app()
    assert failing(await gates_for(await auto_message(app_id))) == {"auto_follow_ups"}


@pytest.mark.parametrize("case", ["reply", "new_address", "daily_cap", "per_app_cap", "quiet_hours", "other_type"])
async def test_no_automatic_follow_up_when_a_condition_fails(channel, case):
    await set_values(followups__auto_send=True)
    app_id = await sent_app()
    now, kwargs = DUE, {}
    if case == "reply":
        await link_thread(app_id)
    if case == "new_address":
        kwargs["to"] = ["someone.else@example.com"]
    if case == "daily_cap":
        await set_values(followups__auto_daily_cap=0)
    if case == "per_app_cap":
        await set_values(followups__max_per_application=0)
    if case == "quiet_hours":
        now = QUIET.replace(tzinfo=DUE.tzinfo)
    if case == "other_type":
        kwargs["kind"] = "thank_you"
    msg_id = await auto_message(app_id, now=now, **kwargs)
    expected = {"reply": "employer_reply", "new_address": "recipient_sent_before", "daily_cap": "followup_cap",
                "per_app_cap": "followup_cap", "quiet_hours": "quiet_hours", "other_type": "plain_follow_up"}[case]
    assert expected in failing(await gates_for(msg_id, now=now))
    async with maker()() as s:
        result = await sending.queue(s, await s.get(OutboundMessage, msg_id), actor=sending.AUTO_ACTOR, now=now)
        await s.commit()
    assert result.status == "denied"


async def test_owner_approved_messages_do_not_need_the_automatic_conditions(channel):
    app_id = await sent_app()
    await link_thread(app_id)  # a reply exists; the owner may still answer it
    async with maker()() as s:
        app = await s.get(Application, app_id)
        msg = await drafting.create(s, llm(PLAIN), app, "info_reply", now=DUE)
        await sending.approve(s, msg, actor="owner", now=DUE)
        await s.commit()
        msg_id = msg.id
    assert failing(await gates_for(msg_id)) == set()


async def test_due_tick_sends_the_follow_up_automatically_once(channel):
    await set_values(followups__auto_send=True)
    app_id = await sent_app()
    async with maker()() as s:
        report = await due.tick(s, llm(PLAIN), now=DUE)
        await s.commit()
    assert report["opened"] == 1 and report["auto_queued"] == 1
    async with maker()() as s:
        tick = await dispatch.tick(s, now=DUE + timedelta(minutes=11))
    assert list(tick.sent.values()) == ["sent"]
    sent = channel.dispatched[-1].packet
    assert sent.message_kind == "follow_up" and sent.email.to == [SENT_TO]
    async with maker()() as s:
        await due.tick(s, llm(PLAIN), now=DUE + timedelta(minutes=12))
        await s.commit()
        row = await s.scalar(select(FollowupDue).where(FollowupDue.application_id == app_id))
        assert row.status == "sent"
    assert len(channel.dispatched) == 2


async def test_a_reply_during_the_send_delay_cancels_the_automatic_follow_up(channel):
    await set_values(followups__auto_send=True)
    app_id = await sent_app()
    async with maker()() as s:
        await due.tick(s, llm(PLAIN), now=DUE)
        await s.commit()
    await link_thread(app_id)
    async with maker()() as s:
        await dispatch.tick(s, now=DUE + timedelta(minutes=11))
    assert len(channel.dispatched) == 1  # only the application itself
    async with maker()() as s:
        msg = await s.scalar(select(OutboundMessage).where(OutboundMessage.application_id == app_id))
    assert [a.status for a in await message_attempts(msg.id)] == [DispatchStatus.cancelled]


async def test_due_list_reminder_snooze_and_not_needed(channel):
    app_id = await sent_app()
    async with maker()() as s:
        assert [i.status for i in await due.due_list(s, now=AFTER_DELAY)] == ["upcoming"]
        report = await due.tick(s, None, now=DUE)
        await s.commit()
    assert report["opened"] == 1
    async with maker()() as s:
        action = await s.scalar(select(PendingAction).where(PendingAction.type == PendingActionType.follow_up))
        assert action.status == PendingStatus.open and action.application_id == app_id
        row = await s.scalar(select(FollowupDue).where(FollowupDue.application_id == app_id))
        await due.snooze(s, row, actor="owner", now=DUE)
        assert row.status == "snoozed" and row.snoozed_until > DUE
        await s.commit()
    async with maker()() as s:
        await due.tick(s, None, now=DUE + timedelta(days=4))  # snooze (3 days) over: due again
        row = await s.scalar(select(FollowupDue).where(FollowupDue.application_id == app_id))
        assert row.status == "due"
        await due.not_needed(s, row, actor="owner", now=DUE + timedelta(days=4))
        await s.commit()
        action = await s.get(PendingAction, row.pending_action_id)
        assert action.status == PendingStatus.resolved


async def test_campaign_paused_until_a_date_sends_nothing_then_resumes_on_the_date(channel):
    from app.apply import approval, packets
    from tests.apply.helpers import email_draft, setup_app, setup_campaign
    from tests.pipeline.matching.helpers import NOW

    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, now=NOW)
        built = await packets.build(s, app, email_draft(), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)
        result = await dispatch.queue(s, app.id, now=NOW)
        assert result.queued
        campaign.status, campaign.paused_until = CampaignStatus.paused, date(2026, 12, 1)
        await s.commit()
        campaign_id = campaign.id
    async with maker()() as s:
        status = await dispatch.run(s, result.attempt.id, now=NOW + timedelta(minutes=11))
    assert status == DispatchStatus.cancelled and channel.dispatched == []
    async with maker()() as s:
        assert await campaigns.resume_due(s, now=datetime(2026, 11, 30, 12, tzinfo=NOW.tzinfo)) == []
        resumed = await campaigns.resume_due(s, now=datetime(2026, 12, 1, 6, tzinfo=NOW.tzinfo))
        await s.commit()
    assert [c.id for c in resumed] == [campaign_id]
    async with maker()() as s:
        c = await s.get(Campaign, campaign_id)
        assert c.status == CampaignStatus.active and c.paused_until is None
