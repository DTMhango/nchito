"""Insights aggregates on an invented dataset with known answers (fictional employers only)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.apply.approval import AUTO_APPROVER
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    ApplicationEvent,
    ApplicationPacket,
    ApplicationSpecVersion,
    Channel,
    DispatchAttempt,
    DispatchStatus,
    PendingActionType,
    Stage,
)
from app.models.kit import Track
from app.models.platform import AuditEvent, LedgerEntry, LedgerKind
from app.models.search import Assessment, AssessmentState, Campaign, Job, JobSighting, Source, SourceAccess
from app.schemas.json_types import (
    ApplicationSpec,
    FilterResult,
    PacketContents,
    PacketDestination,
    StructuredLocation,
)
from tests.tracking.helpers import make_pending

RANGE = {"since": "2026-11-01", "until": "2026-11-30"}


def d(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=UTC)


async def _job(session, name: str, country: str, source: Source, merged_into: Job | None = None) -> Job:
    job = Job(title=name, employer=f"{name} Ltd", canonical_employer=f"{name} Ltd", created_at=d(1),
              content_hash=uuid.uuid4().hex.ljust(64, "0"), location=StructuredLocation(country=country),
              merged_into_id=merged_into.id if merged_into else None)
    session.add(job)
    await session.flush()
    session.add(JobSighting(job_id=job.id, source_id=source.id, url=f"https://example.com/{name}",
                            first_seen_at=d(1), last_seen_at=d(1)))
    return job


def _assess(session, job, campaign, state, score=None, failed: str | None = None) -> None:
    results = [FilterResult(name=failed, result="fail", reason="no")] if failed else []
    session.add(Assessment(job_id=job.id, campaign_id=campaign.id, state=state, score=score, created_at=d(1),
                           filter_results=results))


async def _app(session, job, campaign, stage, created, applied=None, events=(), **kw) -> Application:
    app = Application(job_id=job.id, campaign_id=campaign.id, stage=stage, created_at=created, applied_at=applied,
                      **kw)
    session.add(app)
    await session.flush()
    for at, frm, to in events:
        session.add(ApplicationEvent(application_id=app.id, kind="stage_change", actor="system", created_at=at,
                                     detail={"from": frm, "to": to}))
    return app


def _packet(session, app, by: str) -> ApplicationPacket:
    contents = PacketContents(destination=PacketDestination(url="https://example.com/a", domain="example.com"),
                              sending_identity="owner@example.com", channel="email")
    packet = ApplicationPacket(application_id=app.id, version=1, content_hash="p" * 64, contents=contents,
                               approved_at=d(2), approved_by=by)
    session.add(packet)
    session.add(ApplicationSpecVersion(application_id=app.id, version=1, origin="tailor", spec=ApplicationSpec(),
                                       content_hash="s" * 64, created_by="system"))
    return packet


@pytest.fixture
async def world(session) -> SimpleNamespace:
    track = Track(key="analytics", name="Analytics")
    s1 = Source(connector="rss", name="Board One", access=SourceAccess.email)
    s2 = Source(connector="rss", name="Board Two", access=SourceAccess.email)
    session.add_all([track, s1, s2])
    await session.flush()
    camp = Campaign(name="Analytics roles", track_id=track.id)
    session.add(camp)
    await session.flush()
    j = {}
    for name, country, src in [("j1", "Zambia", s1), ("j2", "Zambia", s1), ("j3", "Kenya", s2),
                               ("j4", "Zambia", s1), ("j5", "Zambia", s2), ("j7", "Zambia", s1),
                               ("j8", "Kenya", s2), ("j9", "Zambia", s2)]:
        j[name] = await _job(session, name, country, src)
    j["j6"] = await _job(session, "j6", "Zambia", s1, merged_into=j["j1"])
    scored, out = AssessmentState.scored, AssessmentState.filtered_out
    for name, score in [("j1", 80), ("j2", 75), ("j3", 70), ("j4", 65), ("j5", 50)]:
        _assess(session, j[name], camp, scored, score)
    _assess(session, j["j7"], camp, out, failed="work_rights")
    _assess(session, j["j8"], camp, out, failed="work_rights")
    _assess(session, j["j9"], camp, out, failed="pay_floor")

    a1 = await _app(session, j["j1"], camp, Stage.interview, d(1), d(4), channel=Channel.email, events=[
        (d(2), "shortlisted", "ready"), (d(4), "ready", "submitted"), (d(8), "submitted", "screening"),
        (d(10), "screening", "interview")])
    p1 = _packet(session, a1, AUTO_APPROVER)
    a2 = await _app(session, j["j2"], camp, Stage.rejected, d(1), d(5), channel=Channel.email, events=[
        (d(5), "shortlisted", "submitted"), (d(15), "submitted", "rejected")])
    _packet(session, a2, "owner")
    await _app(session, j["j3"], camp, Stage.submitted, d(2), d(3), applied_outside=True, origin="owner")
    await _app(session, j["j4"], camp, Stage.shortlisted, d(2), snoozed_until=d(28))
    await _app(session, j["j1"], camp, Stage.submitted, d(6), d(7))  # a second application: ignored
    await _app(session, j["j6"], camp, Stage.submitted, d(3), d(4))  # job merged away: ignored

    for day, stage, model, micros in [(3, "assess", "m1", 1_000_000), (4, "tailor", "m2", 3_000_000),
                                      (9, "tailor", "m2", 2_000_000)]:
        session.add(LedgerEntry(kind=LedgerKind.reconciliation, amount_micros=micros, currency="USD", stage=stage,
                                model=model, created_at=d(day)))
    session.add(LedgerEntry(kind=LedgerKind.reservation, amount_micros=9_000_000, currency="USD", stage="assess",
                            model="m1", created_at=d(3)))
    session.add(LedgerEntry(kind=LedgerKind.reconciliation, amount_micros=7_000_000, currency="USD",
                            stage="assess", model="m1", created_at=datetime(2026, 9, 1, tzinfo=UTC)))

    await make_pending(session, None, type_=PendingActionType.captcha, created_at=d(5))
    await make_pending(session, None, type_=PendingActionType.captcha, created_at=d(6))
    await make_pending(session, None, type_=PendingActionType.sign_in, created_at=d(6))
    await make_pending(session, None, type_=PendingActionType.approve, created_at=d(6))
    for reason in ("outside hours", "outside hours", "no packet"):
        session.add(AuditEvent(actor="runner:x", action="gateway.permit_denied", detail={"reason": reason},
                               created_at=d(7)))
    await session.flush()
    session.add(DispatchAttempt(application_id=a1.id, packet_id=p1.id, packet_hash="p" * 64,
                                channel=Channel.email, status=DispatchStatus.unknown, created_at=d(4)))
    await session.commit()
    return SimpleNamespace(track=track, s1=s1, s2=s2, camp=camp)


async def get(client, **params) -> dict:
    r = await client.get("/api/insights", params={**RANGE, **params})
    assert r.status_code == 200, r.text
    return r.json()


def steps(report: dict) -> dict[str, int]:
    assert len(report["funnel"]) == 1
    return {s["key"]: s["count"] for s in report["funnel"][0]["steps"]}


async def test_funnel_counts_each_role_once(owner_client, world) -> None:
    report = await get(owner_client)
    assert steps(report) == {"found": 8, "passed_filters": 5, "scored_above": 4, "tailored": 2, "approved": 3,
                             "sent": 3, "reply": 2, "interview": 1, "offer": 0}
    sent = report["funnel"][0]["steps"][5]
    assert sent["of_previous"] == 1.0 and sent["of_found"] == 0.375


async def test_response_rate_flags_small_samples_at_default_and_other_value(owner_client, session, world) -> None:
    report = await get(owner_client)
    by_source = {r["label"]: r for r in report["response"]["by_source"]}
    assert report["response"]["min_sample"] == 10
    one = by_source["Board One"]
    assert (one["sent"], one["replies"], one["rate"], one["too_few"]) == (2, 2, 1.0, True)
    assert by_source["Board Two"]["sent"] == 1 and by_source["Board Two"]["too_few"] is True
    assert report["response"]["by_track"][0]["label"] == "Analytics"
    markets = {r["key"]: r for r in report["response"]["by_market"]}
    assert markets["Zambia"]["replies"] == 2 and markets["Kenya"]["replies"] == 0

    await settings_service.set_value(session, "insights.min_sample", 2, actor="test")
    await session.commit()
    again = await get(owner_client)
    flags = {r["label"]: r["too_few"] for r in again["response"]["by_source"]}
    assert flags == {"Board One": False, "Board Two": True}


async def test_time_in_stage_and_first_reply(owner_client, world) -> None:
    report = await get(owner_client)
    rows = {r["stage"]: r for r in report["time_in_stage"]["stages"]}
    assert rows["shortlisted"]["n"] == 2  # a1: 1 day, a2: 4 days
    assert rows["shortlisted"]["median_days"] == 2.5 and rows["shortlisted"]["p75_days"] == 3.25
    first = report["time_in_stage"]["first_reply"]
    assert (first["n"], first["median_days"], first["p75_days"]) == (2, 7.0, 8.5)  # 4 and 10 days after sending


async def test_spend_in_micros_by_period_with_week_start(owner_client, session, world) -> None:
    report = await get(owner_client)
    spend = report["spend"]
    assert spend["total_micros"] == 6_000_000 and spend["currency"] == "USD"
    assert spend["per_sent_micros"] == 2_000_000 and spend["per_interview_micros"] == 6_000_000
    weeks = {(r["period"], r["stage"]): r["micros"] for r in spend["rows"]}
    assert weeks == {("2026-11-02", "assess"): 1_000_000, ("2026-11-02", "tailor"): 3_000_000,
                     ("2026-11-09", "tailor"): 2_000_000}
    await settings_service.set_value(session, "insights.week_start", "sunday", actor="test")
    await session.commit()
    sunday = {r["period"] for r in (await get(owner_client))["spend"]["rows"]}
    assert sunday == {"2026-11-01", "2026-11-08"}
    month = (await get(owner_client, period="month"))["spend"]["rows"]
    assert {r["period"] for r in month} == {"2026-11-01"}


async def test_source_quality_counts_duplicates_apart(owner_client, world) -> None:
    rows = {r["name"]: r for r in (await get(owner_client))["sources"]}
    one, two = rows["Board One"], rows["Board Two"]
    assert (one["found"], one["duplicates"], one["passed"], one["applied"], one["replies"]) == (4, 1, 3, 2, 2)
    assert (two["found"], two["duplicates"], two["passed"], two["applied"], two["replies"]) == (4, 0, 2, 1, 0)


async def test_automation_outcomes_and_exclusions(owner_client, world) -> None:
    report = await get(owner_client)
    auto = report["automation"]
    assert (auto["auto"], auto["approved"], auto["manual"], auto["uncertain_sends"]) == (1, 1, 1, 1)
    assert {r["key"]: r["count"] for r in auto["blockers"]} == {"captcha": 2, "sign_in": 1}
    assert {r["key"]: r["count"] for r in auto["permits_denied"]} == {"outside hours": 2, "no packet": 1}
    assert {r["key"]: r["count"] for r in report["exclusions"]} == {"work_rights": 2, "pay_floor": 1}
    assert report["exclusions"][0]["key"] == "work_rights"


async def test_filters_narrow_every_section(owner_client, world) -> None:
    kenya = await get(owner_client, country="Kenya")
    assert steps(kenya)["found"] == 2 and steps(kenya)["sent"] == 1 and steps(kenya)["reply"] == 0
    assert kenya["automation"]["manual"] == 1 and kenya["automation"]["auto"] == 0
    by_source = await get(owner_client, source_id=str(world.s1.id))
    assert steps(by_source)["found"] == 4 and steps(by_source)["sent"] == 2
    by_track = await get(owner_client, track_id=str(world.track.id))
    assert steps(by_track)["found"] == 8
    other = await get(owner_client, campaign_id=str(uuid.uuid4()))
    assert other["funnel"] == [] and other["response"]["by_source"] == []
    assert steps(await get(owner_client, channel="email"))["sent"] == 2
    empty_range = await get(owner_client, since="2025-01-01", until="2025-01-31")
    assert empty_range["funnel"] == [] and empty_range["spend"]["total_micros"] == 0
    assert empty_range["spend"]["per_sent_micros"] is None


async def test_default_range_comes_from_settings(owner_client, session, world) -> None:
    body = (await owner_client.get("/api/insights")).json()
    assert date.fromisoformat(body["until"]) - date.fromisoformat(body["since"]) == timedelta(days=90)
    await settings_service.set_value(session, "insights.default_range_days", 30, actor="test")
    await session.commit()
    body = (await owner_client.get("/api/insights")).json()
    assert date.fromisoformat(body["until"]) - date.fromisoformat(body["since"]) == timedelta(days=30)


async def test_nothing_recorded_yet(owner_client) -> None:
    body = await get(owner_client)
    assert body["funnel"] == [] and body["sources"] == [] and body["spend"]["rows"] == []
    assert body["time_in_stage"]["first_reply"]["median_days"] is None

