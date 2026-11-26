"""Bulk actions over HTTP and the engine: preview, confirm, run, partial failure, re-run, undo, caps,
"everything matching this view", and the rule that bulk never bypasses a gate or a conflict group."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api.routers.bulk import get_bulk_enqueue
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import Application, Stage
from app.models.bulk import BulkItem, BulkOperation
from app.models.platform import AuditEvent
from app.models.search import Job, SavedView
from app.pipeline import bulk
from app.schemas.json_types import SavedViewBody
from tests.apply.helpers import setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW
from tests.tracking.helpers import make_app, make_job


class Recorder:
    """Stands in for the worker: runs the operation at once with fake dependencies."""

    def __init__(self) -> None:
        self.tailored: list[uuid.UUID] = []
        self.rechecked: list[uuid.UUID] = []
        self.fail_once: set[uuid.UUID] = set()
        self.deps = bulk.Deps(self._tailor, self._recheck, lambda: None)

    async def _tailor(self, req) -> None:
        self.tailored.append(req.application_id)

    async def _recheck(self, session, job, actor):
        self.rechecked.append(job.id)
        return {"availability": "open", "content_changed": False}

    async def __call__(self, operation_id: uuid.UUID) -> None:
        async with get_sessionmaker()() as session:
            await bulk.execute(session, operation_id, self.deps)


@pytest.fixture
def worker(app):
    rec = Recorder()
    app.dependency_overrides[get_bulk_enqueue] = lambda: rec
    yield rec
    app.dependency_overrides.pop(get_bulk_enqueue, None)


async def _preview(client, subject, action, ids, **params):
    r = await client.post("/api/bulk/preview", json={"subject": subject, "action": action, "params": params,
                                                     "selection": {"ids": [str(i) for i in ids]}})
    return r


async def _run(client, preview):
    r = await client.post(f"/api/bulk/{preview['operation_id']}/run", json={"confirm_count": preview["selected"]})
    assert r.status_code == 202, r.text
    return (await client.get(f"/api/bulk/{preview['operation_id']}")).json()


async def test_endpoints_need_the_owner(client) -> None:
    assert (await client.get("/api/bulk/options")).status_code == 401
    assert (await client.post("/api/bulk/preview", json={})).status_code == 401
    assert (await client.get("/api/employers")).status_code == 401


async def test_preview_groups_by_reason_and_counts_equal_results(owner_client, session, worker) -> None:
    ok1 = await make_app(session, await make_job(session, "Analyst", "Acme Ltd"), Stage.shortlisted)
    ok2 = await make_app(session, await make_job(session, "Engineer", "Zambezi Works"), Stage.tailoring)
    sent1 = await make_app(session, await make_job(session, "Nurse", "Kafue Clinic"), Stage.submitted,
                           applied_at=NOW)
    sent2 = await make_app(session, await make_job(session, "Clerk", "Lusaka Co"), Stage.screening, applied_at=NOW)
    await session.commit()

    r = await _preview(owner_client, "applications", "move_stage", [ok1.id, ok2.id, sent1.id, sent2.id],
                       stage="ready")
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["selected"], p["will_change"], p["refused_total"]) == (4, 2, 2)
    [group] = p["refused"]
    assert group["code"] == "illegal_transition" and group["count"] == 2
    assert {s["label"] for s in group["samples"]} == {"Nurse at Kafue Clinic", "Clerk at Lusaka Co"}
    # a preview changes nothing
    async with get_sessionmaker()() as s:
        stages = {a.id: a.stage for a in (await s.scalars(select(Application))).all()}
    assert stages[ok1.id] == Stage.shortlisted and stages[sent1.id] == Stage.submitted

    op = await _run(owner_client, p)
    assert op["status"] == "done"
    assert op["counts"] == {"changed": p["will_change"], "refused": p["refused_total"]}
    assert op["done"] == p["selected"]
    items = (await owner_client.get(f"/api/bulk/{p['operation_id']}/items", params={"outcome": "refused"})).json()
    assert {i["code"] for i in items["items"]} == {"illegal_transition"}
    async with get_sessionmaker()() as s:
        stages = {a.id: a.stage for a in (await s.scalars(select(Application))).all()}
    assert stages[ok1.id] == stages[ok2.id] == Stage.ready
    assert stages[sent1.id] == Stage.submitted  # the single-item rules held for the others


async def test_run_needs_the_confirmed_count(owner_client, session, worker) -> None:
    job = await make_job(session)
    await session.commit()
    p = (await _preview(owner_client, "jobs", "tag", [job.id], tag="keep")).json()
    r = await owner_client.post(f"/api/bulk/{p['operation_id']}/run", json={"confirm_count": 99})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "count_mismatch"
    r = await owner_client.post(f"/api/bulk/{p['operation_id']}/run", json={})
    assert r.status_code == 409


async def test_selection_cap_is_a_setting(owner_client, session, worker) -> None:
    jobs = [await make_job(session, f"Role {i}", f"Employer {i}") for i in range(4)]
    await session.commit()
    ids = [j.id for j in jobs]
    assert (await _preview(owner_client, "jobs", "tag", ids, tag="x")).status_code == 200  # default cap is 500
    await settings_service.set_value(session, "bulk.max_selection", 3, actor="test")
    await session.commit()
    r = await _preview(owner_client, "jobs", "tag", ids, tag="x")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "selection_too_large"
    assert (await _preview(owner_client, "jobs", "tag", ids[:3], tag="x")).status_code == 200
    assert (await owner_client.get("/api/bulk/options")).json()["max_selection"] == 3


async def test_parameter_errors(owner_client, session, worker) -> None:
    job = await make_job(session)
    await session.commit()
    assert (await _preview(owner_client, "jobs", "skip", [job.id])).status_code == 422  # a reason is required
    assert (await _preview(owner_client, "jobs", "tag", [job.id])).status_code == 422
    assert (await _preview(owner_client, "jobs", "move_stage", [job.id], stage="ready")).status_code == 422
    assert (await _preview(owner_client, "applications", "move_stage", [job.id], stage="nowhere")).status_code == 422
    r = await owner_client.post("/api/bulk/preview", json={"subject": "jobs", "action": "tag", "params": {"tag": "a"},
                                                           "selection": {"ids": []}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "empty_selection"


async def test_rerun_is_idempotent_and_retries_only_failures(owner_client, session, worker, monkeypatch) -> None:
    jobs = [await make_job(session, f"Role {i}", f"Employer {i}") for i in range(3)]
    await session.commit()
    p = (await _preview(owner_client, "jobs", "tag", [j.id for j in jobs], tag="Priority")).json()
    assert p["will_change"] == 3

    real = bulk.HANDLERS["tag"]
    boom = {"on": True}

    async def flaky(ctx, subject):
        if boom["on"] and subject.id == jobs[1].id:
            raise RuntimeError("disk on fire")
        return await real(ctx, subject)

    monkeypatch.setitem(bulk.HANDLERS, "tag", flaky)
    op = await _run(owner_client, p)
    assert op["status"] == "partial" and op["counts"] == {"changed": 2, "failed": 1}
    failed = (await owner_client.get(f"/api/bulk/{p['operation_id']}/items", params={"outcome": "failed"})).json()
    assert failed["items"][0]["subject_id"] == str(jobs[1].id) and "disk on fire" in failed["items"][0]["reason"]

    boom["on"] = False  # re-run: only the failed item is retried, nothing is repeated
    op = await _run_again(owner_client, p)
    assert op["status"] == "done" and op["counts"] == {"changed": 3}
    async with get_sessionmaker()() as s:
        tags = [j.tags for j in (await s.scalars(select(Job).order_by(Job.title))).all()]
        updates = await s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "job.updated"))
    assert tags == [["priority"]] * 3  # normalised, and never doubled
    assert updates == 3

    again = await owner_client.post(f"/api/bulk/{p['operation_id']}/run", json={"confirm_count": 3})
    assert again.status_code == 409  # a finished operation does not run twice
    # the same action again is a no-op: every item is "already as asked"
    p2 = (await _preview(owner_client, "jobs", "tag", [j.id for j in jobs], tag="priority")).json()
    assert p2["will_change"] == 0 and p2["unchanged"]["count"] == 3


async def _run_again(client, preview):
    r = await client.post(f"/api/bulk/{preview['operation_id']}/run", json={"confirm_count": preview["selected"]})
    assert r.status_code == 202, r.text
    return (await client.get(f"/api/bulk/{preview['operation_id']}")).json()


async def test_undo_tags_snooze_skip_and_archive(owner_client, session, worker) -> None:
    a = await make_job(session, "A", "Acme Ltd", tags=["keep"])
    b = await make_job(session, "B", "Zambezi Works")
    await session.commit()
    ids = [a.id, b.id]
    until = (datetime.now(UTC) + timedelta(days=3)).isoformat()

    for action, params, field_check in (
        ("tag", {"tag": "later"}, lambda j: "later" in j.tags),
        ("snooze", {"until": until}, lambda j: j.snoozed_until is not None),
        ("skip", {"reason": "not for me"}, lambda j: j.triage == "skipped"),
        ("archive", {}, lambda j: j.triage == "archived"),
    ):
        p = (await _preview(owner_client, "jobs", action, ids, **params)).json()
        assert p["reversible"] is True
        op = await _run(owner_client, p)
        assert op["can_undo"] and op["counts"]["changed"] == 2, action
        async with get_sessionmaker()() as s:
            assert all(field_check(j) for j in (await s.scalars(select(Job))).all()), action
        r = await owner_client.post(f"/api/bulk/{p['operation_id']}/undo")
        assert r.status_code == 200 and r.json()["status"] == "undone", r.text
        assert r.json()["counts"] == {"undone": 2}
        async with get_sessionmaker()() as s:
            jobs = {j.id: j for j in (await s.scalars(select(Job))).all()}
        assert not any(field_check(j) for j in jobs.values()), action
    assert jobs[a.id].tags == ["keep"] and jobs[a.id].triage == "new"
    again = await owner_client.post(f"/api/bulk/{p['operation_id']}/undo")
    assert again.status_code == 409


async def test_undo_leaves_what_changed_since_and_expires(owner_client, session, worker) -> None:
    a = await make_job(session, "A", "Acme Ltd")
    b = await make_job(session, "B", "Zambezi Works")
    await session.commit()
    p = (await _preview(owner_client, "jobs", "archive", [a.id, b.id])).json()
    await _run(owner_client, p)
    async with get_sessionmaker()() as s:  # the owner un-archives A by hand in the meantime
        (await s.get(Job, a.id)).triage = "shortlisted"
        await s.commit()
    r = (await owner_client.post(f"/api/bulk/{p['operation_id']}/undo")).json()
    assert r["counts"] == {"undone": 1, "undo_skipped": 1}
    skipped = (await owner_client.get(f"/api/bulk/{p['operation_id']}/items",
                                      params={"outcome": "undo_skipped"})).json()["items"]
    assert skipped[0]["subject_id"] == str(a.id) and skipped[0]["code"] == "changed_since"

    # a window of 0 turns undo off; an expired one refuses
    await settings_service.set_value(session, "bulk.undo_window_minutes", 0, actor="test")
    await session.commit()
    p = (await _preview(owner_client, "jobs", "tag", [a.id], tag="t")).json()
    op = await _run(owner_client, p)
    assert op["can_undo"] is False and op["undo_until"] is None
    assert (await owner_client.post(f"/api/bulk/{p['operation_id']}/undo")).status_code == 409
    await settings_service.set_value(session, "bulk.undo_window_minutes", 5, actor="test")
    await session.commit()
    p = (await _preview(owner_client, "jobs", "tag", [b.id], tag="t")).json()
    await _run(owner_client, p)
    async with get_sessionmaker()() as s:
        row = await s.get(BulkOperation, uuid.UUID(p["operation_id"]))
        row.undo_until = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()
    r = await owner_client.post(f"/api/bulk/{p['operation_id']}/undo")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "undo_expired"
    # sending-adjacent and stage actions are not reversible
    p = (await _preview(owner_client, "jobs", "recheck", [a.id])).json()
    assert p["reversible"] is False


async def test_all_matching_view_equals_the_views_result_set(owner_client, session, worker) -> None:
    for i in range(6):
        await make_job(session, f"Role {i}", f"Employer {i}", tags=["remote"] if i % 2 == 0 else [])
    view = SavedView(name="Remote", body=SavedViewBody.model_validate({"conditions": {"root": {"conditions": [
        {"type": "values", "facet": "tags", "include": ["remote"]}]}}}))
    session.add(view)
    await session.commit()
    listed = (await owner_client.get("/api/jobs", params={"view_id": str(view.id), "limit": 200})).json()
    expected = {i["id"] for i in listed["items"]}
    assert len(expected) == 3

    r = await owner_client.post("/api/bulk/preview", json={
        "subject": "jobs", "action": "tag", "params": {"tag": "reviewed"},
        "selection": {"view": {"view_id": str(view.id)}}})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["selected"] == len(expected)  # the count to confirm is the view's count
    async with get_sessionmaker()() as s:
        planned = {str(i.subject_id) for i in (await s.scalars(select(BulkItem).where(
            BulkItem.operation_id == uuid.UUID(p["operation_id"])))).all()}
    assert planned == expected
    op = await _run(owner_client, p)
    assert op["counts"] == {"changed": 3}
    async with get_sessionmaker()() as s:
        tagged = {str(j.id) for j in (await s.scalars(select(Job))).all() if "reviewed" in j.tags}
    assert tagged == expected


async def test_all_matching_for_applications_uses_the_applications_filters(owner_client, session, worker) -> None:
    keep = await make_app(session, await make_job(session, "A", "Acme Ltd"), Stage.ready)
    await make_app(session, await make_job(session, "B", "Zambezi Works"), Stage.shortlisted)
    await session.commit()
    r = await owner_client.post("/api/bulk/preview", json={
        "subject": "applications", "action": "tag", "params": {"tag": "ready-batch"},
        "selection": {"view": {"stage": "ready"}}})
    assert r.status_code == 200, r.text
    assert r.json()["selected"] == 1
    listed = (await owner_client.get("/api/applications", params={"stage": "ready"})).json()
    assert [i["id"] for i in listed["items"]] == [str(keep.id)]


async def test_bulk_never_bypasses_the_owner_only_stage_rules(owner_client, session, worker) -> None:
    app = await make_app(session, await make_job(session, "A", "Acme Ltd"), Stage.ready)
    await session.commit()
    p = (await _preview(owner_client, "applications", "move_stage", [app.id], stage="applying")).json()
    assert p["will_change"] == 0 and p["refused"][0]["code"] == "illegal_transition"
    p = (await _preview(owner_client, "applications", "move_stage", [app.id], stage="submitted")).json()
    assert p["will_change"] == 0  # no evidence, no submitted state by dragging


async def test_a_held_runner_up_is_refused_in_a_bulk_send_and_a_bulk_tailor(owner_client, session, worker) -> None:
    campaign = await setup_campaign(session)
    winner_job, winner = await setup_app(session, campaign, title="Senior Analyst", score=90, now=NOW,
                                         stage=Stage.shortlisted)
    held_job, held = await setup_app(session, campaign, title="Analyst", score=70, now=NOW, stage=Stage.shortlisted)
    await session.commit()
    async with get_sessionmaker()() as s:
        assert (await s.get(Job, held_job.id)).conflict_state.value == "held"
        assert (await s.get(Job, winner_job.id)).conflict_state.value == "winner"

    for action in ("send_for_approval", "queue_tailoring"):
        p = (await _preview(owner_client, "applications", action, [held.id])).json()
        assert p["will_change"] == 0, action
        [g] = p["refused"]
        assert g["code"] == "held" and "outranked" in g["samples"][0]["reason"], (action, g)
        op = await _run(owner_client, p)
        assert op["counts"] == {"refused": 1} and not worker.tailored
    # the winner is not blocked by the group: it is only blocked by what blocks any single send (no draft yet)
    p = (await _preview(owner_client, "applications", "send_for_approval", [winner.id, held.id])).json()
    codes = {g["code"] for g in p["refused"]}
    assert codes == {"spec_not_ready", "held"}
    async with get_sessionmaker()() as s:
        assert (await s.get(Application, held.id)).stage == Stage.shortlisted


async def test_queue_tailoring_goes_through_the_single_item_service(owner_client, session, worker) -> None:
    campaign = await setup_campaign(session)
    job, _ = await setup_app(session, campaign, score=88, now=NOW, stage=Stage.shortlisted)
    bare = await make_job(session, "Bare Job", "Nobody Ltd")  # no application yet: bulk creates it, as the UI does
    await session.commit()
    p = (await _preview(owner_client, "jobs", "queue_tailoring", [job.id, bare.id])).json()
    assert p["will_change"] == 2, p
    async with get_sessionmaker()() as s:
        assert (await s.scalar(select(func.count()).select_from(Application))) == 1  # the preview created nothing
    op = await _run(owner_client, p)
    assert op["counts"] == {"changed": 2}
    async with get_sessionmaker()() as s:
        stages = {a.job_id: a.stage for a in (await s.scalars(select(Application))).all()}
    assert stages == {job.id: Stage.tailoring, bare.id: Stage.tailoring}
    assert len(worker.tailored) == 2
    p = (await _preview(owner_client, "jobs", "queue_tailoring", [job.id])).json()
    assert p["will_change"] == 0 and p["unchanged"]["count"] == 1  # asking again changes nothing


async def test_never_apply_blocks_bulk_tailoring(owner_client, session, worker) -> None:
    job = await make_job(session, "Analyst", "Blocked Co")
    ok = await make_job(session, "Analyst", "Fine Co")
    await session.commit()
    r = await owner_client.patch("/api/employers/policy", params={"key": "blocked co"},
                                 json={"never_apply": True, "never_reason": "bad reputation"})
    assert r.status_code == 200, r.text
    p = (await _preview(owner_client, "jobs", "queue_tailoring", [job.id, ok.id])).json()
    assert p["will_change"] == 1
    assert p["refused"][0]["code"] == "never_apply" and "bad reputation" in p["refused"][0]["samples"][0]["reason"]
    await _run(owner_client, p)
    async with get_sessionmaker()() as s:
        owned = {a.job_id for a in (await s.scalars(select(Application))).all()}
    assert owned == {ok.id}  # nothing was created for the blocked employer


async def test_approve_reviewed_is_off_by_default(owner_client, session, worker) -> None:
    app = await make_app(session, await make_job(session, "A", "Acme Ltd"), Stage.ready)
    await session.commit()
    opts = (await owner_client.get("/api/bulk/options")).json()
    assert opts["approve_reviewed_enabled"] is False
    assert "approve_reviewed" not in opts["actions"]["applications"]
    assert "approve_reviewed" not in opts["actions"]["jobs"]
    r = await _preview(owner_client, "applications", "approve_reviewed", [app.id])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "disabled"

    await settings_service.set_value(session, "bulk.allow_approve_reviewed", True, actor="test")
    await session.commit()
    assert "approve_reviewed" in (await owner_client.get("/api/bulk/options")).json()["actions"]["applications"]
    p = (await _preview(owner_client, "applications", "approve_reviewed", [app.id])).json()
    assert p["will_change"] == 0 and p["refused"][0]["code"] == "no_packet"  # never builds a packet


async def test_skip_an_application_promotes_the_next_role_and_can_be_undone(owner_client, session, worker) -> None:
    campaign = await setup_campaign(session)
    first_job, first = await setup_app(session, campaign, title="Senior Analyst", score=90, now=NOW,
                                       stage=Stage.shortlisted)
    second_job, _ = await setup_app(session, campaign, title="Analyst", score=70, now=NOW,
                                         stage=Stage.shortlisted)
    await session.commit()
    p = (await _preview(owner_client, "applications", "skip", [first.id], reason="wrong level")).json()
    op = await _run(owner_client, p)
    assert op["counts"] == {"changed": 1}
    async with get_sessionmaker()() as s:
        assert (await s.get(Application, first.id)).stage == Stage.skipped
        assert (await s.get(Job, first_job.id)).triage == "skipped"
        assert (await s.get(Job, second_job.id)).conflict_state.value == "winner"  # promoted, as for one skip
    r = await owner_client.post(f"/api/bulk/{p['operation_id']}/undo")
    assert r.status_code == 200 and r.json()["counts"] == {"undone": 1}
    async with get_sessionmaker()() as s:
        assert (await s.get(Application, first.id)).stage == Stage.shortlisted
        assert (await s.get(Job, first_job.id)).triage == "new"


async def test_assign_campaign_and_recheck_and_export(owner_client, session, worker) -> None:
    from app.models.search import Campaign

    campaign = Campaign(name="Analytics")
    session.add(campaign)
    app = await make_app(session, await make_job(session, "=cmd|calc", "Acme Ltd"), Stage.shortlisted)
    await session.flush()
    app_job_id = app.job_id
    await session.commit()

    p = (await _preview(owner_client, "applications", "assign_campaign", [app.id], campaign_id=str(campaign.id))).json()
    await _run(owner_client, p)
    async with get_sessionmaker()() as s:
        assert (await s.get(Application, app.id)).campaign_id == campaign.id
    p = (await _preview(owner_client, "applications", "assign_campaign", [app.id], campaign_id=str(campaign.id))).json()
    assert p["unchanged"]["count"] == 1
    missing = await _preview(owner_client, "applications", "assign_campaign", [app.id], campaign_id=str(uuid.uuid4()))
    assert missing.status_code == 404

    p = (await _preview(owner_client, "jobs", "recheck", [app_job_id])).json()
    await _run(owner_client, p)
    assert worker.rechecked == [app_job_id]

    p = (await _preview(owner_client, "jobs", "export_csv", [app_job_id])).json()
    await _run(owner_client, p)
    r = await owner_client.get(f"/api/bulk/{p['operation_id']}/csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0].startswith("id,title,employer")
    assert "'=cmd|calc" in lines[1]  # posting text never becomes a spreadsheet formula
    assert (await owner_client.get(f"/api/bulk/{p['operation_id']}")).json()["can_undo"] is False


async def test_operation_progress_is_published_and_listed(owner_client, session, worker) -> None:
    jobs = [await make_job(session, f"Role {i}", f"Employer {i}") for i in range(3)]
    await session.commit()
    p = (await _preview(owner_client, "jobs", "tag", [j.id for j in jobs], tag="x")).json()
    await _run(owner_client, p)
    listing = (await owner_client.get("/api/bulk")).json()
    assert [o["id"] for o in listing["items"]] == [p["operation_id"]]  # previews are not listed
    async with get_sessionmaker()() as s:
        actions = {a for (a,) in (await s.execute(select(AuditEvent.action))).all()}
    assert {"bulk.confirmed", "bulk.finished"} <= actions
