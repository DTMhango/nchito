"""Posting change alerts (DESIGN.md 18.4): kinds detected from invented job versions, closed versus unknown,
stale packets invalidated on a material change, wording ignored, the scheduled scan and the endpoints."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.apply import approval, packets
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import (
    Application,
    ApplicationEvent,
    ApplicationPacket,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.changes import JobChange, JobVersion, JobWatch
from app.models.search import Availability, Job
from app.pipeline import changes, orchestrator, recheck
from app.schemas.json_types import JobFacets, Requirement, StructuredLocation
from app.sources.base import SourceError
from tests.apply.helpers import email_draft, setup_app, setup_campaign
from tests.pipeline.intake.conftest import NOW
from tests.pipeline.intake.fakes import raw
from tests.pipeline.intake.test_orchestrator import EXTRACT, setup
from tests.pipeline.matching.fakes import add_job


def kinds(found):
    return {c["kind"] for c in found}


# ----- change kinds from invented versions --------------------------------------------------------------


async def make(session, **over):
    kw = dict(deadline=date(2026, 12, 31), pay_state="stated", pay_min_minor=50_000_00, pay_max_minor=60_000_00,
              pay_currency="USD", pay_period="year", apply_method="portal", apply_url="https://jobs.example.com/1",
              requirements=[Requirement(text="Python", kind="required"), Requirement(text="Tableau", kind="preferred")],
              location=StructuredLocation(country="Zambia", city="Lusaka", raw="Lusaka"),
              facets={"work_model": {"value": "remote"}, "remote_scope": {"value": "worldwide"},
                      "required_skills": ["Python"]})
    kw.update(over)
    return await add_job(session, "Data Analyst", "Acme Example", **kw)


async def test_each_kind_is_detected_at_field_level(session):
    job = await make(session)
    before = changes.snapshot_of(job)

    def after(**edits):
        for key, value in edits.items():
            setattr(job, key, value)
        return changes.diff(before, changes.snapshot_of(job))

    moved = after(deadline=date(2026, 12, 10))
    assert kinds(moved) == {"deadline_moved"} and moved[0]["material"] and "2026-12-10" in moved[0]["summary"]
    job.deadline = date(2026, 12, 31)

    paid = after(pay_max_minor=45_000_00)
    assert kinds(paid) == {"pay_changed"} and "60,000" in paid[0]["summary"] and "45,000" in paid[0]["summary"]
    job.pay_max_minor = 60_000_00
    stated_to_gone = after(pay_state="not_stated", pay_min_minor=None, pay_max_minor=None)
    assert "not stated" in stated_to_gone[0]["summary"]
    job.pay_state, job.pay_min_minor, job.pay_max_minor = "stated", 50_000_00, 60_000_00

    harder = after(requirements=[Requirement(text="Python", kind="required"),
                                 Requirement(text="Five years of SQL", kind="required"),
                                 Requirement(text="Tableau", kind="preferred")])
    assert kinds(harder) == {"requirements_changed"} and harder[0]["material"]
    assert "five years of sql" in harder[0]["summary"].lower()
    nicer = after(requirements=[Requirement(text="Python", kind="required"),
                                Requirement(text="Tableau and Power BI", kind="preferred")])
    assert kinds(nicer) == {"requirements_changed"} and not nicer[0]["material"]  # preferred only
    job.requirements = [Requirement(text="Python", kind="required"), Requirement(text="Tableau", kind="preferred")]

    apply = after(apply_method="email", apply_url=None, apply_email="jobs@example.com")
    assert kinds(apply) == {"apply_method_changed"} and "portal -> email" in apply[0]["summary"]
    job.apply_method, job.apply_url, job.apply_email = "portal", "https://jobs.example.com/1", None

    moved_city = after(location=StructuredLocation(country="Kenya", city="Nairobi", raw="Nairobi"))
    assert kinds(moved_city) == {"location_changed"}
    job.location = StructuredLocation(country="Zambia", city="Lusaka", raw="Lusaka")

    job.facets = JobFacets.model_validate({"work_model": {"value": "remote"},
                                           "remote_scope": {"value": "country_only"}, "required_skills": ["Python"]})
    scoped = changes.diff(before, changes.snapshot_of(job))
    assert kinds(scoped) == {"eligibility_changed"} and "worldwide -> country only" in scoped[0]["summary"]


async def test_wording_only_is_recorded_but_not_material(session):
    job = await make(session)
    before = changes.snapshot_of(job)
    job.raw_text = job.raw_text + " We are a friendly team."
    found = changes.diff(before, changes.snapshot_of(job))
    assert kinds(found) == {"wording"} and not changes.is_material(found)
    job.raw_text = before_text = "  ".join(job.raw_text.split())  # reflow is not even a change
    assert changes.diff(changes.snapshot_of(job), changes.snapshot_of(job)) == [] and before_text


async def test_closed_needs_the_source_to_say_so_and_unknown_is_never_closed(session):
    job = await make(session)
    snap = changes.snapshot_of(job)
    assert kinds(changes.diff(snap, snap, availability_before="open", availability_after="closed")) == {"closed"}
    assert changes.diff(snap, snap, availability_before="open", availability_after="unknown") == []
    assert changes.diff(snap, snap, availability_before="unknown", availability_after="unknown") == []
    reopened = changes.diff(snap, snap, availability_before="closed", availability_after="open")
    assert kinds(reopened) == {"reopened"} and not changes.is_material(reopened)


async def test_recheck_with_a_failing_source_records_nothing_and_never_closes(session, rig):
    _, _, run = await setup(session, rig)
    conn = rig.connector("A", jobs=[raw(req="R1")], availability="open")
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    job = await session.scalar(select(Job))
    first = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert first.change_id is None  # first look: the baseline is stored, there is nothing to compare with
    assert await session.scalar(select(JobVersion.id).where(JobVersion.job_id == job.id)) is not None

    conn.availability = SourceError("HTTP 503")
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.availability_after == "unknown" and out.change_id is None
    assert await session.scalar(select(JobChange.id)) is None

    conn.availability = "closed"
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.availability_after == "closed" and out.change_kinds == ["closed"]
    row = await session.scalar(select(JobChange))
    assert row.material and row.changes[0]["summary"] == "The role is closed"


async def test_recheck_of_a_reworded_posting_is_wording_not_material(session, rig):
    _, _, run = await setup(session, rig)
    conn = rig.connector("A", jobs=[raw(req="R1")], availability="open")
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    job = await session.scalar(select(Job))
    await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    conn.jobs[0] = raw(req="R1", text=job.raw_text + " Our offices have good coffee.")
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.content_changed and out.change_kinds == ["wording"]
    assert not (await session.scalar(select(JobChange))).material


# ----- what a change does to an application -------------------------------------------------------------


def maker():
    return get_sessionmaker()


async def approved_app(employer="Acme Example"):
    async with maker()() as s:
        campaign = await setup_campaign(s)
        job, app = await setup_app(s, campaign, employer=employer, now=NOW)
        built = await packets.build(s, app, email_draft(), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)
        await s.commit()
        return job.id, app.id, built.packet.id


async def edit_and_record(job_id, **edits):
    async with maker()() as s:
        job = await s.get(Job, job_id)
        before = changes.snapshot_of(job)
        for key, value in edits.items():
            setattr(job, key, value)
        row = await changes.record_changes(s, job, before=before, availability_before=Availability.open,
                                           actor="system:watch", now=NOW + timedelta(days=1))
        await s.commit()
        return row.id if row else None


async def test_a_material_change_invalidates_the_approved_packet_and_asks_the_owner():
    job_id, app_id, packet_id = await approved_app()
    change_id = await edit_and_record(job_id, pay_max_minor=45_000_00, raw_text="Data Analyst at Acme. Pay cut.",
                                      content_hash="v2" * 32)
    async with maker()() as s:
        packet = await s.get(ApplicationPacket, packet_id)
        app = await s.get(Application, app_id)
        assert packet.invalidated_at is not None and "pay changed" in packet.invalidated_reason.lower()
        assert app.approved_packet_id is None and app.stage == Stage.ready
        action = (await s.scalars(select(PendingAction).where(PendingAction.application_id == app_id))).one()
        assert action.type == PendingActionType.follow_up and action.detail["kind"] == "posting_changed"
        assert action.detail["was_approved"] and action.detail["job_change_id"] == str(change_id)
        row = await s.get(JobChange, change_id)
        assert row.material and row.effects["invalidated_packets"] == [str(packet_id)]
        events = (await s.scalars(select(ApplicationEvent.kind).where(ApplicationEvent.application_id == app_id))).all()
        assert "posting_changed" in events
    # A second change updates the same open action rather than piling up.
    await edit_and_record(job_id, deadline=date(2026, 12, 5))
    async with maker()() as s:
        open_actions = (await s.scalars(select(PendingAction).where(
            PendingAction.application_id == app_id, PendingAction.status == PendingStatus.open))).all()
        assert len(open_actions) == 1


async def test_a_wording_change_leaves_the_approved_packet_alone():
    job_id, app_id, packet_id = await approved_app()
    change_id = await edit_and_record(job_id, raw_text="Data Analyst at Acme Example. A friendlier tone now.",
                                      content_hash="v2" * 32)
    async with maker()() as s:
        row = await s.get(JobChange, change_id)
        assert row.kinds == ["wording"] and not row.material and row.effects["invalidated_packets"] == []
        assert (await s.get(Application, app_id)).approved_packet_id == packet_id
        assert (await s.get(ApplicationPacket, packet_id)).invalidated_at is None
        assert (await s.scalars(select(PendingAction))).first() is None


async def test_a_closed_role_opens_an_action_but_keeps_the_packet():
    job_id, app_id, packet_id = await approved_app()
    async with maker()() as s:
        job = await s.get(Job, job_id)
        before = changes.snapshot_of(job)
        job.availability = Availability.closed
        row = await changes.record_changes(s, job, before=before, availability_before=Availability.open,
                                           actor="system:watch", now=NOW + timedelta(days=1))
        await s.commit()
        assert row.kinds == ["closed"] and row.effects["invalidated_packets"] == []
    async with maker()() as s:
        action = (await s.scalars(select(PendingAction))).one()
        assert action.detail["kind"] == "posting_closed" and action.detail["approved_packet_waiting"]
        assert (await s.get(Application, app_id)).approved_packet_id == packet_id  # the send gates refuse it anyway


async def test_a_submitted_application_is_only_noted_never_touched():
    job_id, app_id, packet_id = await approved_app()
    async with maker()() as s:
        (await s.get(Application, app_id)).stage = Stage.submitted
        await s.commit()
    await edit_and_record(job_id, pay_max_minor=1, content_hash="v3" * 32, raw_text="Cut.")
    async with maker()() as s:
        assert (await s.get(ApplicationPacket, packet_id)).invalidated_at is None
        assert (await s.scalars(select(PendingAction))).first() is None
        events = (await s.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app_id))).all()
        assert any(e.kind == "posting_changed" and e.detail["stage"] == "submitted" for e in events)


async def test_the_packet_is_judged_against_the_version_it_was_built_on():
    """A wording change first, then a harder requirement: the second is judged against the packet's own version."""
    job_id, _app_id, packet_id = await approved_app()
    await edit_and_record(job_id, raw_text="Data Analyst at Acme Example. A friendlier tone now.",
                          content_hash="v2" * 32)  # wording only: packet stays
    change = await edit_and_record(job_id, requirements=[Requirement(text="Ten years of Rust", kind="required")],
                                   raw_text="Data Analyst. Ten years of Rust.", content_hash="v3" * 32)
    async with maker()() as s:
        packet = await s.get(ApplicationPacket, packet_id)
        assert packet.invalidated_at is not None and "requirements" in packet.invalidated_reason.lower()
        assert (await s.get(JobChange, change)).material


