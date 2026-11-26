"""Interview events: lifecycle, proposals from mail (never auto-confirmed), overlaps, reminders, debrief."""

# ruff: noqa: E501
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.settings import service as settings_service
from app.llm.fake import FakeLLMClient
from app.models.applications import (
    ApplicationEvent,
    PendingAction,
    PendingStatus,
    Stage,
)
from app.models.calendar import InterviewEvent
from app.models.platform import Notification
from app.pipeline import events as svc
from tests.calendar.helpers import NOW, ics_invite, invite, make_job_app

LUSAKA = "Africa/Lusaka"


def data(start: str = "2026-12-03T14:30", end: str | None = "2026-12-03T15:30", tz: str = LUSAKA, **kw) -> svc.EventData:
    return svc.EventData(starts_local=start, ends_local=end, timezone=tz, **kw)


async def values(session) -> dict:
    return await settings_service.values(session)


async def proposals(session) -> list[InterviewEvent]:
    return list((await session.scalars(select(InterviewEvent).where(InterviewEvent.status == "proposed"))).all())


# ----- lifecycle --------------------------------------------------------------------------------------


async def test_create_confirmed_event_stores_utc_and_the_employer_zone(session) -> None:
    _, app = await make_job_app(session)
    ev = await svc.create(session, app, data("2026-07-15T10:00", "2026-07-15T11:00", "Europe/London",
                                             type="video", interviewers=("Jane Banda", "Jane Banda", " Tom ")),
                          status="confirmed", actor="owner")
    await session.commit()
    assert ev.starts_at == datetime(2026, 7, 15, 9, 0, tzinfo=UTC) and ev.timezone == "Europe/London"
    assert ev.interviewers == ["Jane Banda", "Tom"]
    assert svc.local_text(ev.starts_at, LUSAKA) == "2026-07-15T11:00"  # both zones from one instant
    kinds = [e.kind for e in await session.scalars(select(ApplicationEvent))]
    assert "interview_event" in kinds


async def test_a_wall_time_in_a_clock_gap_is_refused_and_a_missing_zone_too(session) -> None:
    _, app = await make_job_app(session)
    with pytest.raises(svc.EventError) as gap:
        await svc.create(session, app, data("2026-03-29T01:30", None, "Europe/London"), status="confirmed", actor="owner")
    assert gap.value.code == "nonexistent_time"
    with pytest.raises(svc.EventError) as no_zone:
        await svc.create(session, app, svc.EventData(starts_local="2026-12-03T10:00"), status="confirmed", actor="owner")
    assert no_zone.value.code == "timezone_required"
    with pytest.raises(svc.EventError) as bad_zone:
        await svc.create(session, app, data(tz="Mars/Olympus"), status="confirmed", actor="owner")
    assert bad_zone.value.code == "invalid_timezone"
    with pytest.raises(svc.EventError) as backwards:
        await svc.create(session, app, data("2026-12-03T15:00", "2026-12-03T14:00"), status="confirmed", actor="owner")
    assert backwards.value.code == "invalid_range"


async def test_meeting_link_must_be_http_and_is_only_text(session) -> None:
    _, app = await make_job_app(session)
    with pytest.raises(svc.EventError):
        await svc.create(session, app, data(meeting_link="javascript:alert(1)"), status="confirmed", actor="owner")
    ev = await svc.create(session, app, data(meeting_link="https://meet.example.com/x"), status="confirmed", actor="owner")
    assert ev.meeting_link == "https://meet.example.com/x"


async def test_confirmed_event_cannot_be_moved_by_edit_only_by_reschedule(session) -> None:
    _, app = await make_job_app(session)
    ev = await svc.create(session, app, data(), status="confirmed", actor="owner")
    with pytest.raises(svc.EventError) as err:
        await svc.update(session, ev, data("2026-12-04T09:00", None), actor="owner")
    assert err.value.code == "use_reschedule"
    await svc.update(session, ev, data(location="Plot 1"), actor="owner")  # unchanged time is fine
    fresh = await svc.reschedule(session, ev, data("2026-12-04T09:00", None), actor="owner")
    await session.commit()
    await session.refresh(ev)
    assert ev.status == "rescheduled" and fresh.status == "confirmed" and fresh.replaces_id == ev.id
    assert fresh.starts_at == datetime(2026, 12, 4, 7, 0, tzinfo=UTC) and fresh.location == "Plot 1"


