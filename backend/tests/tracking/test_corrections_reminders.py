"""Merge, split, employer fixes, and the follow-up and stale reminders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.apply import reminders
from app.core.settings import service as settings_service
from app.models.applications import (
    ApplicationEvent,
    Contact,
    PendingAction,
    PendingActionType,
    PendingStatus,
    Stage,
)
from app.models.platform import AuditEvent, Notification
from app.models.search import EmployerAlias, Job, JobSighting
from app.pipeline import corrections
from tests.tracking.helpers import make_app, make_job, make_pending

NOW = datetime.now(UTC)


async def _sightings(session, job_id):
    return sorted(s.url for s in await session.scalars(select(JobSighting).where(JobSighting.job_id == job_id)))


async def test_merge_keeps_sightings_tags_contacts_and_application_history(owner_client, session) -> None:
    keep = await make_job(session, "Analyst", "Acme", url="https://a.example.com/1", tags=["remote"])
    dup = await make_job(session, "Analyst (repost)", "Acme", url="https://b.example.com/2", tags=["remote", "data"])
    app = await make_app(session, dup, Stage.submitted, applied_at=NOW)
    session.add(Contact(job_id=dup.id, name="Chola"))
    await session.commit()
    r = await owner_client.post(f"/api/jobs/{keep.id}/merge", json={"duplicate_ids": [str(dup.id)]})
    assert r.status_code == 200
    body = r.json()
    assert {s["url"] for s in body["sightings"]} == {"https://a.example.com/1", "https://b.example.com/2"}
    assert body["tags"] == ["remote", "data"] and body["application_id"] == str(app.id)
    await session.refresh(dup)
    await session.refresh(app)
    assert dup.merged_into_id == keep.id and dup.triage == "archived" and app.job_id == keep.id
    assert (await session.scalar(select(Contact))).job_id == keep.id
    events = await session.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id))
    kinds = [e.kind for e in events]
    assert "job_merged" in kinds
    audit = await session.scalar(select(AuditEvent).where(AuditEvent.action == "job.merge"))
    assert audit.actor == "owner" and audit.detail["loser"] == str(dup.id)
    # a merged job cannot be merged again or applied to
    assert (await owner_client.post(f"/api/jobs/{keep.id}/merge", json={"duplicate_ids": [str(dup.id)]})
            ).status_code == 409
    assert (await owner_client.post("/api/applications", json={"job_id": str(dup.id)})).status_code == 409


async def test_merge_then_split_restores_the_original(owner_client, session) -> None:
    keep = await make_job(session, "Analyst", "Acme", url="https://a.example.com/1", tags=["remote"])
    keep.notes = "my notes"
    dup = await make_job(session, "Analyst B", "Acme", url="https://b.example.com/2", tags=["data"])
    dup.notes = "dup notes"
    app = await make_app(session, dup, Stage.ready)
    contact = Contact(job_id=dup.id, name="Chola")
    session.add(contact)
    await session.commit()
    await owner_client.post(f"/api/jobs/{keep.id}/merge", json={"duplicate_ids": [str(dup.id)]})
    r = await owner_client.post(f"/api/jobs/{keep.id}/split", json={"sighting_urls": ["https://b.example.com/2"]})
    assert r.status_code == 200 and r.json()["id"] == str(dup.id)
    for obj in (keep, dup, app, contact):
        await session.refresh(obj)
    assert dup.merged_into_id is None and dup.triage == "new"
    assert await _sightings(session, keep.id) == ["https://a.example.com/1"]
    assert await _sightings(session, dup.id) == ["https://b.example.com/2"]
    assert (keep.tags, keep.notes) == (["remote"], "my notes") and dup.tags == ["data"]
    assert app.job_id == dup.id and contact.job_id == dup.id
    splits = list(await session.scalars(select(AuditEvent).where(AuditEvent.action == "job.split")))
    assert len(splits) == 1 and splits[0].detail["restored"] is True
    # and it can be merged again
    again = await owner_client.post(f"/api/jobs/{keep.id}/merge", json={"duplicate_ids": [str(dup.id)]})
    assert again.status_code == 200


async def test_split_of_a_sighting_that_was_never_merged_makes_a_new_job(owner_client, session) -> None:
    job = await make_job(session, "Analyst", "Acme", url="https://a.example.com/1", tags=["x"])
    session.add(JobSighting(job_id=job.id, url="https://wrong.example.com/9", first_seen_at=NOW, last_seen_at=NOW))
    await session.commit()
    r = await owner_client.post(f"/api/jobs/{job.id}/split", json={"sighting_urls": ["https://wrong.example.com/9"]})
    assert r.status_code == 200 and r.json()["id"] != str(job.id)
    assert [s["url"] for s in r.json()["sightings"]] == ["https://wrong.example.com/9"]
    assert r.json()["apply_url"] == "https://wrong.example.com/9" and r.json()["tags"] == ["x"]
    assert await _sightings(session, job.id) == ["https://a.example.com/1"]
    only = await owner_client.post(f"/api/jobs/{job.id}/split", json={"sighting_urls": ["https://a.example.com/1"]})
    assert only.status_code == 422  # would leave the job empty
    none = await owner_client.post(f"/api/jobs/{job.id}/split", json={"sighting_urls": ["https://nope"]})
    assert none.status_code == 404


async def test_merge_refuses_two_live_applications_and_self_merge(owner_client, session) -> None:
    a = await make_job(session, "A")
    b = await make_job(session, "B")
    await make_app(session, a, Stage.submitted, applied_at=NOW)
    await make_app(session, b, Stage.interview, applied_at=NOW)
    await session.commit()
    assert (await owner_client.post(f"/api/jobs/{a.id}/merge", json={"duplicate_ids": [str(b.id)]})).status_code == 409
    assert (await owner_client.post(f"/api/jobs/{a.id}/merge", json={"duplicate_ids": [str(a.id)]})).status_code == 422
    assert (await session.get(Job, b.id)).merged_into_id is None


async def test_fix_employer_updates_aliases_and_calls_the_hook(owner_client, session) -> None:
    seen: list[set[str]] = []

    async def hook(_session, employers: set[str]) -> None:
        seen.append(employers)

    corrections.set_conflict_reevaluator(hook)
    try:
        wrong = await make_job(session, "Analyst", "Acme Mining Ltd", canonical="Acme Retail")
        sibling = await make_job(session, "Driver", "Acme Mining Ltd", canonical="Acme Retail")
        elsewhere = await make_job(session, "Clerk", "Other Co", canonical="Other Co")
        await session.commit()
        r = await owner_client.post(f"/api/jobs/{wrong.id}/employer", json={"canonical_employer": "Acme Mining"})
        assert r.status_code == 200 and r.json()["canonical_employer"] == "Acme Mining"
        for j in (wrong, sibling, elsewhere):
            await session.refresh(j)
        assert (wrong.canonical_employer, sibling.canonical_employer, elsewhere.canonical_employer) == (
            "Acme Mining", "Acme Mining", "Other Co")
        alias = await session.scalar(select(EmployerAlias))
        assert (alias.alias, alias.canonical) == ("Acme Mining Ltd", "Acme Mining")
        assert seen == [{"Acme Retail", "Acme Mining"}]
        # the alias now applies to jobs created later
        assert await corrections.canonical_employer(session, "acme mining ltd") == "Acme Mining"
        again = await owner_client.post(f"/api/jobs/{wrong.id}/employer",
                                        json={"canonical_employer": "Acme Group", "remember_alias": False})
        assert again.json()["canonical_employer"] == "Acme Group"
        assert (await session.scalar(select(EmployerAlias))).canonical == "Acme Mining"
        audit = list(await session.scalars(select(AuditEvent).where(AuditEvent.action == "job.employer_fixed")))
        assert len(audit) == 2
    finally:
        corrections.set_conflict_reevaluator(None)


async def test_default_hook_is_a_no_op_and_merge_calls_it_with_both_employers(owner_client, session) -> None:
    seen: list[set[str]] = []

    async def hook(_session, employers: set[str]) -> None:
        seen.append(employers)

    a = await make_job(session, "A", "One", canonical="One")
    b = await make_job(session, "B", "Two", canonical="Two")
    await session.commit()
    assert (await owner_client.post(f"/api/jobs/{a.id}/merge", json={"duplicate_ids": [str(b.id)]})).status_code == 200
    corrections.set_conflict_reevaluator(hook)
    try:
        c = await make_job(session, "C", "Three", canonical="Three")
        await session.commit()
        await owner_client.post(f"/api/jobs/{a.id}/merge", json={"duplicate_ids": [str(c.id)]})
        assert seen == [{"One", "Three"}]
    finally:
        corrections.set_conflict_reevaluator(None)


# ----- reminders ----------------------------------------------------------------------------------


async def test_follow_up_reminder_after_the_configured_interval(session) -> None:
    job = await make_job(session, "Analyst", "Acme")
    sent = await make_app(session, job, Stage.submitted, applied_at=NOW - timedelta(days=11))
    fresh = await make_app(session, await make_job(session, "B"), Stage.submitted, applied_at=NOW - timedelta(days=5))
    replied = await make_app(session, await make_job(session, "C"), Stage.screening,
                             applied_at=NOW - timedelta(days=30))
    mine = await make_app(session, await make_job(session, "D"), Stage.submitted, applied_at=NOW - timedelta(days=40),
                          owner_attested=True)
    await session.commit()
    assert await reminders.create_follow_up_reminders(session, NOW) == 2
    await session.commit()
    actions = list(await session.scalars(
        select(PendingAction).where(PendingAction.type == PendingActionType.follow_up)))
    assert {a.application_id for a in actions} == {sent.id, mine.id}
    assert next(a for a in actions if a.application_id == sent.id).title == "Follow up with Acme about Analyst"
    assert await reminders.create_follow_up_reminders(session, NOW) == 0  # idempotent
    # a different interval (setting) changes who is due
    await settings_service.set_value(session, "automation.follow_up_days", 3, actor="owner")
    await session.commit()
    assert await reminders.create_follow_up_reminders(session, NOW) == 1
    await session.commit()
    assert {a.application_id for a in await session.scalars(select(PendingAction))} == {sent.id, mine.id, fresh.id}
    assert replied.id not in {a.application_id for a in await session.scalars(select(PendingAction))}


async def test_dismissed_follow_up_is_not_recreated(session) -> None:
    app = await make_app(session, await make_job(session), Stage.submitted, applied_at=NOW - timedelta(days=20))
    await session.commit()
    await reminders.create_follow_up_reminders(session, NOW)
    action = await session.scalar(select(PendingAction))
    action.status = PendingStatus.dismissed
    await session.commit()
    assert await reminders.create_follow_up_reminders(session, NOW) == 0
    assert app.id == action.application_id


async def test_follow_up_shows_up_for_the_owner(owner_client, session) -> None:
    await make_app(session, await make_job(session), Stage.submitted, applied_at=NOW - timedelta(days=12))
    await session.commit()
    await reminders.create_follow_up_reminders(session, NOW)
    await session.commit()
    groups = (await owner_client.get("/api/pending-actions/decisions")).json()
    assert groups[0]["actions"][0]["type"] == "follow_up" and groups[0]["consequence"] == "1 follow-up due"


@pytest.mark.parametrize(("days", "expected"), [(3, 1), (10, 0)])
async def test_stale_pending_reminder_once_and_not_when_snoozed(session, days, expected) -> None:
    await settings_service.set_value(session, "tracking.stale_pending_days", days, actor="owner")
    app = await make_app(session, await make_job(session))
    await make_pending(session, app, title="Approve CV", created_at=NOW - timedelta(days=5))
    await make_pending(session, app, title="Snoozed", created_at=NOW - timedelta(days=5),
                       snoozed_until=NOW + timedelta(days=1))
    await session.commit()
    assert await reminders.remind_stale_pending(session, NOW) == expected
    assert await reminders.remind_stale_pending(session, NOW) == 0
    await session.commit()
    notes = list(await session.scalars(select(Notification)))
    assert len(notes) == expected
    if expected:
        assert notes[0].kind == "pending_action_stale" and "Approve CV" in notes[0].title
