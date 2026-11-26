"""JobSpy connector behind a fake scraper (no library, no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.sources import registry  # noqa: F401  (imports every connector)
from app.sources.base import SearchContext, SourceError
from app.sources.jobspy import JobSpyConnector, JobSpyScraper, row_to_raw
from tests.sources.support import FakeFetcher, fixture_text

pytestmark = pytest.mark.nodb

OPEN = (200, fixture_text("robots_allow_all.txt"))
ROWS = json.loads(fixture_text("jobspy_rows.json"))
INDEED = "https://zm.indeed.com"


class FakeScraper:
    def __init__(self, rows=None, fail_boards=()):
        self.rows = ROWS if rows is None else rows
        self.fail_boards = set(fail_boards)
        self.calls: list[tuple] = []

    def scrape(self, board, query, location, results, hours_old):
        self.calls.append((board, query, location, results, hours_old))
        if board in self.fail_boards:
            raise SourceError(f"{board}: blocked")
        return [dict(r, site=board) for r in self.rows]


def ctx(**config) -> SearchContext:
    return SearchContext(campaign_id="c1", titles=["Actuary", "Risk Analyst"], keywords=[], locations=["Lusaka"],
                         source_config={"enabled": True, **config})


def pages() -> FakeFetcher:
    return FakeFetcher({
        f"{INDEED}/robots.txt": OPEN,
        f"{INDEED}/viewjob?jk=abc": (200, fixture_text("careers_detail_ld.html")),
        f"{INDEED}/viewjob?jk=def": (200, "<html><body>Analyse claims</body></html>"),
        f"{INDEED}/viewjob?jk=gone": (200, fixture_text("careers_closed.html")),
        f"{INDEED}/viewjob?jk=wall": (403, "blocked"),
    })


def connector(scraper=None, fetcher=None, **kw):
    slept: list[float] = []

    async def sleep(seconds):
        slept.append(seconds)

    c = JobSpyConnector(fetcher or pages(), scraper=scraper or FakeScraper(), sleep=sleep, **kw)
    return c, slept


def test_missing_library_is_reported_not_raised_at_import():
    c = JobSpyConnector(FakeFetcher(), installed=lambda: False)
    with pytest.raises(ValueError, match="not installed"):
        c.validate_config({})
    ok = JobSpyConnector(FakeFetcher(), installed=lambda: True)
    assert ok.validate_config({"boards": ["linkedin"]})["boards"] == ["linkedin"]
    for bad in ({"boards": ["myspace"]}, {"results_per_board": 0}, {"board_delay_seconds": -1}):
        with pytest.raises(ValueError):
            ok.validate_config(bad)


async def test_search_without_library_or_when_off_is_a_clean_source_error():
    missing = JobSpyConnector(FakeFetcher(), installed=lambda: False)
    with pytest.raises(SourceError, match="not installed"):
        await missing.search(ctx(), None)
    off = JobSpyConnector(FakeFetcher(), scraper=FakeScraper())
    with pytest.raises(SourceError, match="switched off"):
        await off.search(SearchContext("c1", ["Actuary"], [], [], {}), None)
    with pytest.raises(SourceError, match="not installed"):
        JobSpyScraper().scrape("indeed", "x", None, 1, 1)


async def test_search_maps_rows_dedupes_and_verifies_links():
    c, _ = connector()
    jobs = await c.search(ctx(boards=["indeed"], results_per_board=10), None)
    by_title = {j.title: j for j in jobs}
    assert set(by_title) == {"Treaty Actuary", "Claims Analyst", "Blocked Role"}  # gone dropped, no-url skipped
    a = by_title["Treaty Actuary"]
    assert a.source_url == f"{INDEED}/viewjob?jk=abc"  # tracking parameter removed
    assert a.apply_url == "https://careers.example.com/jobs/treaty-actuary" and a.employer == "Kalumbila Re"
    assert a.remote_hint is None and a.pay_text is None and a.requisition_id is None  # unknown stays unknown
    assert a.extra["link_verified"] == "open" and a.extra["discovered_via"] == "jobspy"
    b = by_title["Claims Analyst"]
    assert b.pay_text == "ZMW 30000 - 45000 per monthly" and b.remote_hint == "remote"
    assert b.apply_url is None and b.posted_at == datetime(2026, 11, 21, tzinfo=UTC)
    assert by_title["Blocked Role"].extra["link_verified"] == "unknown"  # blocked page stays, unverified
    assert any("dropped" in w for w in c.warnings)


async def test_same_posting_from_two_queries_is_returned_once():
    scraper = FakeScraper()
    c, _ = connector(scraper)
    jobs = await c.search(ctx(boards=["indeed"]), None)
    assert len(scraper.calls) == 2 and len([j for j in jobs if j.title == "Treaty Actuary"]) == 1


async def test_politeness_delay_between_calls_and_result_caps():
    scraper = FakeScraper()
    c, slept = connector(scraper)
    await c.search(ctx(boards=["indeed", "google"], board_delay_seconds=7, results_per_board=2, verify_links=False),
                   None)
    assert len(scraper.calls) == 4 and slept == [7, 7, 7]
    assert {call[3] for call in scraper.calls} == {2} and {call[2] for call in scraper.calls} == {"Lusaka"}
    capped, _ = connector(FakeScraper())
    jobs = await capped.search(ctx(boards=["indeed"], results_per_board=2, verify_links=False), None)
    assert len(jobs) == 2


async def test_robots_disallow_leaves_links_unverified_and_unfetched():
    f = FakeFetcher({f"{INDEED}/robots.txt": (200, "User-agent: *\nDisallow: /viewjob\n")})
    c, _ = connector(fetcher=f)
    jobs = await c.search(ctx(boards=["indeed"]), None)
    assert len(jobs) == 4 and {j.extra["link_verified"] for j in jobs} == {"unknown"}
    assert [call[1] for call in f.calls] == [f"{INDEED}/robots.txt"]


async def test_one_failing_board_is_a_warning_all_failing_is_an_error():
    c, _ = connector(FakeScraper(fail_boards={"indeed"}))
    jobs = await c.search(ctx(boards=["indeed", "google"], verify_links=False), None)
    assert jobs and any("indeed" in w for w in c.warnings)
    dead, _ = connector(FakeScraper(fail_boards={"indeed"}))
    with pytest.raises(SourceError, match="blocked"):
        await dead.search(ctx(boards=["indeed"]), None)


async def test_since_drops_older_postings_and_limits_window():
    scraper = FakeScraper()
    c, _ = connector(scraper)
    jobs = await c.search(ctx(boards=["indeed"], verify_links=False), datetime(2026, 11, 21, tzinfo=UTC))
    assert {j.title for j in jobs} == {"Claims Analyst", "Gone Role", "Blocked Role"}
    assert scraper.calls[0][4] <= 72  # never asks for older than the setting allows


async def test_check_open_only_ever_proves_closed():
    c, _ = connector()
    assert await c.check_open(f"{INDEED}/viewjob?jk=gone") == "closed"
    assert await c.check_open(f"{INDEED}/viewjob?jk=abc") == "unknown"  # a 200 on a scraped board proves nothing
    assert await c.check_open(f"{INDEED}/viewjob?jk=wall") == "unknown"


def test_connector_declares_discovery_only_actions():
    assert JobSpyConnector.permitted_actions == {"search", "fetch", "check_open"}
    assert not any(a.startswith("apply") for a in JobSpyConnector.permitted_actions)


def test_row_with_nan_gaps_is_not_stated():
    nan = float("nan")
    raw = row_to_raw({"job_url": "https://x.example.com/j/1", "title": "T", "company": nan, "location": nan,
                      "description": nan, "date_posted": nan, "min_amount": nan, "max_amount": nan,
                      "is_remote": nan}, "google")
    assert raw is not None and raw.employer == "Unknown employer" and raw.location_raw is None
    assert raw.pay_text is None and raw.remote_hint is None and raw.posted_at is None