async def test_cancel_and_the_states_that_cannot_change(session) -> None:
    _, app = await make_job_app(session)
    ev = await svc.create(session, app, data(), status="confirmed", actor="owner")
    await svc.cancel(session, ev, actor="owner")
    assert ev.status == "cancelled"
    with pytest.raises(svc.EventError):
        await svc.cancel(session, ev, actor="owner")
    with pytest.raises(svc.EventError):
        await svc.reschedule(session, ev, data(), actor="owner")


# ----- overlaps -----------------------------------------------------------------------------------------


async def test_overlap_is_reported_for_both_events_and_back_to_back_is_not(session) -> None:
    _, app1 = await make_job_app(session, employer="Acme Ltd")
    _, app2 = await make_job_app(session, employer="Beta Ltd")
    first = await svc.create(session, app1, data("2026-12-03T14:00", "2026-12-03T15:00"), status="confirmed", actor="owner")
    second = await svc.create(session, app2, data("2026-12-03T14:30", "2026-12-03T15:30"), status="confirmed", actor="owner")
    third = await svc.create(session, app2, data("2026-12-03T15:30", "2026-12-03T16:00"), status="confirmed", actor="owner")
    await session.commit()
    found = await svc.conflicts_for(session, [first, second, third])
    assert [e.id for e in found[first.id]] == [second.id]
    assert {e.id for e in found[second.id]} == {first.id}
    assert third.id not in found  # starts the minute the second ends


async def test_overlap_uses_the_default_length_when_there_is_no_end_and_ignores_cancelled(session) -> None:
    _, app1 = await make_job_app(session, employer="Acme Ltd")
    _, app2 = await make_job_app(session, employer="Beta Ltd")
    a = await svc.create(session, app1, data("2026-12-03T14:00", None), status="confirmed", actor="owner")
    b = await svc.create(session, app2, data("2026-12-03T14:50", None), status="confirmed", actor="owner")
    await session.commit()
    assert a.id in {e.id for e in (await svc.conflicts_for(session, [b]))[b.id]}  # default 60 minutes
    await settings_service.set_value(session, "calendar.default_duration_minutes", 45, actor="test")
    await session.commit()
    assert await svc.conflicts_for(session, [b]) == {}
    await settings_service.set_value(session, "calendar.default_duration_minutes", 60, actor="test")
    await svc.cancel(session, a, actor="owner")
    assert await svc.conflicts_for(session, [b]) == {}


# ----- proposals from mail ------------------------------------------------------------------------------


async def test_ics_invite_becomes_a_proposal_never_a_confirmed_event(session) -> None:
    _, app = await make_job_app(session)
    msg = invite(calendars=(ics_invite(extra=("DESCRIPTION:Join https://meet.example.com/room",)),))
    ev = await svc.propose_from_message(session, app, msg, values=await values(session))
    await session.commit()
    assert ev is not None and ev.status == "proposed" and ev.source == "mail"
    assert ev.starts_at == datetime(2026, 12, 3, 12, 30, tzinfo=UTC) and ev.timezone == LUSAKA
    assert ev.meeting_link == "https://meet.example.com/room" and ev.type == "video"
    assert ev.interviewers == ["Jane Banda"] and ev.ics_uid == "inv-1@acme.example.com"
    [action] = (await session.scalars(select(PendingAction))).all()
    assert action.detail["kind"] == svc.PROPOSAL_KIND and action.detail["event_id"] == str(ev.id)


async def test_a_message_is_proposed_once(session) -> None:
    _, app = await make_job_app(session)
    msg = invite(calendars=(ics_invite(),))
    assert await svc.propose_from_message(session, app, msg, values=await values(session)) is not None
    assert await svc.propose_from_message(session, app, msg, values=await values(session)) is None
    await session.commit()
    assert len(await proposals(session)) == 1


