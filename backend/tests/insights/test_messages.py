"""Insights count messages about applications (follow-ups, replies) on their own, never as applications: the
funnel, the approved step and the uncertain application sends ignore message packets."""

from __future__ import annotations

from datetime import date, timedelta

from app.apply import dispatch
from app.models.applications import DispatchStatus
from app.ops.insights import InsightFilters, build_insights
from tests.apply.fakes import sent
from tests.followups.helpers import channel, link_thread, maker, sent_app  # noqa: F401  (channel is a fixture)
from tests.followups.test_messages import SEND_AT, approve, draft, send

WINDOW = InsightFilters(since=date(2026, 1, 1), until=date.today() + timedelta(days=60))


async def _report():
    async with maker()() as s:
        return await build_insights(s, WINDOW)


async def test_a_sent_follow_up_is_a_message_not_an_application(channel):  # noqa: F811
    app_id = await sent_app()
    before = await _report()
    assert before.messages.sent == 0 and before.messages.by_kind == []
    await link_thread(app_id)
    msg_id = await draft(app_id, "info_reply")
    await approve(msg_id)
    result = await send(msg_id)
    channel.outcomes = [sent("msg-reply-1")]
    async with maker()() as s:
        assert await dispatch.run(s, result.attempt.id, now=SEND_AT) == DispatchStatus.sent
    after = await _report()
    assert after.messages.sent == 1 and [(r.key, r.count) for r in after.messages.by_kind] == [("info_reply", 1)]
    assert after.funnel == before.funnel  # still one application sent, approved once
    assert after.automation == before.automation
    assert after.spend.sent == before.spend.sent == 1


async def test_tailoring_runs_show_in_spend_by_run_kind(session):
    from app.models.search import Run, RunKind, RunStatus

    for kind, cost in ((RunKind.tailoring, 1_200), (RunKind.tailoring, 800), (RunKind.sweep, 500)):
        session.add(Run(kind=kind, trigger="manual", status=RunStatus.succeeded, cost_micros=cost, counts={}))
    session.add(Run(kind=RunKind.tailoring, trigger="manual", status=RunStatus.succeeded, cost_micros=9_999,
                    counts={}, dry_run=True))  # a dry run spends nothing real
    await session.commit()
    report = await build_insights(session, WINDOW)
    rows = [(r.kind, r.runs, r.micros) for r in report.spend.by_run_kind]
    assert rows == [("tailoring", 2, 2_000), ("sweep", 1, 500)]
