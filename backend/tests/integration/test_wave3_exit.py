"""Wave 3 exit tests: browser applications through the real MCP gateway, in process, with fakes only.

(a) A Greenhouse-style application: the browser channel queues the task, a PC runner claims it over MCP, gets the
    packet, is cleared (permit granted and consumed at clearance, bound to the packet hash and its task), uploads
    evidence and reports; the application is submitted and the audit chain is complete. A second runner can neither
    claim the task nor get a permit for it.
(b) A Workday-style role that needs an account: the sign-in request is raised at approval, per portal, listing the
    waiting applications; the runner meets the sign-in wall and raises it; the owner's "continue" gives the task
    back to the same runner with its checkpoint; the runner still needs (and gets) a permit, then submits.
(c) DESIGN 18.6 release gates. Covered elsewhere: gate 1 tests/apply/test_dispatch.py::
    test_pay_answer_changed_during_the_delay_old_packet_cannot_go_out; gate 2 tests/apply/test_dispatch.py::
    test_worker_dies_after_the_provider_accepted_restart_reconciles_without_a_second_send and
    test_restore_starts_paused_and_resume_requires_reconciliation; gate 3 tests/pipeline/matching/
    test_conflicts.py::test_cross_campaign_setting_both_ways; gate 4 tests/tailoring/test_checks.py::
    test_never_together_across_cv_and_letter with tests/apply/test_packets_permits.py::
    test_automatic_approval_waits_for_owner_on_an_unknown (a never_together block refuses approval); gate 5 before
    clearance tests/gateway/test_gateway.py::test_redirect_stops_the_runner_and_shows_what_was_released and
    test_declaration_blocker_frees_the_runner. Not yet covered, and added here: gate 5 *after* clearance over MCP
    (the runner is cleared, then the form redirects: it stops, the owner sees what was released, nothing is sent).
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from app.apply import approval, dispatch, packets
from app.core.clock import FakeClock
from app.gateway import common, server
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    Application,
    DispatchAttempt,
    DispatchStatus,
    PendingAction,
    PendingActionType,
    PendingStatus,
    SubmitPermit,
)
from app.models.platform import AuditEvent
from app.models.search import Availability, Job
from app.pipeline import conflicts
from tests.apply.helpers import browser_draft, setup_app, setup_campaign
from tests.gateway.helpers import ENTERED, URL, hand_out_task, load, make_token, maker, world
from tests.pipeline.matching.helpers import NOW

WORKDAY = "https://arch.wd3.myworkdayjobs.com/en-US/ArchCareers/job/Lusaka/Actuary_R1"


@pytest.fixture(autouse=True)
def clock():
    async def still_open(session, job: Job) -> None:  # recorded answer of the posting's own page
        job.availability, job.last_checked_at = Availability.open, NOW

    common.set_clock(FakeClock(NOW))
    server.limiter.reset()
    dispatch.set_open_checker(still_open)
    yield
    dispatch.set_open_checker(None)
    common.set_clock(None)


@pytest.fixture
def store(monkeypatch, tmp_path):
    from app.connect import local_store

    monkeypatch.setattr(local_store, "default_file_store", lambda: local_store.LocalFileStore(tmp_path))
    return tmp_path


@asynccontextmanager
async def runner(app, secret: str):
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                             headers={"Authorization": f"Bearer {secret}"}, timeout=30)
    async with http, streamable_http_client("http://testserver/mcp", http_client=http) as (read, write, _), \
            ClientSession(read, write) as session:
        await session.initialize()
        yield Mcp(session, http)


class Mcp:
    def __init__(self, session: ClientSession, http: httpx.AsyncClient) -> None:
        self.session, self.http = session, http

    async def call(self, tool: str, **args: Any) -> dict[str, Any]:
        result = await self.session.call_tool(tool, args)
        assert not result.isError, result.content
        return result.structuredContent

    async def refused(self, tool: str, **args: Any) -> str:
        result = await self.session.call_tool(tool, args)
        assert result.isError, result.structuredContent
        return json.loads(result.content[0].text)["code"]


async def audit_actions(*subjects: uuid.UUID) -> list[str]:
    async with maker()() as s:
        rows = await s.scalars(select(AuditEvent).where(AuditEvent.subject_id.in_([str(x) for x in subjects]))
                               .order_by(AuditEvent.created_at, AuditEvent.id))
        return [r.action for r in rows]


async def upload_evidence(mcp: Mcp, task_id: str) -> str:
    link = await mcp.call("evidence_upload_url", task_id=task_id, content_type="image/png")
    r = await mcp.http.put(link["upload_url"].removeprefix("http://testserver"), content=b"\x89PNG confirmation",
                           headers={"Content-Type": "image/png"})
    assert r.status_code == 201, r.text
    return link["ref"]


# ----- (a) Greenhouse-style: claim, packet, clearance, evidence, submitted -----------------------------------


async def test_a_greenhouse_style_application_end_to_end_over_mcp(app, store):
    w = await world()  # approved browser packet; the browser channel queued its task (no permit taken)
    _, secret_b = await make_token("pc-b2")
    async with runner(app, w.secret_a) as a, runner(app, secret_b) as b:
        task = await a.call("next_task")
        assert task["type"] == "apply" and task["posting_url"] == URL
        task_id = task["task_id"]
        assert (await b.call("next_task"))["task_id"] is None  # nothing else to claim
        packet = await a.call("get_packet", task_id=task_id)
        assert packet["destination_domain"] == "boards.greenhouse.io"
        await a.call("save_checkpoint", task_id=task_id, state={"step": "form filled", "url": URL})
        assert await b.refused("request_submit_permit", task_id=task_id, summary="x", entered_answers=ENTERED,
                               attached_files_sha256=[], current_url=URL) == "not_your_task"
        granted = await a.call("request_submit_permit", task_id=task_id, summary="ready", entered_answers=ENTERED,
                               attached_files_sha256=[], current_url=URL)
        assert granted["decision"] == "granted", granted
        # Single use: a second permit for the application is refused while this one is out.
        again = await a.call("request_submit_permit", task_id=task_id, summary="again", entered_answers=ENTERED,
                             attached_files_sha256=[], current_url=URL)
        assert again["decision"] == "denied"
        ref = await upload_evidence(a, task_id)
        done = await a.call("report_result", task_id=task_id, outcome="submitted", permit_id=granted["permit_id"],
                            confirmation_text="Thank you for applying to Acme Example", screenshot_ref=ref)
        assert done == {"recorded": True, "application_stage": "submitted"}

    permit = await load(SubmitPermit, uuid.UUID(granted["permit_id"]))
    assert permit.used_at is not None and permit.agent_task_id == uuid.UUID(task_id)
    async with maker()() as s:
        attempts = (await s.scalars(select(DispatchAttempt).where(DispatchAttempt.application_id == w.app_id))).all()
        assert len(attempts) == 1 and attempts[0].status == DispatchStatus.sent
        assert attempts[0].evidence.kind == "confirmation_page" and attempts[0].evidence.screenshot_ref == ref
        assert attempts[0].permit_id == permit.id and attempts[0].packet_hash == permit.packet_hash
    task_row = await load(AgentTask, uuid.UUID(task_id))
    assert task_row.status == AgentTaskStatus.done and task_row.released["given"]
    chain = await audit_actions(uuid.UUID(task_id), attempts[0].id, permit.id)
    for step in ("browser.task_queued", "browser.task_claimed", "gateway.packet_released", "permit.granted",
                 "permit.consumed", "dispatch.reserved", "browser.cleared", "gateway.permit_granted",
                 "gateway.result_reported"):
        assert step in chain, (step, chain)
    assert chain.index("browser.task_claimed") < chain.index("permit.consumed") < chain.index("browser.cleared")
    assert (await load(Application, w.app_id)).stage.value == "submitted"


# ----- (b) Workday-style: account needed, sign-in, continue, same runner, permit, submit ---------------------


async def workday_app(employer: str, url: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker()() as s:
        campaign = await setup_campaign(s)
        job, app = await setup_app(s, campaign, employer=employer, now=NOW, resolve=False)
        job.apply_url = url
        await conflicts.resolve_employers(s, [employer], now=NOW)
        built = await packets.build(s, app, browser_draft(url), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="browser", actor="owner", now=NOW)
        await hand_out_task(s, app.id)
        await s.commit()
        return app.id, job.id


async def test_b_workday_style_role_needing_an_account(app, owner_client):
    first, _ = await workday_app("Arch Example", WORKDAY)
    second, _ = await workday_app("Arch Example Re", WORKDAY.replace("Actuary_R1", "Analyst_R2"))
    async with maker()() as s:  # raised at approval, one per portal tenant, listing every waiting application
        early = (await s.scalars(select(PendingAction).where(PendingAction.status == PendingStatus.open))).all()
        assert len(early) == 1 and early[0].detail["kind"] == "create_account"
        assert {e["application_id"] for e in early[0].detail["applications"]} == {str(first), str(second)}
        task = await s.scalar(select(AgentTask).where(AgentTask.application_id == first))
        assert task.preferred_runner == "pc"  # needs an account: where the owner can sign in
    pc_a, secret_a = await make_token("pc-a")
    _, secret_b = await make_token("pc-b")
    srv, secret_srv = await make_token("srv", kind="server")
    async with runner(app, secret_a) as a, runner(app, secret_b) as b, runner(app, secret_srv) as server_runner:
        assert (await server_runner.call("next_task"))["task_id"] is None  # account roles never go to the server
        claimed = await a.call("next_task")
        task_id = claimed["task_id"]
        assert task_id == str(task.id)
        await a.call("get_packet", task_id=task_id)
        await a.call("save_checkpoint", task_id=task_id, state={"step": "sign-in wall", "url": WORKDAY})
        blocked = await a.call("raise_blocker", task_id=task_id, type="sign_in", detail="Sign in to apply",
                               url=WORKDAY)
        assert blocked["pending_action_id"] == str(early[0].id)  # joins the tenant's request
        r = await owner_client.post(f"/api/pending-actions/{early[0].id}/resolve", json={"resolution": "continue"})
        assert r.status_code == 200, r.text
        other = await b.call("next_task")  # B may take the second role, never A's resumed task
        assert other["task_id"] != task_id
        resumed = await a.call("next_task")
        assert resumed["task_id"] == task_id and resumed["checkpoint"]["step"] == "sign-in wall"
        # Still needs a permit: a report now would be a violation, so the runner asks first.
        granted = await a.call("request_submit_permit", task_id=task_id, summary="ready", entered_answers=ENTERED,
                               attached_files_sha256=[], current_url=WORKDAY)
        assert granted["decision"] == "granted", granted
        done = await a.call("report_result", task_id=task_id, outcome="submitted", permit_id=granted["permit_id"],
                            reference="WD-R1-0042")
        assert done["application_stage"] == "submitted"
    async with maker()() as s:
        action = await s.get(PendingAction, early[0].id)
        assert action.status == PendingStatus.resolved and task_id in action.resolution["resumed_tasks"]
        from app.models.applications import PortalAccount

        account = await s.scalar(select(PortalAccount))
        assert account is not None and account.status.value == "signed_in" and account.signed_in_runner == "pc"
    assert pc_a and srv


# ----- (c) release gate 5 after clearance ----------------------------------------------------------------------


async def test_c_gate5_redirect_after_clearance_stops_and_nothing_is_sent(app):
    w = await world()
    async with runner(app, w.secret_a) as a:
        task_id = (await a.call("next_task"))["task_id"]
        await a.call("get_packet", task_id=task_id)
        granted = await a.call("request_submit_permit", task_id=task_id, summary="ready", entered_answers=ENTERED,
                               attached_files_sha256=[], current_url=URL)
        assert granted["decision"] == "granted"
        out = await a.call("raise_blocker", task_id=task_id, type="redirect_off_domain",
                           detail="Submit went to another site", url="https://elsewhere.example.org/apply")
    action = await load(PendingAction, uuid.UUID(out["pending_action_id"]))
    assert action.type == PendingActionType.redirect_off_domain
    assert action.detail["released"][0]["answers"][0]["value"] == "One month"  # what already left
    async with maker()() as s:
        attempt = await s.scalar(select(DispatchAttempt).where(DispatchAttempt.application_id == w.app_id))
        assert attempt.status == DispatchStatus.failed  # settled as not sent, never retried automatically
        assert (await s.get(Application, w.app_id)).stage.value == "ready"
        job = await s.scalar(select(Job).join(Application, Application.job_id == Job.id)
                             .where(Application.id == w.app_id))
        assert job is not None