async def test_ambiguous_invites_stay_proposals_with_candidates(session) -> None:
    _, app = await make_job_app(session)
    # several options, no zone
    several = invite(body="Could you do 3 December 2026 at 10:00, or 4 December 2026 at 11:00?", message_id="m-a")
    a = await svc.propose_from_message(session, app, several, values=await values(session))
    # one time, but no zone
    nozone = invite(body="Interview on 7 December 2026 at 09:00.", message_id="m-b")
    b = await svc.propose_from_message(session, app, nozone, values=await values(session))
    # a floating time in a calendar file
    floating = invite(calendars=(ics_invite(uid="f", tzid=None, start="20261208T090000", end=None),), message_id="m-c")
    c = await svc.propose_from_message(session, app, floating, values=await values(session))
    # nothing readable at all
    nothing = invite(body="Please call us to arrange a time.", message_id="m-d")
    d = await svc.propose_from_message(session, app, nothing, values=await values(session))
    await session.commit()
    assert a is not None and b is not None and c is not None and d is not None
    for ev in (a, b, c, d):
        assert ev.status == "proposed" and ev.starts_at is None
    assert len(a.candidates) == 2 and a.candidates[0].timezone is None
    assert len(b.candidates) == 1 and b.candidates[0].starts_local == "2026-12-07T09:00"
    assert d.candidates == []
    # none of them became a confirmed event, and none can be confirmed without the owner choosing
    with pytest.raises(svc.EventError) as err:
        await svc.confirm(session, a, actor="owner")
    assert err.value.code == "time_required"
    with pytest.raises(svc.EventError) as no_zone:
        await svc.confirm(session, a, actor="owner", candidate_index=1)
    assert no_zone.value.code == "timezone_required"


async def test_owner_picks_a_candidate_and_names_the_zone(session) -> None:
    _, app = await make_job_app(session)
    several = invite(body="Could you do 3 December 2026 at 10:00, or 4 December 2026 at 11:00?")
    ev = await svc.propose_from_message(session, app, several, values=await values(session))
    assert ev is not None
    await svc.confirm(session, ev, actor="owner", candidate_index=1, data=svc.EventData(timezone=LUSAKA))
    await session.commit()
    assert ev.status == "confirmed" and ev.starts_at == datetime(2026, 12, 4, 9, 0, tzinfo=UTC) and ev.candidates == []
    open_actions = [a for a in await session.scalars(select(PendingAction)) if a.status == PendingStatus.open]
    assert open_actions == []  # confirming settles the proposal's pending action


async def test_a_time_in_a_clock_gap_is_not_offered_as_a_candidate(session) -> None:
    _, app = await make_job_app(session)
    msg = invite(calendars=(ics_invite(tzid="Europe/London", start="20260329T013000", end=None),))
    ev = await svc.propose_from_message(session, app, msg, values=await values(session))
    assert ev is not None and ev.candidates == [] and ev.starts_at is None


async def test_employer_cancel_of_a_confirmed_event_is_flagged_not_applied(session) -> None:
    _, app = await make_job_app(session)
    first = invite(calendars=(ics_invite(),), message_id="m-1")
    ev = await svc.propose_from_message(session, app, first, values=await values(session))
    assert ev is not None
    await svc.confirm(session, ev, actor="owner")
    cancel = invite(calendars=(ics_invite(method="CANCEL", extra=("STATUS:CANCELLED",)),), message_id="m-2")
    assert await svc.propose_from_message(session, app, cancel, values=await values(session)) is None
    await session.commit()
    await session.refresh(ev)
    assert ev.status == "confirmed"  # the owner decides
    kinds = [a.detail["kind"] for a in await session.scalars(select(PendingAction))]
    assert svc.UPDATE_KIND in kinds


async def test_employer_time_change_updates_a_proposal_but_only_flags_a_confirmed_event(session) -> None:
    _, app = await make_job_app(session)
    ev = await svc.propose_from_message(session, app, invite(calendars=(ics_invite(),), message_id="m-1"),
                                        values=await values(session))
    assert ev is not None
    moved = invite(calendars=(ics_invite(start="20261204T100000", end=None),), message_id="m-2")
    await svc.propose_from_message(session, app, moved, values=await values(session))
    await session.refresh(ev)
    assert ev.status == "proposed" and ev.starts_at == datetime(2026, 12, 4, 8, 0, tzinfo=UTC)
    await svc.confirm(session, ev, actor="owner")
    later = invite(calendars=(ics_invite(start="20261205T100000", end=None),), message_id="m-3")
    await svc.propose_from_message(session, app, later, values=await values(session))
    await session.commit()
    await session.refresh(ev)
    assert ev.starts_at == datetime(2026, 12, 4, 8, 0, tzinfo=UTC)  # unchanged
    assert svc.UPDATE_KIND in [a.detail["kind"] for a in await session.scalars(select(PendingAction))]


async def test_hostile_calendar_part_is_ignored_and_the_wording_rules_still_run(session) -> None:
    _, app = await make_job_app(session)
    msg = invite(body="Interview on 3 December 2026 at 14:30 CAT", calendars=(b"BEGIN:VCALENDAR" + b"x" * 400_000,
                                                                               b"garbage"))
    ev = await svc.propose_from_message(session, app, msg, values=await values(session))
    assert ev is not None and ev.starts_at == datetime(2026, 12, 3, 12, 30, tzinfo=UTC)


