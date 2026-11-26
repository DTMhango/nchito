"""Follow-up due reminders and the calendar's after-interview follow-up are the same thing: whichever comes
first, the owner gets one open 'follow up with the employer' action (so one notification), never two. The
calendar's debrief question is a different thing and stays separate."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.models.applications import Application, PendingAction, PendingActionType, PendingStatus
from app.models.followups import FollowupDue
from app.pipeline import events as calendar
from app.pipeline.followups import due
from tests.followups.helpers import AFTER_DELAY, maker, sent_app

DUE = AFTER_DELAY + timedelta(days=11)  # past the default 10 days for "submitted"


def _event_at(when) -> calendar.EventData:
    fmt = "%Y-%m-%dT%H:%M"
    return calendar.EventData(starts_local=when.strftime(fmt), ends_local=(when + timedelta(hours=1)).strftime(fmt),
                              timezone="UTC")


async def _open_follow_ups(s) -> list[PendingAction]:
    return list((await s.scalars(select(PendingAction).where(
        PendingAction.type == PendingActionType.follow_up, PendingAction.status == PendingStatus.open)
        .order_by(PendingAction.created_at))).all())


async def test_due_reminder_first_then_debrief_adds_no_second_follow_up(channel):
    app_id = await sent_app()
    async with maker()() as s:
        assert (await due.tick(s, None, now=DUE))["opened"] == 1
        await s.commit()
    async with maker()() as s:
        app = await s.get(Application, app_id)
        event = await calendar.create(s, app, _event_at(DUE - timedelta(days=1)), status="confirmed", actor="owner")
        result = await calendar.debrief(s, event, outcome="went_well", next_step="waiting", notes=None,
                                        actor="owner", now=DUE)
        await s.commit()
        [only] = await _open_follow_ups(s)
        assert only.detail["kind"] == "followup_due" and result.follow_up_id == only.id


async def test_debrief_follow_up_first_then_due_reminder_reuses_it(channel):
    app_id = await sent_app()
    async with maker()() as s:
        app = await s.get(Application, app_id)
        event = await calendar.create(s, app, _event_at(AFTER_DELAY + timedelta(days=1)), status="confirmed",
                                      actor="owner")
        result = await calendar.debrief(s, event, outcome="mixed", next_step="waiting", notes=None, actor="owner",
                                        now=AFTER_DELAY + timedelta(days=1, hours=2))
        await s.commit()
    later = utcnow() + timedelta(days=60)  # past 7 days ("interview") from the stage change, whenever it ran
    async with maker()() as s:
        assert (await due.tick(s, None, now=later))["opened"] == 1
        await s.commit()
        [only] = await _open_follow_ups(s)
        assert only.id == result.follow_up_id and only.detail["kind"] == calendar.FOLLOW_UP_KIND
        row = await s.scalar(select(FollowupDue).where(FollowupDue.application_id == app_id))
        assert row.pending_action_id == only.id


async def test_an_open_debrief_question_does_not_swallow_the_follow_up_reminder(channel):
    app_id = await sent_app()
    async with maker()() as s:
        app = await s.get(Application, app_id)
        await calendar.create(s, app, _event_at(DUE - timedelta(days=2)), status="confirmed", actor="owner")
        assert (await calendar.run_due(s, DUE - timedelta(days=1))).debriefs == 1
        await s.commit()
    async with maker()() as s:
        assert (await due.tick(s, None, now=DUE))["opened"] == 1
        await s.commit()
        kinds = sorted(a.detail["kind"] for a in await _open_follow_ups(s))
        assert kinds == ["followup_due", calendar.DEBRIEF_KIND]
