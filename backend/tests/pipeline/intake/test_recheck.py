"""Recheck one job: availability, material change detection, reassessment."""

from __future__ import annotations

from sqlalchemy import select

from app.models.search import Assessment, Availability, Job
from app.pipeline import orchestrator, recheck
from app.sources.base import SourceError
from tests.pipeline.intake.conftest import NOW
from tests.pipeline.intake.fakes import raw
from tests.pipeline.intake.test_orchestrator import EXTRACT, setup


async def seeded(session, rig, **conn):
    _, _, run = await setup(session, rig)
    conn_ = rig.connector("A", jobs=[raw(req="R1")], **conn)
    rig.llm.respond = EXTRACT
    await orchestrator.run_sweep(session, run)
    return (await session.scalar(select(Job))), conn_


async def test_unchanged_posting_reports_nothing_changed(session, rig):
    job, _ = await seeded(session, rig, availability="open")
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.availability_after == "open" and not out.content_changed and out.fetched
    assert job.last_checked_at == NOW


async def test_failed_check_is_unknown_never_closed(session, rig):
    job, conn = await seeded(session, rig, availability="open")
    conn.availability = SourceError("HTTP 503")
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.availability_after == "unknown" and job.availability == Availability.unknown


async def test_closed_posting_is_not_refetched(session, rig):
    job, _ = await seeded(session, rig, availability="closed")
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.availability_after == "closed" and not out.fetched and not out.content_changed


async def test_material_change_is_reextracted_and_reassessed(session, rig):
    job, conn = await seeded(session, rig, availability="open")
    assert await session.scalar(select(Assessment.id).where(Assessment.job_id == job.id)) is None
    calls = len(rig.llm.calls)
    conn.jobs[0] = raw(req="R1", text="Claims Analyst at Example Insurance. Now fully remote, with a new focus "
                                      "on fraud models. Python, SQL and Power BI are required.")
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert out.content_changed and "raw_text" in out.changed_fields
    assert len(rig.llm.calls) > calls  # new text, new extraction
    assert "fraud models" in job.raw_text
    assert await session.scalar(select(Assessment.id).where(Assessment.job_id == job.id)) is not None


async def test_unreadable_posting_leaves_content_alone(session, rig):
    job, conn = await seeded(session, rig, availability="open")
    before = job.raw_text

    async def boom(url):
        raise SourceError("blocked")

    conn.fetch = boom
    out = await recheck.recheck_job(session, job, actor="owner", llm=rig.llm)
    assert not out.fetched and out.note and job.raw_text == before


async def test_recheck_endpoint(owner_client, session, rig):
    job, _ = await seeded(session, rig, availability="open")
    await session.commit()
    r = await owner_client.post(f"/api/jobs/{job.id}/recheck")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["availability_after"] == "open" and body["content_changed"] is False
    assert body["job"]["id"] == str(job.id)
    assert (await owner_client.post(f"/api/jobs/{'0' * 8}-0000-0000-0000-{'0' * 12}/recheck")).status_code == 404