async def test_feature_can_be_switched_off(session) -> None:
    _, app = await make_job_app(session)
    await settings_service.set_value(session, "calendar.propose_from_mail", False, actor="test")
    assert await svc.propose_from_message(session, app, invite(calendars=(ics_invite(),)),
                                          values=await values(session)) is None


async def test_model_extraction_is_off_by_default_and_when_on_only_proposes(session) -> None:
    _, app = await make_job_app(session)
    llm = FakeLLMClient().script("classify_email", {"slots": [{"date": "2026-12-09", "start": "10:00", "timezone": "Africa/Lusaka"},
                                                              {"date": "not a date", "start": "10:00"}]})
    msg = invite(body="Let us talk about next steps soon.")
    off = await svc.propose_from_message(session, app, msg, values=await values(session), llm=llm)
    assert off is not None and off.candidates == [] and llm.calls_for("classify_email") == []
    await settings_service.set_value(session, "calendar.llm_extract", True, actor="test")
    on = await svc.propose_from_message(session, app, invite(body="Let us talk soon.", message_id="m-2"),
                                        values=await values(session), llm=llm)
    assert on is not None and on.status == "proposed"
    assert [c.starts_local for c in on.candidates] == ["2026-12-09T10:00"] and on.starts_at is not None
    [call] = llm.calls_for("classify_email")
    assert '<<<DATA label="email"' in call.prompt.all_text  # the mail went in as a data block, not as instructions
    assert "Let us talk soon." not in call.prompt.all_text.split("<<<DATA")[0]


# ----- reminders ------------------------------------------------------------------------------------------


async def notices(session) -> list[Notification]:
    return list((await session.scalars(select(Notification).order_by(Notification.created_at))).all())


async def configure(session, **extra) -> None:
    await settings_service.set_many(session, {"notifications.channels": ["telegram"], **extra}, actor="test")
    await session.commit()


