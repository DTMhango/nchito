"""The browser channel against PostgreSQL (DESIGN.md 8.2, 8.5, 18.1, 18.3): a task, then a permit consumed at
Submit, a clearance, the runner's report, and reconciliation. Invented data only; no runner, no network."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.apply import approval, dispatch, packets, reconcile
from app.apply.channels import browser, registry
from app.apply.channels.base import DispatchRequest
from app.core.db import get_sessionmaker
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    Application,
    DispatchAttempt,
    DispatchStatus,
    MailClassification,
    MailThread,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.platform import ApiToken, AuditEvent
from app.schemas.json_types import Evidence
from tests.apply.helpers import browser_draft, email_draft, setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW


def maker():
    return get_sessionmaker()


CONFIRMED = Evidence(kind="confirmation_page", value="Thank you, your application was received", at=NOW.isoformat())


async def ready_app(draft=None, *, employer: str = "Acme Example") -> tuple[uuid.UUID, uuid.UUID]:
    """An approved browser packet, and a runner token."""
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, employer=employer, now=NOW)
        built = await packets.build(s, app, draft or browser_draft(), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="browser", actor="owner", now=NOW)
        token = ApiToken(name="pc", token_hash=uuid.uuid4().hex * 2, prefix="nch_", runner_kind="pc")
        s.add(token)
        await s.commit()
        return app.id, token.id


async def task_of(app_id: uuid.UUID) -> AgentTask:
    async with maker()() as s:
        return (await s.scalars(select(AgentTask).where(AgentTask.application_id == app_id)
                                .order_by(AgentTask.created_at.desc()))).first()


async def attempts_of(app_id: uuid.UUID) -> list[DispatchAttempt]:
    async with maker()() as s:
        return list((await s.scalars(select(DispatchAttempt).where(DispatchAttempt.application_id == app_id))).all())


async def load(model, ident):
    async with maker()() as s:
        return await s.get(model, ident)


async def cleared(app_id: uuid.UUID, token_id: uuid.UUID, now=NOW) -> uuid.UUID:
    """The gateway's sequence: queue the task, a runner claims it, the permit is asked for and consumed with the
    attempt, the recheck runs and the runner is cleared. Returns the attempt id."""
    async with maker()() as s:
        queued = await dispatch.queue(s, app_id, now=now)
        assert queued.queued and queued.attempt is None, queued.reason
        await s.commit()
    task = await task_of(app_id)
    async with maker()() as s:
        await browser.mark_task_claimed(s, task.id, token_id=token_id, now=now)
        await s.commit()
    async with maker()() as s:
        result = await dispatch.queue(s, app_id, runner_token_id=token_id, agent_task_id=task.id, now=now)
        assert result.queued and result.attempt is not None, result.reason
        attempt_id = result.attempt.id
        await s.commit()
    async with maker()() as s:
        assert await dispatch.run(s, attempt_id, now=now) == DispatchStatus.handed_off
    return attempt_id


# ----- the permit is consumed at Submit, not at dispatch ------------------------------------------


async def test_dispatch_without_a_runner_queues_a_task_and_takes_no_permit():
    app_id, _ = await ready_app()
    async with maker()() as s:
        result = await dispatch.queue(s, app_id, now=NOW)
        assert result.queued and result.attempt is None
        again = await dispatch.queue(s, app_id, now=NOW)  # idempotent per packet hash
        assert again.queued
        await s.commit()
    assert await attempts_of(app_id) == []
    async with maker()() as s:
        tasks = (await s.scalars(select(AgentTask).where(AgentTask.application_id == app_id))).all()
        assert len(tasks) == 1 and tasks[0].status == AgentTaskStatus.queued
        assert tasks[0].payload["packet_hash"] and tasks[0].payload["destination_domain"] == "boards.greenhouse.io"
        permits = (await s.scalars(select(AuditEvent.action).where(AuditEvent.action.like("permit.%")))).all()
        assert list(permits) == []  # nothing was granted or consumed yet
    assert (await load(Application, app_id)).stage == Stage.ready


async def test_the_full_path_clears_the_runner_then_records_evidence():
    app_id, token_id = await ready_app()
    attempt_id = await cleared(app_id, token_id)
    attempt = await load(DispatchAttempt, attempt_id)
    assert attempt.status == DispatchStatus.handed_off and attempt.permit_id and attempt.started_at
    assert (await load(Application, app_id)).stage == Stage.applying
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        status = await browser.record_result(s, attempt, "submitted", CONFIRMED, now=NOW + timedelta(minutes=2))
        await s.commit()
    assert status == DispatchStatus.sent
    app = await load(Application, app_id)
    assert app.stage == Stage.submitted and app.confirmation_evidence[0].value.startswith("Thank you")
    task = await task_of(app_id)
    assert task.status == AgentTaskStatus.done and task.result["outcome"] == "submitted"
    async with maker()() as s:
        trail = list((await s.scalars(select(AuditEvent.action))).all())
    for action in ("browser.task_queued", "browser.task_claimed", "permit.granted", "permit.consumed",
                   "browser.cleared", "dispatch.sent"):
        assert action in trail


async def test_dispatch_refuses_without_a_consumed_permit_for_this_packet_hash():
    app_id, token_id = await ready_app()
    async with maker()() as s:
        await dispatch.queue(s, app_id, now=NOW)
        await s.commit()
    task = await task_of(app_id)
    async with maker()() as s:
        await browser.mark_task_claimed(s, task.id, token_id=token_id, now=NOW)
        app = await s.get(Application, app_id)
        packet = await packets.current(s, app_id)
        attempt = DispatchAttempt(application_id=app_id, packet_id=packet.id, packet_hash=packet.content_hash,
                                  channel=app.channel, status=DispatchStatus.reserved, permit_id=None)
        s.add(attempt)
        await s.flush()
        request = DispatchRequest(attempt_id=str(attempt.id), application_id=str(app_id),
                                  packet_hash=packet.content_hash, packet=packet.contents)
        out = await (await registry.get(s, "browser")).dispatch(request)
        assert out.status == "failed" and "permit" in out.error
        wrong = DispatchRequest(attempt_id=str(attempt.id), application_id=str(app_id), packet_hash="0" * 64,
                                packet=packet.contents)
        assert (await (await registry.get(s, "browser")).dispatch(wrong)).status == "failed"


async def test_a_report_without_a_consumed_permit_is_refused():
    app_id, _ = await ready_app()
    async with maker()() as s:
        app = await s.get(Application, app_id)
        packet = await packets.current(s, app_id)
        attempt = DispatchAttempt(application_id=app_id, packet_id=packet.id, packet_hash=packet.content_hash,
                                  channel=app.channel, status=DispatchStatus.reserved, started_at=NOW)
        s.add(attempt)
        await s.flush()
        with pytest.raises(browser.UnpermittedReport) as info:
            await browser.record_result(s, attempt, "submitted", CONFIRMED, now=NOW)
        assert info.value.code == "no_permit"
        await s.rollback()


async def test_a_report_before_the_runner_was_cleared_is_refused():
    app_id, token_id = await ready_app()
    async with maker()() as s:
        await dispatch.queue(s, app_id, now=NOW)
        await s.commit()
    task = await task_of(app_id)
    async with maker()() as s:
        await browser.mark_task_claimed(s, task.id, token_id=token_id, now=NOW)
        queued = await dispatch.queue(s, app_id, runner_token_id=token_id, agent_task_id=task.id, now=NOW)
        await s.commit()
        attempt = await s.get(DispatchAttempt, queued.attempt.id)
        with pytest.raises(browser.UnpermittedReport):  # reserved, never started: dispatch has not cleared it
            await browser.record_result(s, attempt, "submitted", CONFIRMED, now=NOW)
        await s.rollback()


async def test_a_changed_packet_during_the_wait_cancels_the_clearance():
    app_id, token_id = await ready_app()
    async with maker()() as s:
        await dispatch.queue(s, app_id, now=NOW)
        await s.commit()
    task = await task_of(app_id)
    async with maker()() as s:
        await browser.mark_task_claimed(s, task.id, token_id=token_id, now=NOW)
        queued = await dispatch.queue(s, app_id, runner_token_id=token_id, agent_task_id=task.id, now=NOW)
        await s.commit()
        attempt_id = queued.attempt.id
    async with maker()() as s:  # a new answer: the old packet can no longer go out
        app = await s.get(Application, app_id)
        await packets.build(s, app, browser_draft().__class__(
            channel="browser", destination_url="https://boards.greenhouse.io/acme/jobs/1",
            sending_identity="owner@example.com",
            answers=[packets.DraftAnswer(question="Notice period", value="Two months")]), actor="owner", now=NOW)
        await s.commit()
    async with maker()() as s:
        assert await dispatch.run(s, attempt_id, now=NOW) == DispatchStatus.cancelled
    assert (await load(DispatchAttempt, attempt_id)).status == DispatchStatus.cancelled


# ----- an uncertain attempt is never handed to a runner again -------------------------------------


async def test_an_uncertain_browser_attempt_is_never_queued_or_claimed_again():
    app_id, token_id = await ready_app()
    attempt_id = await cleared(app_id, token_id)
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        status = await browser.record_result(s, attempt, "uncertain", None, detail="the page froze after Submit",
                                             now=NOW)
        await s.commit()
    assert status == DispatchStatus.unknown
    assert (await load(Application, app_id)).stage == Stage.submitted_unconfirmed
    # Nothing can queue a new task: not the owner's button, not the worker, not a direct call.
    async with maker()() as s:
        denied = await dispatch.queue(s, app_id, now=NOW)
        assert denied.status == "denied" and denied.code == "already_handed_over"
        with pytest.raises(browser.BrowserError) as info:
            await browser.queue_task(s, app_id, now=NOW)
        assert info.value.code == "already_handed_over"
        assert await browser.queue_approved_tasks(s, now=NOW) == []
        await s.rollback()
    # A task that was already waiting for a runner is withdrawn when a runner tries to claim it.
    async with maker()() as s:
        stray = AgentTask(type="apply", application_id=app_id, status=AgentTaskStatus.queued,
                          payload={"packet_hash": "x"})
        s.add(stray)
        await s.flush()
        with pytest.raises(browser.BrowserError):
            await browser.mark_task_claimed(s, stray.id, token_id=token_id, now=NOW)
        assert stray.status == AgentTaskStatus.cancelled
        await s.commit()
    # The periodic reconcile never dispatches again either: still exactly one attempt.
    async with maker()() as s:
        await dispatch.tick(s, now=NOW + timedelta(hours=1))
    assert len(await attempts_of(app_id)) == 1


async def test_a_runner_reporting_submitted_without_evidence_is_uncertain_not_sent():
    app_id, token_id = await ready_app()
    attempt_id = await cleared(app_id, token_id)
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        status = await browser.record_result(s, attempt, "submitted", None, now=NOW)
        await s.commit()
    assert status == DispatchStatus.unknown
    assert (await load(Application, app_id)).stage == Stage.submitted_unconfirmed
    # The owner's own mark is not runner evidence either.
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        owner_like = Evidence(kind="owner_marked", value="trust me")
        assert await browser.record_result(s, attempt, "submitted", owner_like, now=NOW) == DispatchStatus.unknown


async def test_a_runner_failure_settles_as_not_sent_and_is_not_retried():
    app_id, token_id = await ready_app()
    attempt_id = await cleared(app_id, token_id)
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        assert await browser.record_result(s, attempt, "failed", None, detail="form rejected the file",
                                           now=NOW) == DispatchStatus.failed
        await s.commit()
    assert (await load(Application, app_id)).stage == Stage.ready
    assert len(await attempts_of(app_id)) == 1  # no automatic second attempt
    assert (await task_of(app_id)).status == AgentTaskStatus.failed


async def test_a_second_report_on_a_settled_attempt_changes_nothing():
    app_id, token_id = await ready_app()
    attempt_id = await cleared(app_id, token_id)
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        await browser.record_result(s, attempt, "submitted", CONFIRMED, now=NOW)
        assert await browser.record_result(s, attempt, "failed", None, now=NOW) == DispatchStatus.sent
        await s.commit()
    assert (await load(Application, app_id)).stage == Stage.submitted


# ----- reconcile, each way ------------------------------------------------------------------------


async def uncertain_attempt(employer: str = "Acme Example") -> tuple[uuid.UUID, uuid.UUID]:
    app_id, token_id = await ready_app(employer=employer)
    attempt_id = await cleared(app_id, token_id)
    return app_id, attempt_id


async def check(attempt_id, now):
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        result = await reconcile.check(s, attempt, now=now)
        await s.commit()
        return result


async def test_reconcile_with_nothing_yet_waits_then_asks_the_owner_and_never_resends():
    app_id, attempt_id = await uncertain_attempt()
    assert await check(attempt_id, NOW + timedelta(minutes=20)) == "waiting"
    async with maker()() as s:
        assert (await s.scalars(select(PendingAction).where(PendingAction.type == PendingActionType.confirm_submission)
                                )).first() is None  # still inside the watch window
    assert await check(attempt_id, NOW + timedelta(hours=25)) == "waiting"  # reconcile.confirmation_wait_hours = 24
    async with maker()() as s:
        asked = (await s.scalars(select(PendingAction).where(PendingAction.type == PendingActionType.confirm_submission,
                                                             PendingAction.status == PendingStatus.open))).all()
        assert len(asked) == 1 and asked[0].detail["channel"] == "browser"
        tick = await dispatch.tick(s, now=NOW + timedelta(hours=26))
        assert not tick.sent and not tick.queued
    assert len(await attempts_of(app_id)) == 1
    assert (await task_of(app_id)).status == AgentTaskStatus.claimed  # nobody is asked to submit again


async def test_reconcile_settles_from_the_runners_own_late_evidence():
    app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        task = await task_of(app_id)
        task = await s.get(AgentTask, task.id)
        task.result = {"attempt_id": str(attempt_id), "outcome": "submitted", "evidence": CONFIRMED.model_dump()}
        await s.commit()
    assert await check(attempt_id, NOW + timedelta(minutes=20)) == "sent"
    assert (await load(DispatchAttempt, attempt_id)).evidence.kind == "confirmation_page"
    assert (await load(Application, app_id)).stage == Stage.submitted


async def test_reconcile_settles_from_a_confirmation_email_recorded_by_mail_sync():
    app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        app = await s.get(Application, app_id)
        before = Evidence(kind="confirmation_email", value="old", at=(NOW - timedelta(days=3)).isoformat())
        app.confirmation_evidence = [before]  # an older email is not evidence for this attempt
        await s.commit()
    assert await check(attempt_id, NOW + timedelta(minutes=20)) == "waiting"
    async with maker()() as s:
        app = await s.get(Application, app_id)
        app.confirmation_evidence = [*app.confirmation_evidence, Evidence(
            kind="confirmation_email", value="msg-77", at=(NOW + timedelta(minutes=5)).isoformat())]
        await s.commit()
    assert await check(attempt_id, NOW + timedelta(minutes=40)) == "sent"
    assert (await load(DispatchAttempt, attempt_id)).evidence.value == "msg-77"


async def test_reconcile_settles_from_a_classified_confirmation_thread():
    app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        s.add(MailThread(provider_thread_id="t-1", provider_message_ids=["m-1", "m-2"], application_id=app_id,
                         classification=MailClassification.confirmation, needs_review=False,
                         last_message_at=NOW + timedelta(minutes=3)))
        await s.commit()
    assert await check(attempt_id, NOW + timedelta(minutes=20)) == "sent"
    assert (await load(DispatchAttempt, attempt_id)).evidence.kind == "confirmation_email"


async def test_reconcile_a_thread_needing_review_or_older_than_the_attempt_is_not_evidence():
    app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        s.add(MailThread(provider_thread_id="t-1", application_id=app_id,
                         classification=MailClassification.confirmation, needs_review=True,
                         last_message_at=NOW + timedelta(minutes=3)))
        s.add(MailThread(provider_thread_id="t-2", application_id=app_id,
                         classification=MailClassification.confirmation, needs_review=False,
                         last_message_at=NOW - timedelta(days=2)))
        await s.commit()
    assert await check(attempt_id, NOW + timedelta(minutes=20)) == "waiting"


async def test_reconcile_settles_not_sent_when_the_runner_said_it_never_submitted():
    app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        task = await s.get(AgentTask, (await task_of(app_id)).id)
        task.result = {"attempt_id": str(attempt_id), "outcome": "failed", "detail": "blocked at a captcha"}
        await s.commit()
    assert await check(attempt_id, NOW + timedelta(minutes=20)) == "not_sent"
    assert (await load(Application, app_id)).stage == Stage.ready
    assert len(await attempts_of(app_id)) == 1


async def test_the_owner_settles_an_uncertain_browser_attempt():
    _app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        assert await reconcile.decide(s, attempt, "sent", actor="owner", reference="REF-42", now=NOW) == "sent"
        await s.commit()
    assert (await load(DispatchAttempt, attempt_id)).evidence.value == "REF-42"
    other_app, other_attempt = await uncertain_attempt("Other Example")
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, other_attempt)
        assert await reconcile.decide(s, attempt, "not_sent", actor="owner", note="nothing arrived", now=NOW) \
            == "not_sent"
        await s.commit()
    assert (await load(Application, other_app)).stage == Stage.ready


async def test_a_late_runner_report_settles_an_attempt_already_uncertain():
    app_id, attempt_id = await uncertain_attempt()
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        await browser.record_result(s, attempt, "uncertain", None, now=NOW)
        await s.commit()
    async with maker()() as s:
        attempt = await s.get(DispatchAttempt, attempt_id)
        assert await browser.record_result(s, attempt, "submitted", CONFIRMED, now=NOW) == DispatchStatus.sent
        await s.commit()
    assert (await load(Application, app_id)).stage == Stage.submitted


# ----- tasks --------------------------------------------------------------------------------------


async def test_only_an_approved_verified_browser_packet_gets_a_task():
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, now=NOW)
        await packets.build(s, app, browser_draft(), actor="owner", now=NOW)  # not approved
        await s.commit()
        with pytest.raises(browser.BrowserError) as info:
            await browser.queue_task(s, app.id, now=NOW)
        assert info.value.code == "not_approved"
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, employer="Other Example", now=NOW)
        built = await packets.build(s, app, browser_draft("https://elsewhere.example.org/apply"), actor="owner",
                                    now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="browser", actor="owner", now=NOW)
        await s.commit()
        with pytest.raises(browser.BrowserError) as info:
            await browser.queue_task(s, app.id, now=NOW)
        assert info.value.code == "destination_unverified"
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, employer="Third Example", now=NOW)
        built = await packets.build(s, app, email_draft(), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)
        await s.commit()
        with pytest.raises(browser.BrowserError) as info:
            await browser.queue_task(s, app.id, now=NOW)
        assert info.value.code == "channel_mismatch"


async def test_the_worker_queues_approved_browser_packets_once_and_expires_unclaimed_tasks():
    app_id, _ = await ready_app()
    async with maker()() as s:
        queued = await browser.queue_approved_tasks(s, now=NOW)
        assert len(queued) == 1
        assert await browser.queue_approved_tasks(s, now=NOW) == []  # not again
        assert await browser.expire_stale_tasks(s, now=NOW + timedelta(hours=23)) == []
        expired = await browser.expire_stale_tasks(s, now=NOW + timedelta(hours=25))  # runners.browser_task_expiry
        assert expired == [queued[0].id]
        await s.commit()
    assert (await task_of(app_id)).status == AgentTaskStatus.cancelled
    assert (await load(Application, app_id)).approved_packet_id is not None  # the approval stays


async def test_a_changed_packet_withdraws_the_old_task():
    app_id, _ = await ready_app()
    async with maker()() as s:
        first = await browser.queue_task(s, app_id, now=NOW)
        app = await s.get(Application, app_id)
        built = await packets.build(s, app, packets.PacketDraft(
            channel="browser", destination_url="https://boards.greenhouse.io/acme/jobs/1",
            sending_identity="owner@example.com",
            answers=[packets.DraftAnswer(question="Notice period", value="Two months")]), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="browser", actor="owner", now=NOW)
        second = await browser.queue_task(s, app_id, now=NOW)
        await s.commit()
        assert second.id != first.id and first.status == AgentTaskStatus.cancelled
        assert second.payload["packet_hash"] == built.packet.content_hash


def test_evidence_from_a_report():
    assert browser.evidence_from_report() is None
    assert browser.evidence_from_report(confirmation_text="  ").kind if browser.evidence_from_report(
        confirmation_text="  ") else True
    page = browser.evidence_from_report(confirmation_text="Received", screenshot_ref="s1", now=NOW)
    assert page.kind == "confirmation_page" and page.screenshot_ref == "s1"
    assert browser.evidence_from_report(confirmation_text="Received", reference="R-1").kind == "reference"
