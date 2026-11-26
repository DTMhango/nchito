"""Dispatch, reconciliation, pause and restore against PostgreSQL with a fake channel (DESIGN.md 8.5,
18.2, 18.3, 18.6 gates 1 and 2). Invented data only."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.apply import approval, autopilot, dispatch, handoff, outcomes, owner_actions, packets, reconcile, restore
from app.apply.channels import registry
from app.apply.channels.base import DispatchOutcome
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
    SubmitPermit,
)
from app.models.base import Origin, ReviewState
from app.models.kit import Answer, AnswerClass
from app.models.platform import AuditEvent
from app.schemas.json_types import AnswerPatterns
from tests.apply.fakes import FakeChannel, sent
from tests.apply.helpers import email_draft, setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW

AFTER_DELAY = NOW + timedelta(minutes=11)  # past the default 10-minute email send delay


@pytest.fixture
def channel():
    fake = FakeChannel(hasher=registry.packet_hash)

    async def factory(session):
        return fake

    registry.register("email", factory, replace=True)
    yield fake
    registry.unregister("email")


def maker():
    return get_sessionmaker()


async def approve(s, app, draft=None):
    built = await packets.build(s, app, draft or email_draft(), actor="owner", now=NOW)
    await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                           channel=built.packet.contents.channel, actor="owner", now=NOW)
    return built.packet


async def ready_app(*, employer: str = "Acme Example", draft=None) -> uuid.UUID:
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, employer=employer, now=NOW)
        await approve(s, app, draft)
        await s.commit()
        return app.id


async def queued(app_id: uuid.UUID, now=NOW) -> uuid.UUID:
    async with maker()() as s:
        result = await dispatch.queue(s, app_id, now=now)
        assert result.queued, result.reason
        await s.commit()
        return result.attempt.id


async def load(model, ident):
    async with maker()() as s:
        return await s.get(model, ident)


async def attempts_of(app_id):
    async with maker()() as s:
        return (await s.scalars(select(DispatchAttempt).where(DispatchAttempt.application_id == app_id)
                                .order_by(DispatchAttempt.created_at))).all()


async def audit_actions(prefix: str) -> list[str]:
    async with maker()() as s:
        return list((await s.scalars(select(AuditEvent.action).where(AuditEvent.action.like(f"{prefix}%"))
                                     .order_by(AuditEvent.created_at))).all())


# ----- the normal path ----------------------------------------------------------------------------


async def test_send_waits_the_delay_then_records_evidence_and_the_audit_trail(channel):
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    attempt = await load(DispatchAttempt, attempt_id)
    assert attempt.status == DispatchStatus.reserved and attempt.send_after == NOW + timedelta(minutes=10)
    assert attempt.permit_id and attempt.gate_results
    async with maker()() as s:
        assert await dispatch.run(s, attempt_id, now=NOW) is None  # not due yet: still cancellable
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) == DispatchStatus.sent
    assert len(channel.dispatched) == 1
    attempt = await load(DispatchAttempt, attempt_id)
    app = await load(Application, app_id)
    assert attempt.status == DispatchStatus.sent and attempt.evidence.kind == "sent_mail_id"
    assert attempt.provider_message_id == "msg-1" and attempt.started_at == AFTER_DELAY
    assert app.stage == Stage.submitted and app.applied_at and app.confirmation_evidence[0].value == "msg-1"
    # Facts, approval, gates, permit, runner and evidence are all in the append-only audit.
    trail = await audit_actions("")
    for action in ("application.approved", "permit.granted", "permit.consumed", "dispatch.reserved",
                   "dispatch.started", "dispatch.sent"):
        assert action in trail
    async with maker()() as s:
        event = await s.scalar(select(AuditEvent).where(AuditEvent.action == "dispatch.reserved"))
        assert event.detail["approved_by"] == "owner" and event.detail["gates"] and event.detail["permit_id"]
        sent_event = await s.scalar(select(AuditEvent).where(AuditEvent.action == "dispatch.sent"))
        assert sent_event.detail["evidence"]["value"] == "msg-1"


async def test_sent_without_evidence_is_uncertain(channel):
    channel.outcomes = [DispatchOutcome(status="sent", provider_message_id="x")]
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) == DispatchStatus.unknown
    assert (await load(Application, app_id)).stage == Stage.submitted_unconfirmed


async def test_tick_queues_an_approved_packet_and_sends_it_once(channel):
    app_id = await ready_app()
    async with maker()() as s:
        report = await dispatch.tick(s, now=NOW)
        assert [r.status for r in report.queued] == ["queued"] and not report.sent
        report = await dispatch.tick(s, now=AFTER_DELAY)
        assert list(report.sent.values()) == ["sent"] and not report.queued
        await dispatch.tick(s, now=AFTER_DELAY + timedelta(hours=1))
    assert len(channel.dispatched) == 1 and len(await attempts_of(app_id)) == 1


async def test_owner_can_cancel_during_the_send_delay(channel):
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        app = await s.get(Application, app_id)
        await outcomes.cancel(s, attempt, app, "changed my mind", actor="owner", now=NOW)
        await s.commit()
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) is None
    assert not channel.dispatched and (await load(Application, app_id)).stage == Stage.ready


# ----- no double submit under concurrency -----------------------------------------------------------


async def test_two_workers_one_packet_never_submit_twice(channel):
    channel.delay = 0.2
    app_id = await ready_app()

    async def worker_queue():
        async with maker()() as s:
            result = await dispatch.queue(s, app_id, now=NOW)
            await asyncio.sleep(0.2)
            await s.commit()
            return result.status

    assert sorted(await asyncio.gather(worker_queue(), worker_queue())) == ["denied", "queued"]
    rows = await attempts_of(app_id)
    assert len(rows) == 1

    async def worker_run():
        async with maker()() as s:
            return await dispatch.run(s, rows[0].id, now=AFTER_DELAY)

    results = await asyncio.gather(worker_run(), worker_run(), worker_run())
    assert sorted(r.value for r in results if r) == ["sent"]
    assert len(channel.dispatched) == 1
    async with maker()() as s:
        assert len((await s.scalars(select(SubmitPermit))).all()) == 1


# ----- uncertain: never resent; reconcile settles it both ways --------------------------------------


async def test_uncertain_is_never_resent_and_reconcile_settles_it_as_sent(channel):
    channel.outcomes = [TimeoutError("provider timed out after accepting?")]
    channel.reconciles = [DispatchOutcome(status="unknown"), sent("found-in-sent-items")]
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) == DispatchStatus.unknown
        assert (await s.get(Application, app_id)).stage == Stage.submitted_unconfirmed
        # The next ticks never resend, and the role is not queued again; reconcile runs on its schedule.
        first = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=1))
        assert first.reconciled == {attempt_id: "waiting"} and not first.queued
        skipped = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=5))  # within check_every_minutes
        assert skipped.reconciled == {}
        settled = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=17))
        assert settled.reconciled == {attempt_id: "sent"}
    assert len(channel.dispatched) == 1 and len(channel.reconciled) == 2
    attempt = await load(DispatchAttempt, attempt_id)
    assert attempt.status == DispatchStatus.sent and attempt.evidence.value == "found-in-sent-items"
    assert attempt.reconcile_attempts == 2 and (await load(Application, app_id)).stage == Stage.submitted


async def test_reconcile_settles_not_sent_and_nothing_is_retried(channel):
    channel.outcomes = [TimeoutError("timeout")]
    channel.reconciles = [DispatchOutcome(status="failed", error="not in sent items")]
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        await dispatch.run(s, attempt_id, now=AFTER_DELAY)
        report = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=1))
        assert report.reconciled == {attempt_id: "not_sent"}
        again = await dispatch.tick(s, now=AFTER_DELAY + timedelta(hours=2))
        assert not again.queued and not again.sent
    app = await load(Application, app_id)
    assert app.stage == Stage.ready and app.applied_at is None
    assert len(channel.dispatched) == 1 and len(await attempts_of(app_id)) == 1


@pytest.mark.parametrize("wait_hours", [None, 48])
async def test_reconcile_gives_up_and_asks_the_owner_who_confirms(channel, wait_hours):
    channel.outcomes = [TimeoutError("timeout")]
    app_id = await ready_app()
    async with maker()() as s:
        if wait_hours:
            await settings_service.set_value(s, "reconcile.confirmation_wait_hours", wait_hours, actor="owner")
            await s.commit()
    hours = wait_hours or 24
    attempt_id = await queued(app_id)
    async with maker()() as s:
        await dispatch.run(s, attempt_id, now=AFTER_DELAY)
        await dispatch.tick(s, now=AFTER_DELAY + timedelta(hours=hours - 1))
        assert await s.scalar(select(PendingAction).where(
            PendingAction.type == PendingActionType.confirm_submission)) is None
        await dispatch.tick(s, now=AFTER_DELAY + timedelta(hours=hours, minutes=1))
        await dispatch.tick(s, now=AFTER_DELAY + timedelta(hours=hours + 1))  # asked once only
        actions = (await s.scalars(select(PendingAction).where(
            PendingAction.type == PendingActionType.confirm_submission))).all()
        assert len(actions) == 1 and actions[0].detail["attempt_id"] == str(attempt_id)
        await owner_actions.confirm_submission(s, actions[0], actor="owner", reference="REF-123")
        await s.commit()
        await s.refresh(actions[0])
        assert actions[0].status == PendingStatus.resolved
    app = await load(Application, app_id)
    assert app.stage == Stage.submitted and app.reference == "REF-123"
    assert len(channel.dispatched) == 1


# ----- restart resumes without duplicates (release gate 2, restart) ---------------------------------


async def test_worker_dies_after_the_provider_accepted_restart_reconciles_without_a_second_send(channel):
    channel.outcomes = [asyncio.CancelledError()]  # the worker is killed mid-send: nothing is recorded
    channel.reconciles = [sent("accepted-before-crash")]
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        with pytest.raises(asyncio.CancelledError):
            await dispatch.run(s, attempt_id, now=AFTER_DELAY)
    attempt = await load(DispatchAttempt, attempt_id)
    assert attempt.status == DispatchStatus.reserved and attempt.started_at == AFTER_DELAY  # in flight
    async with maker()() as s:
        # Restarted: the in-flight attempt is never claimed again, and is not yet called uncertain.
        early = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=5))
        assert not early.sent and not early.uncertain and not early.queued
        later = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=16))
        assert later.uncertain == [attempt_id] and later.reconciled == {attempt_id: "sent"}
        await dispatch.tick(s, now=AFTER_DELAY + timedelta(hours=1))
    assert len(channel.dispatched) == 1 and len(await attempts_of(app_id)) == 1
    assert (await load(Application, app_id)).stage == Stage.submitted


# ----- bounded retry of definite failures, each with a fresh permit ---------------------------------


@pytest.mark.parametrize("max_retries", [None, 2])
async def test_definite_failure_is_retried_with_a_fresh_permit_up_to_the_limit(channel, max_retries):
    failed = DispatchOutcome(status="failed", error="mailbox refused: quota")
    channel.outcomes = [failed, failed, sent("third-time")]
    if max_retries is not None:
        async with maker()() as s:
            await settings_service.set_value(s, "automation.dispatch_max_retries", max_retries, actor="owner")
            await s.commit()
    app_id = await ready_app()
    async with maker()() as s:
        await dispatch.tick(s, now=NOW)
        await dispatch.tick(s, now=AFTER_DELAY)
    rows = await attempts_of(app_id)
    app = await load(Application, app_id)
    async with maker()() as s:
        permits_used = (await s.scalars(select(SubmitPermit).order_by(SubmitPermit.issued_at))).all()
    assert len({r.permit_id for r in rows}) == len(rows) == len(permits_used)
    assert all(p.used_at is not None for p in permits_used)
    if max_retries is None:  # default 1: two tries, then the claim goes back
        assert [r.status for r in rows] == [DispatchStatus.failed, DispatchStatus.failed]
        assert app.stage == Stage.ready and "dispatch.gave_up" in await audit_actions("dispatch.")
    else:
        assert [r.status for r in rows] == [DispatchStatus.failed, DispatchStatus.failed, DispatchStatus.sent]
        assert app.stage == Stage.submitted
    assert len(channel.dispatched) == len(rows)


# ----- pause --------------------------------------------------------------------------------------


async def test_pause_blocks_dispatch(channel):
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        summary = (await autopilot.set_paused(s, True, actor="owner", reason="checking")).summary
        await s.commit()
        assert [i.id for i in summary.cancelled] == [str(attempt_id)]
        report = await dispatch.tick(s, now=AFTER_DELAY)
        assert not report.sent and not report.queued
        refused = await dispatch.queue(s, app_id, now=AFTER_DELAY)
        assert refused.status == "denied" and "pause" in refused.reason
        await s.rollback()
    assert not channel.dispatched and (await load(Application, app_id)).stage == Stage.ready


async def test_pause_set_during_the_delay_is_rechecked_at_dispatch(channel):
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        await settings_service.set_value(s, "automation.paused", True, actor="owner")  # no pause effects run
        await s.commit()
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) == DispatchStatus.cancelled
    assert not channel.dispatched
    assert (await load(DispatchAttempt, attempt_id)).error.startswith("autopilot is paused")
    assert "global_pause" in [e["gates"][0]["gate"] for e in await _details("dispatch.cancelled")]


async def _details(action: str) -> list[dict]:
    async with maker()() as s:
        return [e.detail for e in (await s.scalars(select(AuditEvent).where(AuditEvent.action == action))).all()]


# ----- release gate 1: the packet changes during the send delay ------------------------------------


async def test_pay_answer_changed_during_the_delay_old_packet_cannot_go_out(channel):
    async with maker()() as s:
        answer = Answer(patterns=AnswerPatterns(canonical="Expected salary"), value="USD 55,000",
                        answer_class=AnswerClass.auto, material=True, settled=True,
                        review_state=ReviewState.confirmed, origin=Origin.owner)
        s.add(answer)
        await s.commit()
        answer_id = answer.id
    draft = email_draft()
    draft.answers = [packets.DraftAnswer(question="Expected salary", answer_id=answer_id)]
    app_id = await ready_app(draft=draft)
    attempt_id = await queued(app_id)
    async with maker()() as s:
        (await s.get(Answer, answer_id)).value = "USD 70,000"
        await s.commit()
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) == DispatchStatus.cancelled
    assert not channel.dispatched
    attempt = await load(DispatchAttempt, attempt_id)
    assert "answers[0].value" in attempt.error
    app = await load(Application, app_id)
    assert app.stage == Stage.ready and app.approved_packet_id is None
    async with maker()() as s:
        assert await packets.current(s, app_id) is None  # the old packet is retired; a new one needs approval


# ----- restore from backup (18.3; release gate 2, restore) ------------------------------------------


async def test_restore_starts_paused_and_resume_requires_reconciliation(channel):
    channel.outcomes = [asyncio.CancelledError()]
    channel.reconciles = [DispatchOutcome(status="unknown"), sent("sent-after-backup")]
    in_flight_app = await ready_app()
    waiting_app = await ready_app(employer="Beta Example")  # approved, not yet queued at backup time
    attempt_id = await queued(in_flight_app)
    async with maker()() as s:
        with pytest.raises(asyncio.CancelledError):
            await dispatch.run(s, attempt_id, now=AFTER_DELAY)
    async with maker()() as s:
        state = await restore.enter(s, backup_taken_at=AFTER_DELAY, now=AFTER_DELAY + timedelta(minutes=1))
        await s.commit()
        assert state.active and [a.id for a in state.outstanding] == [attempt_id]
        assert state.held_application_ids == [waiting_app]
        assert await dispatch.is_paused(s)
        with pytest.raises(restore.RestoreError) as refused:
            await restore.resume(s, actor="owner")
        assert refused.value.outstanding == [attempt_id]
        with pytest.raises(autopilot.ResumeRefused):
            await autopilot.set_paused(s, False, actor="owner")
        await s.rollback()
        # The held role cannot be sent: its approval was withdrawn and the owner is asked again.
        held = await s.get(Application, waiting_app)
        assert held.approved_packet_id is None
        ask = await s.scalar(select(PendingAction).where(PendingAction.application_id == waiting_app,
                                                         PendingAction.type == PendingActionType.approve))
        assert ask is not None and "restored" in ask.detail["reason"]
        # Reconciliation runs while paused; nothing is sent.
        first = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=2))
        assert first.reconciled == {attempt_id: "waiting"} and not first.queued and not first.sent
        with pytest.raises(restore.RestoreError):
            await restore.resume(s, actor="owner")
        await s.rollback()
        second = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=20))
        assert second.reconciled == {attempt_id: "sent"}
        await restore.resume(s, actor="owner")
        await s.commit()
        assert not await dispatch.is_paused(s) and not (await restore.state(s)).active
        after = await dispatch.tick(s, now=AFTER_DELAY + timedelta(minutes=30))
        assert not after.queued  # the held role waits for the owner's new approval
    assert len(channel.dispatched) == 1
    assert (await load(Application, in_flight_app)).stage == Stage.submitted


async def test_owner_can_settle_a_restore_attempt_as_not_sent(channel):
    channel.outcomes = [TimeoutError("timeout")]
    app_id = await ready_app()
    attempt_id = await queued(app_id)
    async with maker()() as s:
        await dispatch.run(s, attempt_id, now=AFTER_DELAY)
        await restore.enter(s, now=AFTER_DELAY + timedelta(minutes=1))
        await s.commit()
        attempt = await s.get(DispatchAttempt, attempt_id)
        assert await reconcile.decide(s, attempt, "not_sent", actor="owner", note="checked: not in sent items") \
            == "not_sent"
        await restore.resume(s, actor="owner")
        await s.commit()
    assert (await load(Application, app_id)).stage == Stage.ready and len(channel.dispatched) == 1


# ----- manual handoff ------------------------------------------------------------------------------


def manual_draft():
    return packets.PacketDraft(channel="manual", destination_url="https://boards.greenhouse.io/acme/jobs/1",
                               sending_identity="owner@example.com",
                               answers=[packets.DraftAnswer(question="Notice period", value="One month")])


async def test_mark_submitted_blocks_a_later_automatic_send_of_the_same_role(channel):
    async with maker()() as s:
        campaign = await setup_campaign(s)
        job, manual_app = await setup_app(s, campaign, now=NOW)
        await approve(s, manual_app, manual_draft())
        # A second application to the same job, approved for email before the owner submitted by hand.
        other = Application(job_id=job.id, campaign_id=campaign.id, assessment_id=manual_app.assessment_id,
                            stage=Stage.ready)
        s.add(other)
        await s.flush()
        await approve(s, other)
        await s.commit()
        manual_id, other_id = manual_app.id, other.id
    async with maker()() as s:
        kit = await handoff.kit(s, await s.get(Application, manual_id))
        assert kit.posting_url == "https://boards.greenhouse.io/acme/jobs/1"
        assert kit.answers == [{"question": "Notice period", "value": "One month"}] and kit.remaining_steps
        await handoff.mark_submitted(s, await s.get(Application, manual_id), reference="GH-42", note=None,
                                     actor="owner", now=NOW)
        await s.commit()
    app = await load(Application, manual_id)
    assert app.stage == Stage.submitted and app.reference == "GH-42"
    rows = await attempts_of(manual_id)
    assert len(rows) == 1 and rows[0].status == DispatchStatus.sent and rows[0].evidence.kind == "reference"
    async with maker()() as s:
        refused = await dispatch.queue(s, other_id, now=NOW)
        assert refused.status == "denied" and ("gone out" in refused.reason or "employer" in refused.reason)
        await s.rollback()
        report = await dispatch.tick(s, now=AFTER_DELAY)
        assert not any(r.queued for r in report.queued)
    assert not channel.dispatched and not await attempts_of(other_id)


async def test_mark_submitted_without_an_approved_packet_points_to_applied_myself(channel):
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, now=NOW)
        await packets.build(s, app, manual_draft(), actor="owner", now=NOW)
        with pytest.raises(handoff.HandoffError, match="applied myself"):
            await handoff.mark_submitted(s, app, reference=None, note=None, actor="owner", now=NOW)
        await s.rollback()


# ----- quiet hours are rechecked at send time -----------------------------------------------------


async def test_a_permit_granted_before_quiet_hours_does_not_send_inside_them(channel):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    app_id = await ready_app()
    async with maker()() as s:
        zone = ZoneInfo(await settings_service.get_value(s, "general.timezone"))
    start = (NOW + timedelta(minutes=5)).astimezone(zone)
    end = (NOW + timedelta(minutes=60)).astimezone(zone)
    attempt_id = await queued(app_id)  # granted at NOW, outside quiet hours
    async with maker()() as s:
        await settings_service.set_value(s, "automation.quiet_hours_start", start.strftime("%H:%M"), actor="owner")
        await settings_service.set_value(s, "automation.quiet_hours_end", end.strftime("%H:%M"), actor="owner")
        await s.commit()
        assert await dispatch.run(s, attempt_id, now=AFTER_DELAY) is None  # due, but inside quiet hours
    assert not channel.dispatched
    attempt = await load(DispatchAttempt, attempt_id)
    resume = datetime.combine(end.date(), end.time().replace(second=0, microsecond=0), tzinfo=zone)
    assert attempt.status == DispatchStatus.reserved and attempt.started_at is None
    assert attempt.send_after == resume
    assert "dispatch.deferred" in await audit_actions("dispatch.")
    async with maker()() as s:
        assert await dispatch.run(s, attempt_id, now=resume + timedelta(minutes=1)) == DispatchStatus.sent
    assert len(channel.dispatched) == 1


def test_quiet_hours_end_handles_overnight_windows_and_unknown():
    from datetime import UTC, datetime

    values = {"automation.quiet_hours_start": "21:00", "automation.quiet_hours_end": "07:00",
              "general.timezone": "UTC"}
    assert dispatch.quiet_hours_end(values, datetime(2026, 11, 26, 22, 0, tzinfo=UTC)) == datetime(
        2026, 11, 27, 7, 0, tzinfo=UTC)
    assert dispatch.quiet_hours_end(values, datetime(2026, 11, 26, 6, 0, tzinfo=UTC)) == datetime(
        2026, 11, 26, 7, 0, tzinfo=UTC)
    assert dispatch.quiet_hours_end(values, datetime(2026, 11, 26, 12, 0, tzinfo=UTC)) is None
    assert dispatch.quiet_hours_end({**values, "general.timezone": None}, datetime.now(UTC)) == "unknown"