async def test_reminders_fire_at_the_default_offsets_once_each(session) -> None:
    _, app = await make_job_app(session)
    start = NOW + timedelta(hours=30)  # 30 hours away
    ev = await svc.create(session, app, data(start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"), None, "UTC"), status="confirmed", actor="owner")
    await configure(session, **{"calendar.prep_nudge_minutes": 0})
    assert (await svc.run_due(session, NOW)).reminders == 0  # more than a day away (default 1440 and 60 minutes)
    first = await svc.run_due(session, NOW + timedelta(hours=7))  # 23 hours away: the one-day reminder
    assert first.reminders == 1
    assert (await svc.run_due(session, NOW + timedelta(hours=7, minutes=5))).reminders == 0  # not twice
    near = await svc.run_due(session, NOW + timedelta(hours=29, minutes=30))  # 30 minutes away: the one-hour reminder
    await session.commit()
    assert near.reminders == 1
    titles = [n.title for n in await notices(session)]
    assert titles[0].startswith("Interview in 1 day: Acme") and titles[1].startswith("Interview in 1 hour: Acme")
    assert all(n.kind == "interview_reminder" for n in await notices(session))
    assert ev.status == "confirmed"


async def test_reminders_follow_the_offsets_setting_and_a_late_worker_sends_one(session) -> None:
    _, app = await make_job_app(session)
    start = NOW + timedelta(hours=2)
    await svc.create(session, app, data(start.strftime("%Y-%m-%dT%H:%M"), None, "UTC"), status="confirmed", actor="owner")
    await configure(session, **{"calendar.reminder_offsets_minutes": [30, 15], "calendar.prep_nudge_minutes": 0})
    assert (await svc.run_due(session, NOW)).reminders == 0  # two hours away: neither 30 nor 15 minutes
    late = await svc.run_due(session, NOW + timedelta(hours=1, minutes=50))  # both due; only the nearest speaks
    await session.commit()
    assert late.reminders == 1
    assert next(n.title for n in await notices(session)).startswith("Interview in 15 minutes")


async def test_no_reminders_without_a_channel_or_when_the_kind_is_off_or_event_not_confirmed(session) -> None:
    _, app = await make_job_app(session)
    start = NOW + timedelta(minutes=30)
    ev = await svc.create(session, app, data(start.strftime("%Y-%m-%dT%H:%M"), None, "UTC"), status="confirmed", actor="owner")
    assert (await svc.run_due(session, NOW)).reminders == 0  # no channel configured
    await configure(session, **{"notifications.events": ["pending_action"]})
    assert (await svc.run_due(session, NOW)).reminders == 0  # reminders switched off
    await configure(session)
    ev.status = "proposed"
    await session.commit()
    assert (await svc.run_due(session, NOW)).reminders == 0  # a proposal is not an event yet


async def test_prep_nudge_links_to_the_pack_and_respects_its_setting(session) -> None:
    job, app = await make_job_app(session)
    start = NOW + timedelta(hours=40)
    await svc.create(session, app, data(start.strftime("%Y-%m-%dT%H:%M"), None, "UTC"), status="confirmed", actor="owner")
    await configure(session, **{"calendar.reminder_offsets_minutes": []})
    result = await svc.run_due(session, NOW)  # 40 hours away: inside the default 48-hour nudge window
    await session.commit()
    nudges = [n for n in await notices(session) if n.payload.get("nudge") == "prep"]
    assert result.reminders == 1 and nudges[0].link == f"/jobs/{job.id}?tab=interview"
    await settings_service.set_value(session, "calendar.prep_nudge_minutes", 0, actor="test")
    await session.execute(Notification.__table__.delete())
    await session.commit()
    assert (await svc.run_due(session, NOW)).reminders == 0


# ----- how did it go -----------------------------------------------------------------------------------


async def test_debrief_is_asked_once_after_the_event_and_answer_moves_the_application(session) -> None:
    _job, app = await make_job_app(session, stage=Stage.submitted)
    start = NOW - timedelta(hours=3)
    ev = await svc.create(session, app, data(start.strftime("%Y-%m-%dT%H:%M"), (start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), "UTC"), status="confirmed", actor="owner")
    assert (await svc.run_due(session, NOW - timedelta(hours=2))).debriefs == 0  # still within the debrief delay (60 minutes)
    assert (await svc.run_due(session, NOW)).debriefs == 1
    assert (await svc.run_due(session, NOW + timedelta(minutes=1))).debriefs == 0
    await session.commit()
    [action] = (await session.scalars(select(PendingAction).where(PendingAction.status == PendingStatus.open))).all()
    assert action.detail["kind"] == svc.DEBRIEF_KIND and "How did your interview" in action.title
    result = await svc.debrief(session, ev, outcome="went_well", next_step="another_round", notes="Panel of three", actor="owner", now=NOW)
    await session.commit()
    await session.refresh(app)
    assert ev.status == "done" and ev.outcome == "went_well" and app.stage == Stage.interview
    assert result.stage_changed_to == "interview" and result.follow_up_id is not None
    open_now = list((await session.scalars(select(PendingAction).where(PendingAction.status == PendingStatus.open))).all())
    assert [a.detail["kind"] for a in open_now] == [svc.FOLLOW_UP_KIND]
    assert open_now[0].deadline == NOW + timedelta(days=2)  # calendar.followup_days default


async def test_debrief_outcomes_offer_rejected_and_did_not_happen(session) -> None:
    _, app = await make_job_app(session, stage=Stage.interview)
    ev = await svc.create(session, app, data(), status="confirmed", actor="owner")
    done = await svc.debrief(session, ev, outcome="went_badly", next_step="rejected", notes=None, actor="owner")
    await session.refresh(app)
    assert app.stage == Stage.rejected and done.follow_up_id is None
    _, app2 = await make_job_app(session, employer="Beta Ltd", stage=Stage.interview)
    ev2 = await svc.create(session, app2, data(), status="confirmed", actor="owner")
    none = await svc.debrief(session, ev2, outcome="did_not_happen", next_step="waiting", notes=None, actor="owner")
    await session.refresh(app2)
    assert ev2.status == "cancelled" and app2.stage == Stage.interview and none.stage_changed_to is None


async def test_debrief_and_followup_use_the_followup_days_setting(session) -> None:
    _, app = await make_job_app(session, stage=Stage.interview)
    await settings_service.set_value(session, "calendar.followup_days", 5, actor="test")
    ev = await svc.create(session, app, data(), status="confirmed", actor="owner")
    res = await svc.debrief(session, ev, outcome="mixed", next_step="waiting", notes=None, actor="owner", now=NOW)
    action = await session.get(PendingAction, res.follow_up_id)
    assert action is not None and action.deadline == NOW + timedelta(days=5)