# ----- the scheduled scan -------------------------------------------------------------------------------


async def test_the_scan_watches_the_roles_the_owner_cares_about_and_marks_failures_unknown(session, rig):
    _, _, run = await setup(session, rig)
    conn = rig.connector("A", jobs=[raw(req="R1"), raw(req="R2", title="Data Engineer")], availability="open")
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    jobs = (await session.scalars(select(Job).order_by(Job.title))).all()
    watched, other = jobs[0], jobs[1]
    session.add(Application(job_id=watched.id, stage=Stage.ready))
    await session.flush()
    assert await changes.watched_job_ids(session, NOW) == [watched.id]  # not the other, which has no application

    conn.availability = SourceError("HTTP 503")
    report = await changes.scan(session, now=NOW, deps=orchestrator.DEPS, llm=rig.llm)
    assert report.unknown == [watched.id] and not report.closed
    watch = await session.scalar(select(JobWatch).where(JobWatch.job_id == watched.id))
    assert watch.last_result == "unknown" and watched.availability == Availability.unknown
    assert await changes.watched_job_ids(session, NOW + timedelta(hours=1)) == []  # a failure waits the interval
    assert await changes.watched_job_ids(session, NOW + timedelta(hours=13)) == [watched.id]

    conn.availability = "closed"
    report = await changes.scan(session, now=NOW + timedelta(hours=13), deps=orchestrator.DEPS, llm=rig.llm)
    assert report.closed == [watched.id]
    await session.refresh(watch)  # written by an upsert, not through the identity map
    assert watch.last_result == "closed"
    assert await changes.watched_job_ids(session, NOW + timedelta(days=9)) == []  # a closed role is not rechecked
    assert other.id not in {w for w in await changes.watched_job_ids(session, NOW + timedelta(days=9))}


