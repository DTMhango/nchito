"""Every legal and illegal stage move, and what a move records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.apply import stages
from app.models.applications import Application, ApplicationEvent, PendingActionType, PendingStatus, Stage
from tests.tracking.helpers import make_app, make_job, make_pending

S = Stage
SENT = datetime(2026, 11, 20, tzinfo=UTC)
UNSENT = (S.shortlisted, S.tailoring, S.ready, S.applying, S.skipped, S.closed)

# Moves the owner may make by hand on an unsent application.
OWNER_LEGAL = {
    (S.shortlisted, S.tailoring), (S.shortlisted, S.ready), (S.shortlisted, S.skipped), (S.shortlisted, S.closed),
    (S.tailoring, S.shortlisted), (S.tailoring, S.ready), (S.tailoring, S.skipped), (S.tailoring, S.closed),
    (S.ready, S.tailoring), (S.ready, S.skipped), (S.ready, S.closed),
    (S.skipped, S.shortlisted), (S.closed, S.shortlisted),
}
# Moves the owner may make on an application that has gone out (applied_at set).
OWNER_LEGAL_SENT = {
    (S.submitted_unconfirmed, S.screening), (S.submitted_unconfirmed, S.interview),
    (S.submitted_unconfirmed, S.offer), (S.submitted_unconfirmed, S.rejected),
    (S.submitted_unconfirmed, S.withdrawn), (S.submitted_unconfirmed, S.closed),
    (S.submitted, S.screening), (S.submitted, S.interview), (S.submitted, S.offer), (S.submitted, S.rejected),
    (S.submitted, S.withdrawn), (S.submitted, S.closed),
    (S.screening, S.interview), (S.screening, S.offer), (S.screening, S.rejected), (S.screening, S.withdrawn),
    (S.screening, S.closed),
    (S.interview, S.offer), (S.interview, S.rejected), (S.interview, S.withdrawn), (S.interview, S.closed),
    (S.offer, S.accepted), (S.offer, S.rejected), (S.offer, S.withdrawn), (S.offer, S.closed),
}
# Only the apply process (via="system") may make these.
SYSTEM_ONLY = [
    (S.ready, S.applying), (S.applying, S.ready), (S.applying, S.submitted_unconfirmed),
    (S.applying, S.submitted), (S.applying, S.closed), (S.submitted_unconfirmed, S.submitted),
]


def _app(stage: Stage, sent: bool) -> Application:
    return Application(stage=stage, applied_at=SENT if sent else None)


@pytest.mark.nodb
@pytest.mark.parametrize("current", list(Stage))
@pytest.mark.parametrize("target", list(Stage))
def test_owner_moves_are_exactly_the_legal_ones(current: Stage, target: Stage) -> None:
    sent = current not in UNSENT
    verdict = stages.check_transition(_app(current, sent), target, "owner")
    legal = (current, target) in (OWNER_LEGAL_SENT if sent else OWNER_LEGAL)
    assert verdict.ok is legal, (current, target, verdict.reason)
    if not legal:
        assert verdict.reason


@pytest.mark.nodb
@pytest.mark.parametrize(("current", "target"), SYSTEM_ONLY)
def test_system_only_moves(current: Stage, target: Stage) -> None:
    sent = current == S.submitted_unconfirmed
    assert not stages.check_transition(_app(current, sent), target, "owner").ok
    assert stages.check_transition(_app(current, sent), target, "system").ok


@pytest.mark.nodb
def test_owner_cannot_drag_to_submitted_and_is_pointed_to_applied_myself() -> None:
    for start in (S.shortlisted, S.ready, S.submitted_unconfirmed):
        verdict = stages.check_transition(_app(start, False), S.submitted, "owner")
        assert not verdict.ok
        assert "applied myself" in (verdict.reason or "")


@pytest.mark.nodb
def test_nothing_leaves_an_end_state_except_reopening_unsent() -> None:
    for end in (S.accepted, S.rejected, S.withdrawn):
        assert stages.allowed_targets(_app(end, True)) == []
    assert stages.allowed_targets(_app(S.skipped, False)) == [S.shortlisted]
    assert stages.allowed_targets(_app(S.closed, False)) == [S.shortlisted]
    assert stages.allowed_targets(_app(S.closed, True)) == []


@pytest.mark.nodb
def test_post_submit_stage_needs_something_sent() -> None:
    assert not stages.check_transition(_app(S.ready, False), S.interview, "owner").ok
    assert stages.check_transition(_app(S.submitted, True), S.interview, "owner").ok


@pytest.mark.nodb
def test_applied_myself_only_reaches_submitted_from_unsent() -> None:
    for start in (S.shortlisted, S.tailoring, S.ready, S.applying, S.submitted_unconfirmed, S.skipped, S.closed):
        assert stages.check_transition(_app(start, False), S.submitted, "applied_myself").ok
    for start in (S.submitted, S.screening, S.interview, S.offer, S.accepted, S.rejected):
        assert not stages.check_transition(_app(start, True), S.submitted, "applied_myself").ok
    assert not stages.check_transition(_app(S.ready, False), S.interview, "applied_myself").ok


async def test_every_change_records_who_and_why(session) -> None:
    job = await make_job(session)
    app = await make_app(session, job)
    await stages.transition(session, app, S.tailoring, actor="owner", why="starting on the CV")
    await stages.transition(session, app, S.ready, actor="owner", why="CV done")
    await stages.transition(session, app, S.applying, actor="runner-pc", why="permit issued", via="system")
    await stages.transition(session, app, S.submitted, actor="runner-pc", why="form submitted", via="system")
    await session.commit()
    events = list(await session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
                                        .order_by(ApplicationEvent.created_at, ApplicationEvent.id)))
    assert [(e.kind, e.actor, e.detail["from"], e.detail["to"], e.detail["why"]) for e in events] == [
        ("stage_change", "owner", "shortlisted", "tailoring", "starting on the CV"),
        ("stage_change", "owner", "tailoring", "ready", "CV done"),
        ("stage_change", "runner-pc", "ready", "applying", "permit issued"),
        ("stage_change", "runner-pc", "applying", "submitted", "form submitted"),
    ]
    assert app.applied_at is not None


async def test_refused_move_changes_nothing_and_writes_no_event(session) -> None:
    app = await make_app(session, await make_job(session))
    with pytest.raises(stages.IllegalTransition) as err:
        await stages.transition(session, app, S.submitted, actor="owner", why="drag", via="owner")
    assert "applied myself" in err.value.reason
    assert app.stage == S.shortlisted
    assert await session.scalar(select(ApplicationEvent.id).where(ApplicationEvent.application_id == app.id)) is None


async def test_ending_an_application_expires_its_open_pending_actions(session) -> None:
    app = await make_app(session, await make_job(session))
    action = await make_pending(session, app, type_=PendingActionType.sign_in)
    await stages.transition(session, app, S.skipped, actor="owner", why="not for me")
    await session.refresh(action)
    assert action.status == PendingStatus.expired
    assert app.ended_at is not None


async def test_reopening_clears_the_end_date(session) -> None:
    app = await make_app(session, await make_job(session))
    await stages.transition(session, app, S.skipped, actor="owner", why="no")
    await stages.transition(session, app, S.shortlisted, actor="owner", why="changed my mind")
    assert app.ended_at is None


@pytest.mark.nodb
def test_snooze_returns_on_schedule() -> None:
    now = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    until = now + timedelta(days=2)
    assert stages.is_snoozed(until, now, deadlines=[], imminent_days=3)
    assert stages.is_snoozed(until, now + timedelta(days=1, hours=23), deadlines=[], imminent_days=3)
    assert not stages.is_snoozed(until, now + timedelta(days=2), deadlines=[], imminent_days=3)
    assert not stages.is_snoozed(None, now, deadlines=[], imminent_days=3)


@pytest.mark.nodb
def test_imminent_deadline_overrides_snooze_at_the_configured_distance() -> None:
    now = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    until = now + timedelta(days=10)
    near = (now + timedelta(days=2)).date()
    far = (now + timedelta(days=5)).date()
    assert not stages.is_snoozed(until, now, deadlines=[near], imminent_days=3)
    assert stages.is_snoozed(until, now, deadlines=[far], imminent_days=3)
    assert not stages.is_snoozed(until, now, deadlines=[far], imminent_days=7)
    assert stages.is_snoozed(until, now, deadlines=[None], imminent_days=7)
