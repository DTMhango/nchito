"""Applications over HTTP: list, board, detail, stage changes, patch, timeline, contacts, applied myself."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.settings import service as settings_service
from app.models.applications import Application, ApplicationEvent, Channel, Stage
from app.models.platform import AuditEvent
from app.models.search import Assessment, Campaign, Job
from tests.tracking.helpers import make_app, make_job


async def _commit(session) -> None:
    await session.commit()


async def test_endpoints_need_the_owner(client) -> None:
    for path in ("/api/applications", "/api/applications/board", "/api/contacts", "/api/pending-actions",
                 "/api/today"):
        assert (await client.get(path)).status_code == 401


async def test_list_filters_search_and_paging(owner_client, session) -> None:
    campaign = Campaign(name="Analytics")
    session.add(campaign)
    await session.flush()
    a = await make_app(session, await make_job(session, "Data Analyst", "Acme Ltd"), campaign_id=campaign.id,
                       channel=Channel.email)
    b = await make_app(session, await make_job(session, "Site Engineer", "Zambezi Works"), Stage.ready,
                       channel=Channel.browser)
    await make_app(session, await make_job(session, "Nurse", "Kafue Clinic"), Stage.submitted, notes="great team")
    await _commit(session)

    def ids(r):
        return {i["id"] for i in r.json()["items"]}

    r = await owner_client.get("/api/applications")
    assert r.json()["total"] == 3
    assert ids(await owner_client.get("/api/applications", params={"stage": "ready"})) == {str(b.id)}
    assert ids(await owner_client.get("/api/applications", params={"campaign_id": str(campaign.id)})) == {str(a.id)}
    assert ids(await owner_client.get("/api/applications", params={"channel": "browser"})) == {str(b.id)}
    assert len(ids(await owner_client.get("/api/applications", params={"q": "zambezi"}))) == 1
    assert len(ids(await owner_client.get("/api/applications", params={"q": "GREAT team"}))) == 1
    page = (await owner_client.get("/api/applications", params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = (await owner_client.get("/api/applications", params={"limit": 2, "cursor": page["next_cursor"]})).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None


async def test_summary_carries_score_pending_count_and_snooze(owner_client, session) -> None:
    campaign = Campaign(name="C")
    session.add(campaign)
    job = await make_job(session)
    await session.flush()
    session.add(Assessment(job_id=job.id, campaign_id=campaign.id, score=82))
    app = await make_app(session, job, snoozed_until=datetime.now(UTC) + timedelta(days=5))
    await _commit(session)
    item = (await owner_client.get("/api/applications")).json()["items"][0]
    assert item["id"] == str(app.id) and item["score"] == 82 and item["snoozed"] is True
    assert (await owner_client.get("/api/applications", params={"hide_snoozed": True})).json()["total"] == 0


async def test_board_has_every_stage_with_counts(owner_client, session) -> None:
    await make_app(session, await make_job(session, "A"), Stage.ready)
    await make_app(session, await make_job(session, "B"), Stage.ready)
    await make_app(session, await make_job(session, "C"), Stage.interview)
    await _commit(session)
    cols = (await owner_client.get("/api/applications/board")).json()["columns"]
    assert [c["stage"] for c in cols] == [s.value for s in Stage]
    by = {c["stage"]: c for c in cols}
    assert by["ready"]["count"] == 2 and len(by["ready"]["items"]) == 2
    assert by["interview"]["count"] == 1 and by["offer"]["count"] == 0 and by["offer"]["items"] == []


async def test_create_blocks_a_second_application_for_the_same_job(owner_client, session) -> None:
    job = await make_job(session)
    await _commit(session)
    r = await owner_client.post("/api/applications", json={"job_id": str(job.id)})
    assert r.status_code == 201 and r.json()["stage"] == "shortlisted"
    again = await owner_client.post("/api/applications", json={"job_id": str(job.id)})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate"
    assert (await owner_client.post("/api/applications", json={"job_id": "00000000-0000-0000-0000-000000000000"})
            ).status_code == 404


async def test_skipped_application_does_not_block_a_new_one(owner_client, session) -> None:
    job = await make_job(session)
    await make_app(session, job, Stage.skipped)
    await _commit(session)
    assert (await owner_client.post("/api/applications", json={"job_id": str(job.id)})).status_code == 201


async def test_stage_change_through_the_api_records_actor_and_reason(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    await _commit(session)
    r = await owner_client.post(f"/api/applications/{app.id}/stage", json={"stage": "tailoring", "note": "on it"})
    assert r.status_code == 200 and r.json()["stage"] == "tailoring"
    assert "ready" in r.json()["allowed_next"] and "submitted" not in r.json()["allowed_next"]
    timeline = (await owner_client.get(f"/api/applications/{app.id}/timeline")).json()
    change = [e for e in timeline if e["kind"] == "stage_change"][-1]
    assert change["actor"] == "owner"
    assert change["detail"]["why"] == "on it" and change["detail"]["from"] == "shortlisted"


async def test_illegal_stage_change_is_refused_with_a_reason(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    await _commit(session)
    r = await owner_client.post(f"/api/applications/{app.id}/stage", json={"stage": "submitted"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "illegal_transition" and "applied myself" in detail["reason"]
    assert (await owner_client.get(f"/api/applications/{app.id}")).json()["stage"] == "shortlisted"
    bad = await owner_client.post(f"/api/applications/{app.id}/stage", json={"stage": "interview"})
    assert bad.status_code == 409


async def test_patch_next_step_pin_snooze_notes_and_clear(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    await _commit(session)
    until = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    r = await owner_client.patch(f"/api/applications/{app.id}", json={
        "next_step": "Email the recruiter", "next_due": "2026-12-01", "pinned": True, "snoozed_until": until,
        "notes": "Met them at the expo", "channel": "email"})
    body = r.json()
    assert r.status_code == 200
    assert (body["next_step"], body["next_due"], body["pinned"], body["notes"], body["channel"]) == (
        "Email the recruiter", "2026-12-01", True, "Met them at the expo", "email")
    assert body["snoozed_until"] is not None
    cleared = await owner_client.patch(f"/api/applications/{app.id}", json={"snoozed_until": None, "next_due": None})
    assert cleared.json()["snoozed_until"] is None and cleared.json()["next_due"] is None
    assert cleared.json()["next_step"] == "Email the recruiter"
    kinds = [e["kind"] for e in (await owner_client.get(f"/api/applications/{app.id}/timeline")).json()]
    assert kinds.count("edit") == 2


async def test_snooze_hides_until_it_ends_but_an_imminent_deadline_overrides(owner_client, session) -> None:
    far = await make_app(session, await make_job(session, "Far"), snoozed_until=datetime.now(UTC) + timedelta(days=9))
    soon_job = await make_job(session, "Soon", deadline=date.today() + timedelta(days=2))
    soon = await make_app(session, soon_job, snoozed_until=datetime.now(UTC) + timedelta(days=9))
    ended = await make_app(session, await make_job(session, "Ended"),
                           snoozed_until=datetime.now(UTC) - timedelta(minutes=1))
    await _commit(session)
    visible = {i["id"] for i in (await owner_client.get("/api/applications", params={"hide_snoozed": True}))
               .json()["items"]}
    assert str(far.id) not in visible
    assert str(soon.id) in visible and str(ended.id) in visible
    # the owner widens "imminent": the far deadline now overrides too
    await settings_service.set_value(session, "tracking.imminent_deadline_days", 1, actor="owner")
    await session.commit()
    visible = {i["id"] for i in (await owner_client.get("/api/applications", params={"hide_snoozed": True}))
               .json()["items"]}
    assert str(soon.id) not in visible  # 2 days away is no longer imminent at 1 day


async def test_applied_myself_for_an_existing_job_blocks_duplicates(owner_client, session) -> None:
    job = await make_job(session, "Data Analyst", "Acme Ltd", canonical="Acme")
    await _commit(session)
    r = await owner_client.post(f"/api/jobs/{job.id}/applied-myself", json={
        "applied_on": "2026-11-20", "channel": "email", "reference": "REF-77", "note": "Sent from my phone",
        "files": ["cv.pdf"]})
    assert r.status_code == 200
    app = (await owner_client.get("/api/applications", params={"stage": "submitted"})).json()["items"][0]
    assert app["owner_attested"] is True and app["origin"] == "owner" and app["channel"] == "email"
    assert app["applied_at"].startswith("2026-11-20")
    detail = (await owner_client.get(f"/api/applications/{app['id']}")).json()
    assert detail["applied_outside"] is True and detail["reference"] == "REF-77"
    assert detail["confirmation_evidence"] == [] and detail["submitted_snapshot"] is None
    # counts at once: a later duplicate is refused from every direction
    assert (await owner_client.post("/api/applications", json={"job_id": str(job.id)})).status_code == 409
    assert (await owner_client.post(f"/api/jobs/{job.id}/applied-myself", json={})).status_code == 409
    other = await owner_client.post("/api/applications/applied-myself", json={"job_id": str(job.id)})
    assert other.status_code == 409
    audit = await session.scalars(select(AuditEvent.action).where(AuditEvent.action == "application.applied_myself"))
    assert len(list(audit)) == 1
    events = (await owner_client.get(f"/api/applications/{app['id']}/timeline")).json()
    change = next(e for e in events if e["kind"] == "stage_change")
    assert change["detail"]["via"] == "applied_myself" and change["detail"]["why"] == "Sent from my phone"


async def test_applied_myself_moves_an_existing_shortlisted_application(owner_client, session) -> None:
    job = await make_job(session)
    app = await make_app(session, job, Stage.ready)
    await _commit(session)
    r = await owner_client.post("/api/applications/applied-myself", json={"job_id": str(job.id)})
    assert r.status_code == 201 and r.json()["id"] == str(app.id) and r.json()["stage"] == "submitted"
    assert (await session.scalar(select(Application.id).where(Application.job_id == job.id).limit(2))) == app.id


async def test_applied_myself_creates_a_job_on_the_spot_and_reuses_it(owner_client, session) -> None:
    body = {"url": "https://jobs.example.com/roles/42", "title": "Field Officer", "employer": "Kafue Trust",
            "applied_on": "2026-11-18", "channel": "browser", "reference": "KT-9"}
    r = await owner_client.post("/api/applications/applied-myself", json=body)
    assert r.status_code == 201 and r.json()["employer"] == "Kafue Trust"
    job = await session.scalar(select(Job).where(Job.title == "Field Officer"))
    assert job.origin == "owner" and job.apply_url == body["url"]
    again = await owner_client.post("/api/applications/applied-myself", json=body)
    assert again.status_code == 409
    assert len(list(await session.scalars(select(Job).where(Job.title == "Field Officer")))) == 1
    assert (await owner_client.post("/api/applications/applied-myself", json={"title": "x"})).status_code == 422


async def test_applied_myself_rejects_a_future_date(owner_client, session) -> None:
    job = await make_job(session)
    await _commit(session)
    future = (date.today() + timedelta(days=3)).isoformat()
    r = await owner_client.post(f"/api/jobs/{job.id}/applied-myself", json={"applied_on": future})
    assert r.status_code == 422


async def test_applied_myself_counts_toward_the_employer_limit(session, owner_client) -> None:
    from app.apply import stages

    job = await make_job(session, canonical="Acme")
    other = await make_job(session, "Other Role", canonical="Acme")
    await _commit(session)
    assert await stages.live_applications_at_employer(session, "Acme") == 0
    await owner_client.post(f"/api/jobs/{job.id}/applied-myself", json={})
    assert await stages.live_applications_at_employer(session, "acme") == 1
    assert (await stages.blocking_application(session, job.id)) is not None
    assert (await stages.blocking_application(session, other.id)) is None


async def test_timeline_is_in_order_and_404s(owner_client, session) -> None:
    job = await make_job(session)
    await _commit(session)
    app = (await owner_client.post("/api/applications", json={"job_id": str(job.id)})).json()
    await owner_client.post(f"/api/applications/{app['id']}/stage", json={"stage": "tailoring"})
    await owner_client.post(f"/api/applications/{app['id']}/stage", json={"stage": "ready"})
    events = (await owner_client.get(f"/api/applications/{app['id']}/timeline")).json()
    assert [e["kind"] for e in events] == ["created", "stage_change", "stage_change"]
    assert [e["detail"].get("to") for e in events[1:]] == ["tailoring", "ready"]
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await owner_client.get(f"/api/applications/{missing}/timeline")).status_code == 404
    assert (await owner_client.get(f"/api/applications/{missing}")).status_code == 404


async def test_timeline_is_append_only_at_the_database(session) -> None:
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    app = await make_app(session, await make_job(session))
    ev = ApplicationEvent(application_id=app.id, kind="note", actor="owner", detail={})
    session.add(ev)
    await session.commit()
    with pytest.raises(DBAPIError):
        await session.execute(text("UPDATE application_event SET actor = 'x'"))


async def test_contacts_crud_per_job(owner_client, session) -> None:
    job = await make_job(session)
    other = await make_job(session, "Other")
    await _commit(session)
    made = await owner_client.post("/api/contacts", json={"job_id": str(job.id), "name": "Mwansa Phiri",
                                                          "role": "Recruiter", "email": "m@example.com"})
    assert made.status_code == 201 and made.json()["origin"] == "owner"
    await owner_client.post("/api/contacts", json={"job_id": str(other.id), "name": "Someone Else"})
    listed = (await owner_client.get("/api/contacts", params={"job_id": str(job.id)})).json()
    assert [c["name"] for c in listed["items"]] == ["Mwansa Phiri"]
    assert (await owner_client.get("/api/contacts")).json()["items"].__len__() == 2
    cid = made.json()["id"]
    upd = await owner_client.put(f"/api/contacts/{cid}", json={"job_id": str(job.id), "name": "Mwansa P.",
                                                              "notes": "Likes email"})
    assert upd.status_code == 200 and upd.json()["name"] == "Mwansa P." and upd.json()["notes"] == "Likes email"
    assert (await owner_client.delete(f"/api/contacts/{cid}")).status_code == 204
    assert (await owner_client.delete(f"/api/contacts/{cid}")).status_code == 404
    assert (await owner_client.post("/api/contacts", json={
        "job_id": "00000000-0000-0000-0000-000000000000", "name": "x"})).status_code == 404
    actions = list(await session.scalars(select(AuditEvent.action).where(AuditEvent.action.like("contact.%"))))
    assert {"contact.created", "contact.updated", "contact.deleted"} <= set(actions)


async def test_files_can_be_attached_after_applying_myself(owner_client, session, tmp_path, monkeypatch) -> None:
    from app.core.config import get_config

    monkeypatch.setattr(get_config(), "files_dir", tmp_path)
    app = (await owner_client.post("/api/applications/applied-myself", json={
        "title": "Clerk", "employer": "Mumbwa Co", "files": ["cv.pdf"]})).json()
    r = await owner_client.post(f"/api/applications/{app['id']}/files",
                                files=[("files", ("cv.pdf", b"%PDF-1.4 fake", "application/pdf"))])
    assert r.status_code == 201 and r.json()[0]["name"] == "cv.pdf" and r.json()[0]["size_bytes"] == 13
    assert (tmp_path / "applications" / app["id"] / f"{r.json()[0]['file_id']}.bin").read_bytes() == b"%PDF-1.4 fake"
    assert (await owner_client.get(f"/api/applications/{app['id']}/files")).json()[0]["sha256"] == r.json()[0]["sha256"]
    kinds = [e["kind"] for e in (await owner_client.get(f"/api/applications/{app['id']}/timeline")).json()]
    assert "file_attached" in kinds
