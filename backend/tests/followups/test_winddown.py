"""The wind-down after accepting an offer (DESIGN.md 18.4): pause before listing, nothing sent by itself,
choices, withdrawal drafted for approval, reopen restores everything paused (never deleted)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.apply import approval, dispatch, packets, winddown
from app.models.applications import (
    Application,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.followups import OutboundMessage, WindDown
from app.models.search import Campaign, CampaignStatus, RunKind, Schedule
from tests.apply.helpers import email_draft, setup_app
from tests.followups.helpers import AFTER_DELAY, PLAIN, llm, maker, sent_app

LATER = AFTER_DELAY + timedelta(days=2)


async def queued_other(campaign_id):
    """A second application, approved and queued (inside its send delay)."""
    async with maker()() as s:
        campaign = await s.get(Campaign, campaign_id)
        _, app = await setup_app(s, campaign, employer="Globex Example", title="BI Analyst", now=LATER)
        built = await packets.build(s, app, email_draft(), actor="owner", now=LATER)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=LATER)
        result = await dispatch.queue(s, app.id, now=LATER)
        assert result.queued, result.reason
        await s.commit()
        return app.id, result.attempt.id


async def test_wind_down_pauses_first_sends_nothing_and_reopen_restores(channel):
    sent_id = await sent_app()
    async with maker()() as s:
        sent = await s.get(Application, sent_id)
        campaign_id = sent.campaign_id
        s.add(Schedule(name="daily", kind=RunKind(next(iter(RunKind)).value), campaign_id=campaign_id,
                       cron="0 6 * * *", enabled=True))
        action = PendingAction(type=PendingActionType.follow_up, application_id=sent_id, title="Follow up",
                               status=PendingStatus.open, detail={})
        s.add(action)
        await s.commit()
        action_id = action.id
    other_id, attempt_id = await queued_other(campaign_id)

    async with maker()() as s:
        wd = await winddown.start(s, actor="owner", reason="took the Initech offer")
        assert await dispatch.is_paused(s)  # paused before anything is listed
        await s.commit()
        attempt = await s.get(DispatchAttempt, attempt_id)
        assert attempt.status == DispatchStatus.cancelled
        view = await winddown.view(s, wd, now=LATER)
        keys = {i.key for i in view.all()}
        assert f"send:{attempt_id}" in keys and f"application:{sent_id}" in keys
        assert f"action:{action_id}" in keys and f"campaign:{campaign_id}" in keys
        assert "submitted" in view.live_applications
    async with maker()() as s:  # the worker runs: nothing goes
        await dispatch.tick(s, now=LATER + timedelta(minutes=30))
    assert len(channel.dispatched) == 1  # only the original application, before the wind-down

    async with maker()() as s:
        wd = await winddown.active(s)
        client = llm(PLAIN)
        await winddown.choose(s, wd, f"application:{sent_id}", "withdraw", actor="owner", client=client, now=LATER)
        await winddown.choose(s, wd, f"campaign:{campaign_id}", "pause", actor="owner", now=LATER)
        await winddown.choose(s, wd, f"action:{action_id}", "pause", actor="owner", now=LATER)
        await s.commit()
        msg = await s.scalar(select(OutboundMessage).where(OutboundMessage.application_id == sent_id))
        assert msg.kind == "withdraw" and msg.status == "draft" and msg.packet_id is None  # for approval only
        assert (await s.get(Campaign, campaign_id)).status == CampaignStatus.paused
        assert not (await s.scalar(select(Schedule).where(Schedule.campaign_id == campaign_id))).enabled
        assert (await s.get(PendingAction, action_id)).snoozed_until is not None
        assert (await s.get(Application, other_id)).stage in (Stage.ready, Stage.applying)
    assert len(channel.dispatched) == 1

    async with maker()() as s:
        wd = await winddown.active(s)
        await winddown.reopen(s, wd, actor="owner", now=LATER)
        await s.commit()
        assert (await s.get(WindDown, wd.id)).status == "reopened"
        assert (await s.get(Campaign, campaign_id)).status == CampaignStatus.paused  # paused, not deleted
        assert (await s.scalar(select(Schedule).where(Schedule.campaign_id == campaign_id))).enabled
        assert (await s.get(PendingAction, action_id)).snoozed_until is None
        assert await dispatch.is_paused(s)  # the owner resumes autopilot deliberately
        text = winddown.summary_text(await winddown.view(s, wd, now=LATER), "Nchito", LATER)
        assert "withdraw" in text and "took the Initech offer" in text


async def test_withdrawing_an_unsent_application_skips_it_without_any_email(channel):
    sent_id = await sent_app()
    async with maker()() as s:
        campaign_id = (await s.get(Application, sent_id)).campaign_id
    other_id, _ = await queued_other(campaign_id)
    async with maker()() as s:
        wd = await winddown.start(s, actor="owner")
        await s.commit()
        view = await winddown.view(s, wd, now=LATER)
        item = next(i for i in view.all() if i.application_id == other_id)
        await winddown.choose(s, wd, item.key, "withdraw", actor="owner", now=LATER)
        await s.commit()
        app = await s.get(Application, other_id)
        assert app.stage == Stage.skipped and app.approved_packet_id is None
        assert await s.scalar(select(OutboundMessage).where(OutboundMessage.application_id == other_id)) is None
