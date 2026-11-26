"""Sources, watched employers, aliases and the board detector through the API and directly."""

from __future__ import annotations

import pytest

from app.pipeline import orchestrator
from app.sources.base import RateLimitSpec, SourceError
from app.sources.detect import detect, detect_from_url
from app.sources.http import HttpPolicy, HttpxFetcher, RateLimiter
from tests.sources.support import FakeFetcher, fixture_text


@pytest.mark.nodb
@pytest.mark.parametrize(("url", "connector", "slug"), [
    ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
    ("https://job-boards.greenhouse.io/acme", "greenhouse", "acme"),
    ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", "greenhouse", "acme"),
    ("https://boards.greenhouse.io/embed/job_board?for=acme", "greenhouse", "acme"),
    ("https://jobs.lever.co/acme/ad208490-4052-4f91-a57e-433f2d1e484b", "lever", "acme"),
    ("https://jobs.ashbyhq.com/acme", "ashby", "acme"),
    ("https://apply.workable.com/acme/j/ABC123/", "workable", "acme"),
    ("https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/x", "workday", "acme.wd5.myworkdayjobs.com/acme/Careers"),
    ("https://example.com/feed.rss", "rss", "https://example.com/feed.rss"),
])
def test_detect_from_url(url, connector, slug):
    found = detect_from_url(url)
    assert (found.connector, found.board_slug) == (connector, slug)


@pytest.mark.nodb
def test_detect_nothing_for_plain_sites():
    assert detect_from_url("https://example.com/careers").connector is None
    assert detect_from_url("not a url").connector is None


@pytest.mark.nodb
async def test_detect_reads_an_embedded_board_from_a_careers_page():
    page = '<html><iframe src="https://boards.greenhouse.io/embed/job_board?for=examplecorp"></iframe></html>'
    f = FakeFetcher({"https://careers.example.com/": (200, page)})
    found = await detect(f, "https://careers.example.com/")
    assert (found.connector, found.board_slug, found.confidence) == ("greenhouse", "examplecorp", 0.7)


@pytest.mark.nodb
async def test_rate_limiter_spaces_requests():
    now = [0.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(RateLimitSpec(requests_per_minute=60, burst=2), clock=lambda: now[0], sleep=sleep)
    for _ in range(4):
        await limiter.acquire()
    assert slept == [1.0, 1.0]  # the burst of two is free, then one per second


@pytest.mark.nodb
async def test_http_fetcher_retries_transient_errors_then_gives_up():
    import httpx

    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers["user-agent"])
        return httpx.Response(503) if len(attempts) < 3 else httpx.Response(200, text="ok")

    naps: list[float] = []

    async def nap(s: float) -> None:
        naps.append(s)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": "generic"})
    fetcher = HttpxFetcher(HttpPolicy(max_attempts=3), client=client, sleep=nap)
    assert await fetcher.get("https://x.example.com/") == (200, "ok")
    assert naps == [1.0, 2.0] and attempts[0] == "generic"

    always = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(SourceError):
        await HttpxFetcher(HttpPolicy(max_attempts=2), client=always, sleep=nap).get("https://x.example.com/")


@pytest.fixture
def web(owner_client):
    orchestrator.reset_deps()
    fetcher = FakeFetcher({
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true":
            (200, fixture_text("greenhouse_jobs.json")),
        "https://boards.greenhouse.io/acme": (200, "<html></html>"),
        "https://example.com/jobs": (404, ""),
    })
    orchestrator.configure(transport=fetcher)
    yield owner_client
    orchestrator.reset_deps()


async def test_source_crud_and_validation(web):
    body = {"connector": "greenhouse", "name": "Boards", "access": "api", "config": {}}
    created = (await web.post("/api/sources", json=body))
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["health"]["status"] == "unknown" and created.json()["enabled"] is True
    assert (await web.post("/api/sources", json={**body, "connector": "nope"})).status_code == 422
    assert (await web.post("/api/sources", json={**body, "access": "feed"})).status_code == 422
    assert (await web.post("/api/sources", json={"connector": "rss", "name": "R", "access": "feed",
                                                 "config": {}})).status_code == 422
    put = await web.put(f"/api/sources/{sid}", json={**body, "enabled": False})
    assert put.status_code == 200 and put.json()["enabled"] is False
    listing = (await web.get("/api/sources")).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == sid
    assert (await web.delete(f"/api/sources/{sid}")).status_code == 204
    assert (await web.get(f"/api/sources/{sid}")).status_code == 404


async def test_source_test_now_uses_watched_employers(web):
    sid = (await web.post("/api/sources", json={"connector": "greenhouse", "name": "Boards", "access": "api",
                                                "config": {}})).json()["id"]
    first = (await web.post(f"/api/sources/{sid}/test")).json()
    assert first["ok"] is False  # no boards yet
    await web.post("/api/watched-employers", json={"name": "Acme", "board_type": "greenhouse", "board_slug": "acme"})
    second = (await web.post(f"/api/sources/{sid}/test")).json()
    assert second["ok"] is True and second["sample_count"] == 2 and len(second["sample_titles"]) == 2


async def test_watched_employer_paste_a_url_add(web):
    r = await web.post("/api/watched-employers/from-url", json={"url": "https://boards.greenhouse.io/acme/jobs/1"})
    assert r.status_code == 201, r.text
    row = r.json()
    assert (row["board_type"], row["board_slug"], row["name"]) == ("greenhouse", "acme", "Acme")
    assert (await web.post("/api/watched-employers/from-url",
                           json={"url": "https://boards.greenhouse.io/acme"})).status_code == 409
    assert (await web.post("/api/watched-employers/from-url",
                           json={"url": "https://example.com/jobs"})).status_code == 422
    # a source of that board type now exists, so the sweep will read the watched employer
    sources = (await web.get("/api/sources")).json()["items"]
    assert [s["connector"] for s in sources] == ["greenhouse"]
    assert (await web.post("/api/watched-employers", json={"name": "X", "board_type": "myspace",
                                                           "board_slug": "x"})).status_code == 422


async def test_detect_endpoint_and_aliases(web):
    r = await web.post("/api/sources/detect", json={"url": "https://jobs.lever.co/acme"})
    assert r.json()["connector"] == "lever" and r.json()["board_slug"] == "acme"
    a = await web.post("/api/employer-aliases", json={"alias": "Acme Re", "canonical": "Acme"})
    assert a.status_code == 201
    assert (await web.post("/api/employer-aliases", json={"alias": "Acme Re", "canonical": "Other"})).status_code == 409
    assert (await web.get("/api/employer-aliases")).json()["total"] == 1
