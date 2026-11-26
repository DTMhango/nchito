"""De-duplication: requisition id, employer + title + location + similarity, suppression, reposts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models.applications import Application
from app.models.search import EmployerAlias, Job, JobSighting
from app.pipeline import dedupe, normalise
from tests.pipeline.intake.fakes import make_source, raw

NOW = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
THRESHOLD = 0.9

LONG = ("We are hiring a Claims Analyst to review motor and property claims, prepare monthly loss reports, "
        "work with the actuarial team, maintain Power BI dashboards and support audit requests. ") * 3


async def reg(session, source, rj):
    norm = await normalise.parse_with_aliases(session, rj)
    return await dedupe.register(session, norm, source_id=source.id, now=NOW, threshold=THRESHOLD)


async def counts(session):
    jobs = await session.scalar(select(func.count()).select_from(Job))
    sightings = await session.scalar(select(func.count()).select_from(JobSighting))
    return jobs, sightings


async def test_same_requisition_id_across_sources_is_one_job_with_two_sightings(session):
    a, b = make_source("A"), make_source("B", "lever")
    session.add_all([a, b])
    await session.flush()
    first = await reg(session, a, raw(req="R-100", text=LONG, url="https://a.example.com/1"))
    second = await reg(session, b, raw(req="R-100", text="Short excerpt only.", url="https://b.example.com/9",
                                       employer="Example Insurance Ltd"))
    assert first.outcome == dedupe.Outcome.new and second.outcome == dedupe.Outcome.seen
    assert second.job.id == first.job.id
    assert await counts(session) == (1, 2)


async def test_without_requisition_id_employer_title_location_and_text_decide(session):
    a, b = make_source("A"), make_source("B")
    session.add_all([a, b])
    await session.flush()
    one = await reg(session, a, raw(text=LONG, url="https://a.example.com/1"))
    same = await reg(session, b, raw(title="Claims Analyst (Remote)", text=LONG + " Apply today.",
                                     url="https://b.example.com/2", employer="EXAMPLE INSURANCE Inc."))
    other_place = await reg(session, b, raw(text=LONG, url="https://b.example.com/3", location="Nairobi, Kenya"))
    other_title = await reg(session, b, raw(title="Claims Manager", text=LONG, url="https://b.example.com/4"))
    other_text = await reg(session, b, raw(text="Entirely different duties: drive trucks and load cargo every day "
                                                "across the country border posts.", url="https://b.example.com/5"))
    assert same.job.id == one.job.id
    assert len({one.job.id, other_place.job.id, other_title.job.id, other_text.job.id}) == 4


async def test_employer_alias_merges_brands(session):
    a = make_source("A")
    session.add_all([a, EmployerAlias(alias="Example Re", canonical="Example Insurance")])
    await session.flush()
    one = await reg(session, a, raw(req="R-5", text=LONG, url="https://a.example.com/1"))
    two = await reg(session, a, raw(employer="Example Re", text=LONG, url="https://a.example.com/2"))
    assert one.job.canonical_employer == "Example Insurance" and two.job.id == one.job.id


async def test_seen_again_refreshes_the_sighting_and_keeps_one_row(session):
    a = make_source("A")
    session.add(a)
    await session.flush()
    rj = raw(req="R-1", text=LONG, url="https://a.example.com/1")
    first = await reg(session, a, rj)
    again = await reg(session, a, rj)
    assert again.outcome == dedupe.Outcome.seen and again.job.id == first.job.id
    assert await counts(session) == (1, 1)


async def test_applied_skipped_or_archived_jobs_never_resurface_as_new(session):
    a = make_source("A")
    session.add(a)
    await session.flush()
    applied = await reg(session, a, raw(req="R-1", title="Applied Role", text=LONG, url="https://a.example.com/1"))
    skipped = await reg(session, a, raw(req="R-2", title="Skipped Role", text=LONG, url="https://a.example.com/2"))
    archived = await reg(session, a, raw(req="R-3", title="Archived Role", text=LONG, url="https://a.example.com/3"))
    session.add(Application(job_id=applied.job.id))
    skipped.job.triage = "skipped"
    archived.job.triage = "archived"
    await session.flush()
    for r, url in ((raw(req="R-1", title="Applied Role", text=LONG, url="https://c.example.com/1"), 1),
                   (raw(req="R-2", title="Skipped Role", text=LONG, url="https://c.example.com/2"), 2),
                   (raw(title="Archived Role", text=LONG, url="https://c.example.com/3"), 3)):
        result = await reg(session, a, r)
        assert result.outcome == dedupe.Outcome.suppressed, url
    assert await session.scalar(select(func.count()).select_from(Job)) == 3


async def test_materially_changed_repost_is_flagged_not_duplicated(session):
    a = make_source("A")
    session.add(a)
    await session.flush()
    first = await reg(session, a, raw(req="R-9", text=LONG, url="https://a.example.com/1"))
    rewritten = ("Completely rewritten role: lead the new reinsurance pricing desk, own treaty renewals, "
                 "present to the board quarterly and manage three analysts across two offices. ") * 3
    again = await reg(session, a, raw(req="R-9", text=rewritten, url="https://a.example.com/1-repost"))
    assert again.outcome == dedupe.Outcome.reposted and again.flagged_repost
    assert again.job.id == first.job.id and dedupe.REPOSTED_TAG in again.job.tags
    assert again.job.raw_text.startswith("Completely rewritten")
    assert await counts(session) == (1, 2)


async def test_small_edit_is_not_a_repost(session):
    a = make_source("A")
    session.add(a)
    await session.flush()
    await reg(session, a, raw(req="R-9", text=LONG, url="https://a.example.com/1"))
    again = await reg(session, a, raw(req="R-9", text=LONG + " Closing soon.", url="https://a.example.com/1"))
    assert again.outcome == dedupe.Outcome.seen and not again.flagged_repost
    assert dedupe.REPOSTED_TAG not in again.job.tags


async def test_suppressed_job_with_changed_text_is_still_flagged(session):
    a = make_source("A")
    session.add(a)
    await session.flush()
    first = await reg(session, a, raw(req="R-9", text=LONG, url="https://a.example.com/1"))
    first.job.triage = "skipped"
    await session.flush()
    again = await reg(session, a, raw(req="R-9", text="Brand new description about an unrelated treasury role. " * 6,
                                      url="https://a.example.com/2"))
    assert again.outcome == dedupe.Outcome.suppressed and again.flagged_repost
    assert dedupe.REPOSTED_TAG in again.job.tags


def test_similarity_handles_excerpts_and_empty_text():
    assert dedupe.similarity(LONG, LONG[:150]) >= 0.9
    assert dedupe.similarity("", "") == 1.0
    assert dedupe.similarity("alpha beta gamma delta", "one two three four five") == 0.0
