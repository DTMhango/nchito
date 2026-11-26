"""Pending actions (list, decisions, dismiss, snooze, answer) and the Today summary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.llm.money import MICROS_PER_MINOR as M
from app.models.applications import ApplicationEvent, PendingActionType, PendingStatus, Stage
from app.models.kit import Answer, AnswerScope
from app.models.platform import AuditEvent, LedgerEntry, LedgerKind
from app.models.search import Assessment, Campaign, Run, RunKind, RunStatus, Source, SourceAccess
from tests.tracking.helpers import make_app, make_job, make_pending

NOW = datetime.now(UTC)
T = PendingActionType


async def test_list_orders_by_deadline_and_filters(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    await make_pending(session, app, title="late", deadline=NOW + timedelta(days=9))
    soon = await make_pending(session, app, title="soon", deadline=NOW + timedelta(days=1))
    await make_pending(session, app, title="none", created_at=NOW - timedelta(hours=2))
    await make_pending(session, app, title="done", status=PendingStatus.resolved)
    await make_pending(session, app, title="q", type_=T.captcha, created_at=NOW - timedelta(hours=1))
    await session.commit()
    items = (await owner_client.get("/api/pending-actions")).json()["items"]
    assert [i["title"] for i in items] == ["soon", "late", "none", "q"]
    only = (await owner_client.get("/api/pending-actions", params={"type": "captcha"})).json()["items"]
    assert [i["title"] for i in only] == ["q"]
    done = (await owner_client.get("/api/pending-actions", params={"status": "resolved"})).json()["items"]
    assert [i["title"] for i in done] == ["done"]
    one = (await owner_client.get(f"/api/pending-actions/{soon.id}")).json()
    assert one["employer"] == "Acme Ltd" and one["job_title"] == "Data Analyst"
    assert (await owner_client.get("/api/pending-actions/00000000-0000-0000-0000-000000000000")).status_code == 404


async def test_shared_blockers_are_grouped_with_their_consequence(owner_client, session) -> None:
    portal = "portal:workday:acme"
    a1 = await make_app(session, await make_job(session, "Role 1", "Acme"))
    a2 = await make_app(session, await make_job(session, "Role 2", "Acme"))
    a3 = await make_app(session, await make_job(session, "Role 3", "Other Co"))
    await make_pending(session, a1, type_=T.sign_in, title="Sign in to Acme portal", group_key=portal)
    await make_pending(session, a2, type_=T.sign_in, title="Sign in to Acme portal", group_key=portal)
    q = "question:work-rights"
    for a in (a1, a2, a3):
        await make_pending(session, a, type_=T.unknown_question, title="Work rights?", group_key=q,
                           detail={"question": "Do you have the right to work?"})
    await make_pending(session, a3, type_=T.captcha, title="Solve the CAPTCHA")
    await session.commit()
    groups = (await owner_client.get("/api/pending-actions/decisions")).json()
    by_key = {g["group_key"]: g for g in groups}
    assert by_key[portal]["consequence"] == "Signing in here unlocks 2 applications"
    assert len(by_key[portal]["actions"]) == 2
    assert by_key[q]["consequence"] == "One answer affects 3 roles"
    singles = [g for g in groups if g["group_key"].startswith("action:")]
    assert len(singles) == 1 and singles[0]["consequence"] == "Solving this unblocks 1 application"
    assert len(groups) == 3


async def test_decisions_are_sorted_by_deadline_then_consequence(owner_client, session) -> None:
    apps = [await make_app(session, await make_job(session, f"R{i}")) for i in range(5)]
    await make_pending(session, apps[0], title="big, no deadline", group_key="big")
    await make_pending(session, apps[1], title="big, no deadline", group_key="big")
    await make_pending(session, apps[2], title="big, no deadline", group_key="big")
    await make_pending(session, apps[3], title="single no deadline", group_key="single")
    await make_pending(session, apps[4], title="urgent", group_key="urgent", deadline=NOW + timedelta(days=2))
    await make_pending(session, apps[0], title="sooner", group_key="sooner", deadline=NOW + timedelta(hours=5))
    await session.commit()
    keys = [g["group_key"] for g in (await owner_client.get("/api/pending-actions/decisions")).json()]
    assert keys == ["sooner", "urgent", "big", "single"]


async def test_dismiss_records_who_and_why_and_cannot_repeat(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    action = await make_pending(session, app)
    await session.commit()
    r = await owner_client.post(f"/api/pending-actions/{action.id}/dismiss", json={"note": "already did it"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert r.json()["resolution"]["note"] == "already did it"
    assert (await owner_client.post(f"/api/pending-actions/{action.id}/dismiss", json={})).status_code == 409
    assert (await owner_client.get("/api/pending-actions")).json()["items"] == []
    audit = await session.scalar(select(AuditEvent).where(AuditEvent.action == "pending_action.dismissed"))
    assert audit.actor == "owner" and audit.detail["note"] == "already did it"
    event = await session.scalar(select(ApplicationEvent).where(ApplicationEvent.kind == "pending_action_closed"))
    assert event.detail["status"] == "dismissed"


async def test_snooze_hides_then_returns_on_schedule(owner_client, session) -> None:
    action = await make_pending(session, await make_app(session, await make_job(session)))
    await session.commit()
    until = NOW + timedelta(days=2)
    r = await owner_client.post(f"/api/pending-actions/{action.id}/snooze", json={"until": until.isoformat()})
    assert r.status_code == 200 and r.json()["snoozed"] is True
    assert (await owner_client.get("/api/pending-actions")).json()["items"] == []
    assert (await owner_client.get("/api/pending-actions/decisions")).json() == []
    assert (await owner_client.get("/api/today")).json()["needs_you"] == 0
    shown = (await owner_client.get("/api/pending-actions", params={"include_snoozed": True})).json()["items"]
    assert len(shown) == 1
    # time passes: the snooze ends and the action is back
    action.snoozed_until = NOW - timedelta(minutes=1)
    await session.commit()
    assert len((await owner_client.get("/api/pending-actions")).json()["items"]) == 1
    assert (await owner_client.get("/api/today")).json()["needs_you"] == 1
    past = await owner_client.post(f"/api/pending-actions/{action.id}/snooze",
                                   json={"until": (NOW - timedelta(days=1)).isoformat()})
    assert past.status_code == 422


async def test_an_imminent_deadline_overrides_a_snooze(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    urgent = await make_pending(session, app, title="urgent", deadline=NOW + timedelta(hours=20),
                                snoozed_until=NOW + timedelta(days=7))
    await make_pending(session, app, title="relaxed", deadline=NOW + timedelta(days=30),
                       snoozed_until=NOW + timedelta(days=7))
    await session.commit()
    items = (await owner_client.get("/api/pending-actions")).json()["items"]
    assert [i["id"] for i in items] == [str(urgent.id)] and items[0]["snoozed"] is False
    assert [g["actions"][0]["title"] for g in (await owner_client.get("/api/pending-actions/decisions")).json()
            ] == ["urgent"]


async def _unknown_question(session, group: str, *, employer: str, country: str | None, material: bool = False):
    job = await make_job(session, f"Role at {employer}", employer, country=country)
    app = await make_app(session, job)
    action = await make_pending(session, app, type_=T.unknown_question, title="Notice period?", group_key=group,
                                detail={"question": "What is your notice period?", "material": material})
    return app, action


async def test_answering_saves_an_answer_with_the_chosen_scope_and_settles_the_group(owner_client, session) -> None:
    group = "question:notice"
    _, first = await _unknown_question(session, group, employer="Acme", country="ZM")
    _, same_employer = await _unknown_question(session, group, employer="Acme", country="ZM")
    _, other = await _unknown_question(session, group, employer="Other Co", country="ZM")
    await session.commit()
    r = await owner_client.post(f"/api/pending-actions/{first.id}/answer",
                                json={"answer_value": "One month", "answer_scope": "this_employer"})
    assert r.status_code == 200
    assert {a["id"] for a in r.json()} == {str(first.id), str(same_employer.id)}
    answer = await session.scalar(select(Answer))
    assert (answer.value, answer.scope, answer.scope_ref, answer.settled) == (
        "One month", AnswerScope.this_employer, "Acme", True)
    assert answer.patterns.canonical == "What is your notice period?" and answer.material is False
    await session.refresh(other)
    assert other.status == PendingStatus.open
    audit = await session.scalar(select(AuditEvent).where(AuditEvent.action == "answer.saved_from_pending"))
    assert audit.detail["scope"] == "this_employer"


async def test_answer_scope_all_matching_settles_everything_and_scope_defaults_come_from_settings(
        owner_client, session) -> None:
    _, a = await _unknown_question(session, "q:a", employer="Acme", country="ZM")
    _, b = await _unknown_question(session, "q:a", employer="Other", country=None)
    _, m = await _unknown_question(session, "q:m", employer="Acme", country="ZM", material=True)
    await session.commit()
    r = await owner_client.post(f"/api/pending-actions/{a.id}/answer", json={"answer_value": "30 days"})
    assert {x["id"] for x in r.json()} == {str(a.id), str(b.id)}  # routine default scope: all_matching
    r = await owner_client.post(f"/api/pending-actions/{m.id}/answer", json={"answer_value": "Yes"})
    assert r.status_code == 200
    answers = {x.value: x for x in await session.scalars(select(Answer))}
    assert answers["30 days"].scope == AnswerScope.all_matching and answers["30 days"].scope_ref is None
    assert answers["Yes"].scope == AnswerScope.this_application and answers["Yes"].material is True  # material default
    assert answers["Yes"].scope_ref


async def test_answer_by_country_and_resolve_endpoint(owner_client, session) -> None:
    _, a = await _unknown_question(session, "q:c", employer="Acme", country="ZM")
    _, b = await _unknown_question(session, "q:c", employer="Other", country="ZM")
    _, c = await _unknown_question(session, "q:c", employer="Third", country="KE")
    await session.commit()
    r = await owner_client.post(f"/api/pending-actions/{a.id}/resolve", json={
        "resolution": "answered", "answer_value": "Yes", "answer_scope": "this_country"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    await session.refresh(b)
    await session.refresh(c)
    assert b.status == PendingStatus.resolved and c.status == PendingStatus.open
    assert (await owner_client.post(f"/api/pending-actions/{c.id}/resolve", json={"resolution": "answered"})
            ).status_code == 422


async def test_answer_errors(owner_client, session) -> None:
    app = await make_app(session, await make_job(session))
    wrong = await make_pending(session, app, type_=T.sign_in)
    no_country = (await _unknown_question(session, "q:x", employer="Acme", country=None))[1]
    await session.commit()
    assert (await owner_client.post(f"/api/pending-actions/{wrong.id}/answer", json={"answer_value": "x"})
            ).status_code == 409
    assert (await owner_client.post(f"/api/pending-actions/{no_country.id}/answer", json={
        "answer_value": "x", "answer_scope": "this_country"})).status_code == 422
    # Wave 2: "continue" resolves a sign-in; a resolution that does not fit the type is refused.
    assert (await owner_client.post(f"/api/pending-actions/{wrong.id}/resolve", json={"resolution": "answered"})
            ).status_code == 422
    assert (await owner_client.post(f"/api/pending-actions/{wrong.id}/resolve", json={"resolution": "continue"})
            ).status_code == 200
    assert (await session.scalar(select(Answer))) is None


async def test_today_summary(owner_client, session) -> None:
    campaign = Campaign(name="C")
    session.add(campaign)
    await session.flush()
    best = await make_job(session, "Best Match", "Acme")
    ok = await make_job(session, "Fine Match", "Beta")
    taken = await make_job(session, "Taken", "Gamma")
    session.add_all([Assessment(job_id=best.id, campaign_id=campaign.id, score=91),
                     Assessment(job_id=ok.id, campaign_id=campaign.id, score=64),
                     Assessment(job_id=taken.id, campaign_id=campaign.id, score=99)])
    tomorrow = date.today() + timedelta(days=1)
    closing = await make_job(session, "Closing Soon", "Delta", deadline=tomorrow)
    app_closing = await make_app(session, closing, Stage.ready)
    applied = await make_app(session, taken, Stage.submitted, next_step="Chase HR", next_due=tomorrow)
    session.add(Run(kind=RunKind.sweep, trigger="schedule", status=RunStatus.succeeded, counts={"new_jobs": 7},
                    started_at=NOW - timedelta(hours=2), finished_at=NOW - timedelta(hours=1)))
    session.add(Source(connector="rss", name="Careers feed", access=SourceAccess.feed))
    await make_pending(session, app_closing, type_=T.approve, title="Approve CV", deadline=NOW + timedelta(days=1))
    await session.commit()
    body = (await owner_client.get("/api/today")).json()
    assert body["needs_you"] == 1 and body["needs_you_groups"][0]["actions"][0]["title"] == "Approve CV"
    assert body["last_sweep"]["status"] == "succeeded" and body["last_sweep"]["counts"] == {"new_jobs": 7}
    assert body["last_sweep_run_id"] == body["last_sweep"]["run_id"]
    assert [m["title"] for m in body["top_matches"]][:2] == ["Best Match", "Fine Match"]
    assert "Taken" not in [m["title"] for m in body["top_matches"]]  # already applied
    assert body["top_match_ids"] == [m["job_id"] for m in body["top_matches"]]
    kinds = {(u["kind"], u["application_id"]) for u in body["upcoming"]}
    assert ("deadline", str(app_closing.id)) in kinds and ("follow_up", str(applied.id)) in kinds
    assert {f["stage"]: f["count"] for f in body["funnel"]} == {"ready": 1, "submitted": 1}
    assert [s["name"] for s in body["sources"]] == ["Careers feed"] and body["sources"][0]["status"] == "unknown"
    assert body["spend"] == {"month_to_date_minor": 0, "reserved_minor": 0, "cap_minor": None, "currency": "USD",
                             "estimated_unbilled_minor": 0, "month_to_date_micros": 0, "reserved_micros": 0,
                             "cap_micros": None, "estimated_unbilled_micros": 0}
    assert len((await owner_client.get("/api/today", params={"top": 1})).json()["top_matches"]) == 1


async def test_today_with_nothing_yet_and_spend_from_the_ledger(owner_client, session) -> None:
    empty = (await owner_client.get("/api/today")).json()
    assert empty["needs_you"] == 0 and empty["last_sweep"] is None and empty["top_matches"] == []
    reservation = LedgerEntry(kind=LedgerKind.reservation, amount_micros=300 * M, currency="USD", stage="tailor")
    session.add(reservation)
    await session.flush()
    session.add_all([
        LedgerEntry(kind=LedgerKind.reservation, amount_micros=500 * M, currency="USD", stage="score"),
        LedgerEntry(kind=LedgerKind.reconciliation, amount_micros=120 * M, currency="USD", stage="tailor",
                    reservation_id=reservation.id),
        LedgerEntry(kind=LedgerKind.reconciliation, amount_micros=40 * M, currency="USD", stage="score", billed=False)])
    await session.commit()
    spend = (await owner_client.get("/api/today")).json()["spend"]
    assert spend["month_to_date_minor"] == 120 and spend["reserved_minor"] == 500
    assert spend["estimated_unbilled_minor"] == 40
