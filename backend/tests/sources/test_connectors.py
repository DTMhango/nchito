"""Every connector against recorded fixtures (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.sources import registry  # noqa: F401  (imports every connector)
from app.sources.ats import AshbyConnector, GreenhouseConnector, LeverConnector, WorkableConnector
from app.sources.base import SearchContext, SourceError, registered_connectors
from app.sources.feeds import RssConnector, WeWorkRemotelyConnector
from app.sources.page import ManualConnector
from app.sources.remote import HimalayasConnector, RemotiveConnector
from app.sources.workday import WorkdayConnector, parse_posted_on
from tests.sources.support import FakeFetcher, fixture_text

pytestmark = pytest.mark.nodb

GH = "https://boards-api.greenhouse.io/v1/boards"


def ctx(**config) -> SearchContext:
    return SearchContext(campaign_id="c1", titles=[], keywords=[], locations=[], source_config=config)


def test_all_connectors_registered():
    assert set(registered_connectors()) >= {"greenhouse", "lever", "ashby", "workable", "workday", "himalayas",
                                            "remotive", "weworkremotely", "rss", "manual"}


async def test_greenhouse_search_fetch_check():
    f = FakeFetcher({
        f"{GH}/acme/jobs?content=true": (200, fixture_text("greenhouse_jobs.json")),
        f"{GH}/acme/jobs/8940982002?pay_transparency=true": (200, fixture_text("greenhouse_job.json")),
        f"{GH}/acme/jobs/8940982002": (200, "{}"),
        f"{GH}/acme/jobs/1": (404, "{}"),
        f"{GH}/acme/jobs/2": (503, ""),
    })
    c = GreenhouseConnector(f)
    jobs = await c.search(ctx(boards=["acme"]), None)
    assert len(jobs) == 2
    first = jobs[0]
    assert first.title and first.employer == "GitLab" and first.requisition_id == "7426"
    assert first.apply_method_hint == "greenhouse" and first.extra["listing_open"] is True
    assert "<" not in first.raw_text and first.posted_at and first.posted_at.tzinfo
    one = await c.fetch("https://job-boards.greenhouse.io/acme/jobs/8940982002")
    assert one.title == first.title
    assert await c.check_open("https://job-boards.greenhouse.io/acme/jobs/8940982002") == "open"
    assert await c.check_open("https://job-boards.greenhouse.io/acme/jobs/1") == "closed"
    assert await c.check_open("https://job-boards.greenhouse.io/acme/jobs/2") == "unknown"
    assert await c.check_open("https://example.com/not-greenhouse") == "unknown"


async def test_greenhouse_since_filters_older_postings():
    f = FakeFetcher({f"{GH}/acme/jobs?content=true": (200, fixture_text("greenhouse_jobs.json"))})
    jobs = await GreenhouseConnector(f).search(ctx(boards=["acme"]), datetime(2030, 1, 1, tzinfo=UTC))
    assert jobs == []


async def test_board_failure_isolated_but_all_failing_raises():
    f = FakeFetcher({
        f"{GH}/good/jobs?content=true": (200, fixture_text("greenhouse_jobs.json")),
        f"{GH}/bad/jobs?content=true": (500, ""),
    })
    c = GreenhouseConnector(f)
    jobs = await c.search(ctx(boards=["bad", "good"]), None)
    assert len(jobs) == 2 and c.warnings and "bad" in c.warnings[0]
    with pytest.raises(SourceError):
        await GreenhouseConnector(f).search(ctx(boards=["bad"]), None)


async def test_lever():
    f = FakeFetcher({"https://api.lever.co/v0/postings/demo?mode=json": (200, fixture_text("lever_postings.json")),
                     "https://api.lever.co/v0/postings/demo/*": (404, "{}")})
    c = LeverConnector(f)
    jobs = await c.search(ctx(boards=[{"slug": "demo", "name": "Demo Co"}]), None)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.employer == "Demo Co" and j.apply_method_hint == "lever"
    assert j.posted_at and j.pay_text and "85,000" in j.pay_text
    assert await c.check_open("https://jobs.lever.co/demo/ad208490-4052-4f91-a57e-433f2d1e484b") == "closed"
    assert c.validate_config({"boards": ["x"]})["eu"] is False
    with pytest.raises(ValueError):
        c.validate_config({"boards": []})


async def test_ashby():
    f = FakeFetcher({"https://api.ashbyhq.com/posting-api/job-board/Ashby?includeCompensation=true":
                     (200, fixture_text("ashby_board.json"))})
    c = AshbyConnector(f)
    jobs = await c.search(ctx(boards=["Ashby"]), None)
    assert len(jobs) == 2 and jobs[0].apply_method_hint == "ashby" and jobs[0].pay_text
    url = jobs[0].source_url
    assert await c.check_open(url) == "open"
    assert await c.check_open("https://jobs.ashbyhq.com/Ashby/00000000-0000-0000-0000-000000000000") == "closed"
    assert (await c.fetch(url)).title == jobs[0].title


async def test_workable():
    f = FakeFetcher({"https://apply.workable.com/api/v1/widget/accounts/hf?details=true":
                     (200, fixture_text("workable_widget.json"))})
    c = WorkableConnector(f)
    jobs = await c.search(ctx(boards=["hf"]), None)
    assert len(jobs) == 2 and jobs[0].employer == "Hugging Face" and jobs[0].remote_hint == "remote"
    code = jobs[0].extra["shortcode"]
    assert await c.check_open(f"https://apply.workable.com/hf/j/{code}/") == "open"
    assert await c.check_open("https://apply.workable.com/hf/j/ZZZZ/") == "closed"
    assert await c.check_open("https://apply.workable.com/j/ZZZZ") == "unknown"


async def test_workday_paged_search_and_detail():
    f = FakeFetcher({
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs": (200, fixture_text("workday_jobs.json")),
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/*": (200, fixture_text("workday_job.json")),
    })
    c = WorkdayConnector(f, now=lambda: datetime(2026, 11, 26, 9, 0, tzinfo=UTC))
    jobs = await c.search(ctx(boards=["acme.wd5.myworkdayjobs.com/acme/Careers"]), None)
    assert len(jobs) == 2
    assert jobs[0].requisition_id == "JR2030637" and jobs[0].apply_method_hint == "workday"
    assert jobs[0].posted_at == datetime(2026, 11, 26, tzinfo=UTC)
    post = next(call for call in f.calls if call[0] == "POST")
    assert post[2]["limit"] == 20 and post[2]["offset"] == 0
    assert await c.check_open("https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/US-CA/Role_JR1") == "open"


async def test_workday_check_open_404_and_error():
    f = FakeFetcher({"https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/gone": (404, "")})
    c = WorkdayConnector(f)
    assert await c.check_open("https://acme.wd5.myworkdayjobs.com/Careers/job/gone") == "closed"
    assert await c.check_open("https://acme.wd5.myworkdayjobs.com/Careers/nope") == "unknown"


def test_workday_relative_dates():
    now = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    assert parse_posted_on("Posted 3 Days Ago", now) == datetime(2026, 11, 23, tzinfo=UTC)
    assert parse_posted_on("Posted 30+ Days Ago", now) is None
    assert parse_posted_on("Posted Yesterday", now) == datetime(2026, 11, 25, tzinfo=UTC)
    assert parse_posted_on(None, now) is None


async def test_himalayas_and_remotive():
    f = FakeFetcher({"https://himalayas.app/jobs/api?limit=20&offset=0": (200, fixture_text("himalayas.json")),
                     "https://remotive.com/api/remote-jobs": (200, fixture_text("remotive.json"))})
    him = await HimalayasConnector(f).search(ctx(), None)
    assert len(him) == 2 and him[0].remote_hint.startswith("remote") and him[0].posted_at
    rem = await RemotiveConnector(f).search(ctx(), None)
    assert len(rem) == 2 and rem[0].pay_text and rem[0].employer
    assert await RemotiveConnector(f).search(ctx(), datetime(2030, 1, 1, tzinfo=UTC)) == []


async def test_remotive_uses_campaign_queries_and_rejects_http_errors():
    f = FakeFetcher({"https://remotive.com/api/remote-jobs?search=actuary": (403, "blocked")})
    with pytest.raises(SourceError):
        await RemotiveConnector(f).search(SearchContext("c", ["actuary"], [], [], {}), None)


async def test_weworkremotely_and_generic_rss():
    xml = fixture_text("wwr.xml")
    f = FakeFetcher({"https://weworkremotely.com/remote-jobs.rss": (200, xml),
                     "https://careers.example.com/feed.xml": (200, xml)})
    jobs = await WeWorkRemotelyConnector(f).search(ctx(), None)
    assert len(jobs) == 2 and jobs[0].employer == "GitLab" and jobs[0].title.startswith("Renewals")
    assert jobs[0].remote_hint and "EMEA" in jobs[0].remote_hint
    rss = RssConnector(f)
    out = await rss.search(ctx(feed_url="https://careers.example.com/feed.xml", employer="Example Ltd"), None)
    assert len(out) == 2 and out[0].employer == "Example Ltd"
    with pytest.raises(ValueError):
        rss.validate_config({})
    with pytest.raises(ValueError):
        rss.validate_config({"feed_url": "ftp://x"})


async def test_feed_rejects_entity_declarations():
    bomb = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
            "<rss><channel><item><title>&a;</title></item></channel></rss>")
    f = FakeFetcher({"https://careers.example.com/feed.xml": (200, bomb)})
    with pytest.raises(SourceError):
        await RssConnector(f).search(ctx(feed_url="https://careers.example.com/feed.xml"), None)


PAGE = """<html><head><title>Fallback</title><script type="application/ld+json">%s</script></head>
<body><h1>Role</h1><p>Do things.</p></body></html>"""


async def test_manual_fetch_reads_json_ld_and_plain_pages():
    ld = {"@type": "JobPosting", "title": "Claims Analyst", "hiringOrganization": {"name": "Example Insurance"},
          "description": "<p>Analyse claims.</p>", "datePosted": "2026-11-20", "validThrough": "2026-12-31T00:00:00",
          "jobLocation": {"address": {"addressLocality": "Lusaka", "addressCountry": "ZM"}},
          "identifier": {"value": "REQ-9"}}
    plain = "<html><head><title>Plain role</title></head><body>Text here</body></html>"
    f = FakeFetcher({"https://careers.example.com/a": (200, PAGE % json.dumps(ld)),
                     "https://careers.example.com/b": (200, plain),
                     "https://careers.example.com/c": (200, "<p>This job has expired.</p>"),
                     "https://careers.example.com/d": (403, "")})
    c = ManualConnector(f)
    job = await c.fetch("https://careers.example.com/a")
    assert (job.title, job.employer, job.requisition_id) == ("Claims Analyst", "Example Insurance", "REQ-9")
    assert job.location_raw == "Lusaka, ZM" and job.deadline and job.deadline.isoformat() == "2026-12-31"
    page = await c.fetch("https://careers.example.com/b")
    assert page.title == "Plain role" and "Text here" in page.raw_text
    assert await c.check_open("https://careers.example.com/c") == "closed"
    assert await c.check_open("https://careers.example.com/b") == "unknown"
    assert await c.check_open("https://careers.example.com/d") == "unknown"
    assert await c.search(ctx(), None) == []
