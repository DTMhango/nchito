"""Insights drill-through: the Applications and Matches lists hold exactly the rows a clicked number counted."""

from __future__ import annotations

import pytest

from tests.insights.test_insights import RANGE, get, steps, world  # noqa: F401  (fixture)

APP_STEPS = ["tailored", "approved", "sent", "reply", "interview", "offer"]
JOB_STEPS = ["found", "passed_filters", "scored_above"]


async def apps(client, **params) -> int:
    r = await client.get("/api/applications", params={**RANGE, **params})
    assert r.status_code == 200, r.text
    return r.json()["total"]


async def jobs(client, **params) -> int:
    r = await client.get("/api/jobs", params={**RANGE, **params})
    assert r.status_code == 200, r.text
    return r.json()["total"]


@pytest.mark.parametrize("params", [{}, {"country": "Kenya"}, {"channel": "email"}])
async def test_every_application_step_lists_what_it_counts(owner_client, world, params) -> None:  # noqa: F811
    counted = steps(await get(owner_client, **params))
    for step in APP_STEPS:
        assert await apps(owner_client, reached=step, **params) == counted[step], step


async def test_every_job_step_lists_what_it_counts(owner_client, world) -> None:  # noqa: F811
    counted = steps(await get(owner_client))
    for step in JOB_STEPS:
        assert await jobs(owner_client, reached=step) == counted[step], step


async def test_source_and_track_filters_drill_the_same_way(owner_client, world) -> None:  # noqa: F811
    by_source = steps(await get(owner_client, source_id=str(world.s1.id)))
    assert await apps(owner_client, source_id=str(world.s1.id), reached="sent") == by_source["sent"] == 2
    assert await jobs(owner_client, source_id=str(world.s1.id), reached="found") == by_source["found"] == 4
    by_track = steps(await get(owner_client, track_id=str(world.track.id)))
    assert await apps(owner_client, track_id=str(world.track.id), reached="reply") == by_track["reply"]


async def test_source_table_found_lists_roles_first_seen(owner_client, world) -> None:  # noqa: F811
    report = await get(owner_client)
    row = next(r for r in report["sources"] if r["source_id"] == str(world.s1.id))
    assert await jobs(owner_client, source_id=str(world.s1.id)) == row["found"]


async def test_no_drill_params_keep_the_plain_lists(owner_client, world) -> None:  # noqa: F811
    r = await owner_client.get("/api/applications")
    assert r.json()["total"] == 6  # every application, the ignored ones included
    r = await owner_client.get("/api/jobs")
    assert r.json()["total"] == 8  # merged role left out, as before
    assert (await owner_client.get("/api/applications", params={"reached": "found"})).status_code == 422
    assert (await owner_client.get("/api/jobs", params={"reached": "sent"})).status_code == 422