async def test_watch_settings_change_what_is_watched(session, rig):
    _, _, run = await setup(session, rig)
    rig.connector("A", jobs=[raw(req="R1")], availability="open")
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    job = await session.scalar(select(Job))
    session.add(Application(job_id=job.id, stage=Stage.submitted))
    await session.flush()
    assert await changes.watched_job_ids(session, NOW) == []  # submitted is not in the default stages
    await settings_service.set_value(session, "tracking.change_watch_stages", ["ready", "submitted"], actor="owner")
    assert await changes.watched_job_ids(session, NOW) == [job.id]
    await settings_service.set_value(session, "tracking.change_watch_enabled", False, actor="owner")
    assert await changes.watched_job_ids(session, NOW) == []
    await settings_service.set_value(session, "tracking.change_watch_enabled", True, actor="owner")
    job.pinned = True
    await settings_service.set_value(session, "tracking.change_watch_stages", [], actor="owner")
    assert await changes.watched_job_ids(session, NOW) == [job.id]  # pinned
    await settings_service.set_value(session, "tracking.change_watch_pinned", False, actor="owner")
    assert await changes.watched_job_ids(session, NOW) == []


async def test_batch_size_limits_one_pass(session, rig):
    _, _, run = await setup(session, rig)
    rig.connector("A", jobs=[raw(req=f"R{i}", title=f"Analyst {i}") for i in range(3)], availability="open")
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    for job in (await session.scalars(select(Job))).all():
        session.add(Application(job_id=job.id, stage=Stage.ready))
    await session.flush()
    assert len(await changes.watched_job_ids(session, NOW)) == 3
    await settings_service.set_value(session, "tracking.change_batch_size", 2, actor="owner")
    assert len(await changes.watched_job_ids(session, NOW)) == 2


