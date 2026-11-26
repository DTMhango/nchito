"""Portal accounts and the sign-in handoff (8.4): one action per tenant, notifications and reminders, continue to
the same runner, skip to manual handoff, and no secret anywhere (invented employers, example.com only)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import inspect, select

from app.apply import accounts, dispatch
from app.connect.notifier import OutboundMessage, register_notifier_factory
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    Application,
    Channel,
    PendingAction,
    PendingStatus,
    PortalAccount,
    Stage,
)
from app.models.platform import AuditEvent, Notification
from app.models.search import Assessment, AssessmentState, Availability, Job
from app.ops import notifications
from app.schemas.json_types import AgentTaskState, JobFacets
from tests.apply.helpers import setup_campaign
from tests.pipeline.matching.fakes import add_job

DEADLINE = date(2026, 12, 20)
DEADLINE_AT = datetime(2026, 12, 20, 23, 59, 59, tzinfo=UTC)
NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
ARCH = "https://arch.wd5.myworkdayjobs.com/en-US/ArchCareers/job/lusaka/analyst_R1"
ARCH2 = "https://arch.wd5.myworkdayjobs.com/en-US/ArchCareers/job/lusaka/actuary_R2"
BETA = "https://beta.wd3.myworkdayjobs.com/BetaJobs/job/x_R9"


class Recorder:
    channel = "telegram"

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def telegram():
    fake = Recorder()

    async def factory(session):
        return fake

    register_notifier_factory("telegram", factory)
    yield fake
    from app.connect import records

    register_notifier_factory("telegram", records.telegram_factory)


@pytest.fixture(autouse=True)
def fake_open_check():
    async def checker(session, job):
        return None

    dispatch.set_open_checker(checker)
    yield
    dispatch.set_open_checker(None)


async def role(session, campaign, *, title="Data Analyst", employer="Arch Example", url=ARCH, method="workday",
               score=90, deadline: date | None = DEADLINE, facets=None, stage=Stage.shortlisted):
    job = await add_job(session, title, employer, apply_url=url, apply_method=method, deadline=deadline,
                        facets=facets or {})
    assessment = Assessment(job_id=job.id, campaign_id=campaign.id, state=AssessmentState.scored, score=score,
                            base_score=score, filter_results=[], rubric_id=campaign.rubric_id)
    session.add(assessment)
    await session.flush()
    app = Application(job_id=job.id, campaign_id=campaign.id, assessment_id=assessment.id, stage=stage)
    session.add(app)
    await session.flush()
    return job, app


async def open_actions(session) -> list[PendingAction]:
    return list((await session.scalars(select(PendingAction).where(
        PendingAction.status == PendingStatus.open).order_by(PendingAction.created_at))).all())


async def channels_on(session, **extra) -> None:
    await settings_service.set_many(session, {"notifications.channels": ["telegram"], **extra}, actor="test")
    await session.commit()


# ----- identifying the tenant, and what is "needs an account" -------------------------------------


@pytest.mark.nodb
def test_portal_key_is_ats_plus_tenant_host():
    job = Job(apply_url=ARCH, apply_method="workday")
    ref = accounts.portal_ref(job)
    assert ref is not None and ref.key == "workday:arch.wd5.myworkdayjobs.com/archcareers"
    assert accounts.portal_ref(Job(apply_url=BETA, apply_method="unknown")).portal == "workday"  # from the host
    assert accounts.portal_ref(Job(apply_url="https://careers.example.com/x", apply_method="unknown")) is None


@pytest.mark.nodb
def test_unknown_account_need_is_not_no():
    kw = {"required": ["workday"], "account_free": ["lever"]}
    assert accounts.assess_need(Job(apply_method="workday"), **kw) == accounts.AccountNeed.yes
    assert accounts.assess_need(Job(apply_method="lever"), **kw) == accounts.AccountNeed.no
    unknown = Job(apply_method="somewhere_new")
    assert accounts.assess_need(unknown, **kw) == accounts.AccountNeed.unknown != accounts.AccountNeed.no
    yes_facet = Job(apply_method="somewhere_new", facets=JobFacets.model_validate({"needs_account": {"value": "yes"}}))
    assert accounts.assess_need(yes_facet, **kw) == accounts.AccountNeed.yes


async def test_routing_is_local_for_account_roles_and_configurable(session):
    campaign = await setup_campaign(session)
    wd, _ = await role(session, campaign)
    lever, _ = await role(session, campaign, method="lever", url="https://jobs.lever.co/x/1")
    odd, _ = await role(session, campaign, method="somewhere_new", url="https://jobs.example.com/1")
    assert await accounts.preferred_runner_kind(session, wd) == "pc"
    assert await accounts.preferred_runner_kind(session, odd) == "pc"  # unknown is treated like "needs one"
    assert await accounts.preferred_runner_kind(session, lever) is None
    await settings_service.set_value(session, "accounts.runner_for_account_roles", "server", actor="test")
    assert await accounts.preferred_runner_kind(session, wd) == "server"


# ----- known early: one action per tenant ---------------------------------------------------------


async def test_one_action_per_tenant_listing_every_waiting_application(session):
    campaign = await setup_campaign(session)
    await role(session, campaign, title="Data Analyst")
    await role(session, campaign, title="Actuary", url=ARCH2, deadline=date(2026, 12, 10))
    await role(session, campaign, title="Pricing Lead", employer="Beta Example", url=BETA)
    await role(session, campaign, title="Low score", score=40, url="https://gamma.wd1.myworkdayjobs.com/G/job/1",
               employer="Gamma Example")
    await role(session, campaign, title="Unknown portal", method="somewhere_new", url="https://x.example.com/1",
               employer="Delta Example")
    await session.commit()
    first = await accounts.tick(session, NOW)
    await session.commit()
    again = await accounts.tick(session, NOW)
    await session.commit()
    assert (first.raised, first.joined) == (2, 1) and (again.raised, again.joined) == (0, 0)
    actions = await open_actions(session)
    assert len(actions) == 2
    arch = next(a for a in actions if "Arch" in a.title)
    assert arch.title == "Create an account at Arch Example careers: 2 applications are waiting"
    assert {e["title"] for e in arch.detail["applications"]} == {"Data Analyst", "Actuary"}
    assert arch.detail["kind"] == "create_account" and arch.type.value == "create_account"
    assert arch.deadline == datetime(2026, 12, 10, 23, 59, 59, tzinfo=UTC)  # the nearest
    assert arch.group_key == "portal:workday:arch.wd5.myworkdayjobs.com/archcareers"
    beta = next(a for a in actions if "Beta" in a.title)
    assert beta.title.endswith("1 application is waiting")


async def test_signed_in_tenant_raises_nothing_and_created_account_asks_to_sign_in(session):
    campaign = await setup_campaign(session)
    await role(session, campaign)
    session.add(PortalAccount(portal="workday", tenant="arch.wd5.myworkdayjobs.com/archcareers", status="created"))
    await session.commit()
    await accounts.tick(session, NOW)
    (action,) = await open_actions(session)
    assert action.detail["kind"] == "sign_in" and action.title.startswith("Sign in at Arch Example careers")
    acct = await session.scalar(select(PortalAccount))
    acct.status, acct.signed_in_runner = "signed_in", "pc"
    await session.commit()
    result = await accounts.tick(session, NOW)  # the account is ready: the early request closes itself
    await session.commit()
    assert result.closed == 1 and await open_actions(session) == []


# ----- notification content and reminder escalation -----------------------------------------------


async def test_notification_carries_link_runner_waiting_and_deadline(session, telegram):
    campaign = await setup_campaign(session)
    await role(session, campaign, title="Data Analyst")
    await role(session, campaign, title="Actuary", url=ARCH2)
    await channels_on(session)
    await accounts.tick(session, NOW)
    await session.commit()
    await accounts.tick(session, NOW)  # repeated ticks never send a second one
    await session.commit()
    await notifications.collect(session, NOW)  # collect would use the same key: no duplicate either
    await session.commit()
    await notifications.deliver_due(session, datetime.now(UTC).replace(hour=12, minute=0))
    assert len(telegram.sent) == 1
    message = telegram.sent[0]
    assert "Create an account at Arch Example careers: 2 applications are waiting" in message.title
    body = message.body or ""
    assert "https://arch.wd5.myworkdayjobs.com/ArchCareers" in body.replace("archcareers", "ArchCareers") or (
        "arch.wd5.myworkdayjobs.com" in body)
    assert "PC runner's browser profile" in body and "Data Analyst" in body and "Actuary" in body
    assert "2026-12-20" in body
    assert [b.label for b in message.buttons] == ["I've signed in, continue", "Open"]
    assert message.buttons[0].url.endswith("intent=continue")


async def reminder_titles(session) -> list[str]:
    rows = await session.scalars(select(Notification).order_by(Notification.created_at))
    return [n.dedupe_key for n in rows]


async def test_reminders_escalate_toward_the_deadline_at_default_offsets(session, telegram):
    campaign = await setup_campaign(session)
    await role(session, campaign, deadline=DEADLINE)
    await channels_on(session)
    await accounts.tick(session, DEADLINE_AT - timedelta(hours=100))  # outside every offset: only the first message
    await session.commit()
    assert len(await reminder_titles(session)) == 1
    steps = [(timedelta(hours=80), 0), (timedelta(hours=70), 1), (timedelta(hours=60), 0), (timedelta(hours=20), 1),
             (timedelta(hours=10), 0), (timedelta(hours=5), 1), (timedelta(hours=2), 0)]
    for before, expected in steps:  # default offsets 72, 24 and 6 hours
        result = await accounts.tick(session, DEADLINE_AT - before)
        await session.commit()
        assert result.reminded == expected, before
    keys = await reminder_titles(session)
    assert len(keys) == 4 and keys[1].endswith(":r72") and keys[2].endswith(":r24") and keys[3].endswith(":r6")
    assert (await accounts.tick(session, DEADLINE_AT + timedelta(hours=1))).reminded == 0  # nothing after the deadline


async def test_reminders_follow_a_changed_cadence(session):
    campaign = await setup_campaign(session)
    await role(session, campaign, deadline=DEADLINE)
    await settings_service.set_value(session, "accounts.reminder_offsets_hours", [48, 12], actor="test")
    await channels_on(session)
    await accounts.tick(session, DEADLINE_AT - timedelta(hours=60))
    await session.commit()
    assert (await accounts.tick(session, DEADLINE_AT - timedelta(hours=47))).reminded == 1
    await session.commit()
    assert (await accounts.tick(session, DEADLINE_AT - timedelta(hours=30))).reminded == 0  # 72h would not apply now
    assert (await accounts.tick(session, DEADLINE_AT - timedelta(hours=11))).reminded == 1
    await session.commit()
    assert len(await reminder_titles(session)) == 3


async def test_reminders_respect_quiet_hours(session, telegram):
    campaign = await setup_campaign(session)
    await role(session, campaign, deadline=DEADLINE)
    await channels_on(session)
    await accounts.tick(session, DEADLINE_AT - timedelta(hours=100))
    await session.commit()
    late = datetime.now(UTC).replace(hour=20, minute=30)  # 22:30 in Lusaka, inside the quiet hours
    await notifications.deliver_due(session, late)
    assert telegram.sent == []
    await notifications.deliver_due(session, datetime.now(UTC).replace(hour=12, minute=0))
    assert len(telegram.sent) == 1


# ----- blockers raised by the runner ----------------------------------------------------------------


async def blocked_task(session, app: Application, runner: str = "11111111-1111-1111-1111-111111111111"):
    task = AgentTask(type=AgentTaskType.apply, application_id=app.id, status=AgentTaskStatus.blocked,
                     checkpoint=AgentTaskState(), preferred_runner="pc")
    session.add(task)
    await session.flush()
    return task, runner


async def test_register_blocker_joins_the_tenant_action_and_captcha_is_per_task(session):
    campaign = await setup_campaign(session)
    j1, a1 = await role(session, campaign, title="Data Analyst")
    j2, a2 = await role(session, campaign, title="Actuary", url=ARCH2)
    await session.commit()
    await accounts.tick(session, NOW)  # known early
    t1, runner = await blocked_task(session, a1)
    t2, _ = await blocked_task(session, a2)
    one = await accounts.register_blocker(session, kind="sign_in", job=j1, task_id=t1.id, runner_id=runner,
                                          detail={})
    two = await accounts.register_blocker(session, kind="sign_in", job=j2, task_id=t2.id, runner_id=runner,
                                          detail={})
    assert one.id == two.id and len(await open_actions(session)) == 1
    assert {t["task_id"] for t in two.detail["tasks"]} == {str(t1.id), str(t2.id)}
    assert two.detail["kind"] == "sign_in" and two.detail["portal_key"].startswith("workday:arch")
    assert two.detail["task_id"] == str(t2.id) and two.detail["runner_id"] == runner
    cap = await accounts.register_blocker(session, kind="captcha", job=j1, task_id=t1.id, runner_id=runner)
    again = await accounts.register_blocker(session, kind="captcha", job=j1, task_id=t1.id, runner_id=runner)
    assert cap.id == again.id != one.id and cap.group_key == f"task:{t1.id}:captcha"
    with pytest.raises(ValueError):
        await accounts.register_blocker(session, kind="login_form", job=j1, task_id=t1.id, runner_id=runner)


async def test_continue_returns_every_task_to_the_same_runner_and_marks_the_account(owner_client):
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s)
        j1, a1 = await role(s, campaign, title="Data Analyst")
        j2, a2 = await role(s, campaign, title="Actuary", url=ARCH2)
        t1, runner = await blocked_task(s, a1)
        t2, _ = await blocked_task(s, a2)
        action = await accounts.register_blocker(s, kind="sign_in", job=j1, task_id=t1.id, runner_id=runner)
        await accounts.register_blocker(s, kind="sign_in", job=j2, task_id=t2.id, runner_id=runner)
        await s.commit()
        action_id, ids = action.id, (t1.id, t2.id, a1.id)
    r = await owner_client.post(f"/api/pending-actions/{action_id}/resolve", json={"resolution": "continue"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved" and r.json()["resolution"]["not_resumed"] == []
    async with get_sessionmaker()() as s:
        for tid in ids[:2]:
            task = await s.get(AgentTask, tid)
            assert task.status == AgentTaskStatus.queued
            assert task.payload["resume"] is True and task.payload["resume_runner_token_id"] == runner
            assert task.payload["resume_runner_kind"] == "pc"
        acct = await s.scalar(select(PortalAccount))
        assert acct.status.value == "signed_in" and acct.signed_in_runner == "pc" and acct.last_sign_in_at
        assert (await s.get(Application, ids[2])).applied_at is None  # still needs a submit permit
        assert await open_actions(s) == []
    # the next role at this tenant no longer raises anything
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s)
        await role(s, campaign, title="Third role", url="https://arch.wd5.myworkdayjobs.com/ArchCareers/job/z_R3")
        await s.commit()
        await accounts.tick(s, NOW)
        assert await open_actions(s) == []


async def test_continue_does_not_resume_a_closed_posting_or_a_duplicate(owner_client):
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s)
        j1, a1 = await role(s, campaign, title="Data Analyst")
        j2, a2 = await role(s, campaign, title="Actuary", url=ARCH2)
        j3, a3 = await role(s, campaign, title="Pricing", url="https://arch.wd5.myworkdayjobs.com/ArchCareers/job/p")
        for j, a in ((j1, a1), (j2, a2), (j3, a3)):
            j.apply_method = "workday"
        j1.availability = Availability.closed  # the posting closed while the owner was away
        a3.applied_at = datetime(2026, 11, 30, tzinfo=UTC)  # already sent (duplicate protection)
        tasks = []
        for j, a in ((j1, a1), (j2, a2), (j3, a3)):
            t, runner = await blocked_task(s, a)
            tasks.append(t)
            action = await accounts.register_blocker(s, kind="sign_in", job=j, task_id=t.id, runner_id=runner)
        await s.commit()
        action_id, ids, task_ids = action.id, (a1.id, a2.id, a3.id), [t.id for t in tasks]
    r = await owner_client.post(f"/api/pending-actions/{action_id}/resolve", json={"resolution": "continue"})
    assert r.status_code == 200, r.text
    reasons = {x["application_id"]: x["reason"] for x in r.json()["resolution"]["not_resumed"]}
    assert reasons[str(ids[0])] == "the posting has closed"
    assert reasons[str(ids[2])] == "it has already been sent"
    assert str(ids[1]) not in reasons
    async with get_sessionmaker()() as s:
        statuses = [(await s.get(AgentTask, t)).status for t in task_ids]
        assert statuses == [AgentTaskStatus.cancelled, AgentTaskStatus.queued, AgentTaskStatus.cancelled]


async def test_captcha_and_verification_code_use_the_continue_flow(owner_client):
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s)
        j1, a1 = await role(s, campaign)
        t1, runner = await blocked_task(s, a1)
        cap = await accounts.register_blocker(s, kind="captcha", job=j1, task_id=t1.id, runner_id=runner)
        code = await accounts.register_blocker(s, kind="verification_code", job=j1, task_id=t1.id, runner_id=runner)
        assert code.detail["kind"] == "verification_code" and code.type.value == "sign_in"
        await s.commit()
        cap_id, code_id, task_id = cap.id, code.id, t1.id
    assert code.group_key != cap.group_key  # two actions: one continue must not close both
    assert (await owner_client.post(f"/api/pending-actions/{cap_id}/resolve",
                                    json={"resolution": "continue"})).status_code == 200
    async with get_sessionmaker()() as s:
        # The verification code still needs the owner: it stays open and the task stays blocked.
        assert (await s.get(PendingAction, code_id)).status == PendingStatus.open
        assert (await s.get(AgentTask, task_id)).status == AgentTaskStatus.blocked
        assert await s.scalar(select(PortalAccount)) is None  # a CAPTCHA does not mean "signed in"
    assert (await owner_client.post(f"/api/pending-actions/{code_id}/resolve",
                                    json={"resolution": "continue"})).status_code == 200
    async with get_sessionmaker()() as s:
        task = await s.get(AgentTask, task_id)
        assert task.status == AgentTaskStatus.queued and task.payload["resume_runner_token_id"] == runner


# ----- "I can't / skip" ----------------------------------------------------------------------------


async def test_cannot_sign_in_moves_to_manual_handoff_or_skips(owner_client):
    async with get_sessionmaker()() as s:
        campaign = await setup_campaign(s)
        j1, a1 = await role(s, campaign, title="Data Analyst")
        _j2, a2 = await role(s, campaign, title="Actuary", url=ARCH2)
        await s.commit()
        await accounts.tick(s, NOW)
        t1, runner = await blocked_task(s, a1)
        action = await accounts.register_blocker(s, kind="create_account", job=j1, task_id=t1.id, runner_id=runner)
        await s.commit()
        action_id, ids, task_id = action.id, (a1.id, a2.id), t1.id
    url = f"/api/portal-accounts/actions/{action_id}/give-up"
    r = await owner_client.post(url, json={"outcome": "manual_handoff", "application_ids": [str(ids[0])]})
    assert r.status_code == 200, r.text
    assert r.json() == {"outcome": "manual_handoff", "handled": [str(ids[0])], "remaining": 1, "closed": False}
    async with get_sessionmaker()() as s:
        assert (await s.get(Application, ids[0])).channel == Channel.manual
        assert (await s.get(AgentTask, task_id)).status == AgentTaskStatus.cancelled
        assert (await s.get(PendingAction, action_id)).title.endswith("1 application is waiting")
    stranger = await owner_client.post(url, json={"outcome": "skipped", "application_ids": [str(ids[0])]})
    assert stranger.status_code == 422  # no longer waiting here
    r = await owner_client.post(url, json={"outcome": "skipped", "note": "not worth an account"})
    assert r.status_code == 200 and r.json()["closed"] is True and r.json()["handled"] == [str(ids[1])]
    async with get_sessionmaker()() as s:
        assert (await s.get(Application, ids[1])).stage == Stage.skipped
        assert (await s.get(PendingAction, action_id)).status == PendingStatus.resolved
    assert (await owner_client.post(url, json={"outcome": "skipped"})).status_code == 409


# ----- the registry: CRUD, audit, never a secret -----------------------------------------------------


async def test_portal_account_crud_is_owner_only_and_audited(owner_client):
    from app.api.deps import RequireOwner
    from app.api.routers.portal_accounts import router

    assert RequireOwner in router.dependencies
    r = await owner_client.post("/api/portal-accounts", json={
        "portal": "Workday", "tenant": "Arch.wd5.myworkdayjobs.com/ArchCareers", "email_used": "me@example.com",
        "notes": "created 1 Dec"})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["key"] == "workday:arch.wd5.myworkdayjobs.com/archcareers" and row["status"] == "none"
    dup = await owner_client.post("/api/portal-accounts", json={"portal": "workday", "tenant": row["tenant"]})
    assert dup.status_code == 409
    needs_runner = await owner_client.patch(f"/api/portal-accounts/{row['id']}", json={"status": "signed_in"})
    assert needs_runner.status_code == 422
    ok = await owner_client.patch(f"/api/portal-accounts/{row['id']}",
                                  json={"status": "signed_in", "signed_in_runner": "pc"})
    assert ok.status_code == 200 and ok.json()["last_sign_in_at"] and ok.json()["signed_in_runner"] == "pc"
    assert [x["id"] for x in (await owner_client.get("/api/portal-accounts?status=signed_in")).json()["items"]] == [
        row["id"]]
    assert (await owner_client.delete(f"/api/portal-accounts/{row['id']}")).status_code == 204
    assert (await owner_client.get(f"/api/portal-accounts/{row['id']}")).status_code == 404
    async with get_sessionmaker()() as s:
        actions = {a for (a,) in (await s.execute(select(AuditEvent.action))).all()}
    assert {"portal_account.created", "portal_account.updated", "portal_account.deleted"} <= actions


@pytest.mark.parametrize("field", ["password", "Password", "passcode", "secret", "api_token", "login_pin"])
async def test_api_rejects_any_password_or_secret_field(owner_client, field):
    body = {"portal": "workday", "tenant": "x.myworkdayjobs.com/x", field: "hunter2"}
    r = await owner_client.post("/api/portal-accounts", json=body)
    assert r.status_code == 422 and "never stored" in r.text
    created = await owner_client.post("/api/portal-accounts", json={"portal": "workday", "tenant": "y.example.com"})
    r = await owner_client.patch(f"/api/portal-accounts/{created.json()['id']}", json={field: "hunter2"})
    assert r.status_code == 422
    assert field.lower() not in str((await owner_client.get(f"/api/portal-accounts/{created.json()['id']}")).json())


@pytest.mark.nodb
def test_no_secret_column_on_the_model_or_in_the_api_output():
    from app.api.routers.portal_accounts import PortalAccountOut, PortalAccountPatch, PortalAccountWrite

    words = ("password", "passwd", "passcode", "secret", "credential", "token", "pin", "otp", "cookie")
    columns = [c.name for c in inspect(PortalAccount).columns]
    fields = [*PortalAccountOut.model_fields, *PortalAccountWrite.model_fields, *PortalAccountPatch.model_fields]
    for name in columns + fields:
        assert not any(w == name or name.startswith(w) or name.endswith("_" + w) for w in words), name


async def test_approving_a_browser_packet_raises_the_sign_in_request_at_once(session):
    from app.apply import approval, packets
    from app.pipeline import conflicts
    from tests.apply.helpers import browser_draft

    campaign = await setup_campaign(session)
    job, app = await role(session, campaign, title="Data Analyst")
    await conflicts.resolve_employers(session, [job.employer], now=NOW)
    built = await packets.build(session, app, browser_draft(job.apply_url), actor="owner", now=NOW)
    await approval.approve(session, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                           channel="browser", actor="owner", now=NOW)
    actions = await open_actions(session)  # no accounts tick needed
    assert len(actions) == 1 and actions[0].detail["kind"] == "create_account"
    assert actions[0].detail["applications"][0]["application_id"] == str(app.id)