# ----- endpoints ----------------------------------------------------------------------------------------


async def test_change_endpoints(owner_client, session, rig):
    _, _, run = await setup(session, rig)
    conn = rig.connector("A", jobs=[raw(req="R1")], availability="open")
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    job = await session.scalar(select(Job))
    await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    conn.availability = "closed"
    await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    await session.commit()

    r = await owner_client.get(f"/api/jobs/{job.id}/changes")
    assert r.status_code == 200
    body = r.json()
    assert body["changes"][0]["kinds"] == ["closed"] and body["changes"][0]["material"]
    assert body["changes"][0]["changes"][0]["summary"] == "The role is closed" and body["watch"] is None
    feed = (await owner_client.get("/api/job-changes")).json()
    assert [c["id"] for c in feed] == [body["changes"][0]["id"]]
    ack = await owner_client.post(f"/api/job-changes/{feed[0]['id']}/acknowledge")
    assert ack.status_code == 200 and ack.json()["acknowledged_at"]
    assert (await owner_client.get("/api/job-changes")).json() == []
    assert len((await owner_client.get("/api/job-changes?unacknowledged=false")).json()) == 1
    assert (await owner_client.get("/api/job-changes?material_only=true&unacknowledged=false")).json()
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await owner_client.get(f"/api/jobs/{missing}/changes")).status_code == 404
    assert (await owner_client.post(f"/api/job-changes/{missing}/acknowledge")).status_code == 404
