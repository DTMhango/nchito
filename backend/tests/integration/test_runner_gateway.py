"""The server runner (``runner/server``, package ``nchito_runner``) against the REAL gateway.

The backend app runs in process (``httpx.ASGITransport``: MCP at ``/mcp``, signed file and evidence routes) on the
test database; the runner's own ``McpGateway``, ``Runner`` and ``Toolbox`` drive real headless Chromium through a
static fixture form on 127.0.0.1, with a scripted stand-in for the model (no paid calls, no network beyond
127.0.0.1 and the test database).

- Happy path: one submit, the CV fetched through the gateway's signed link, evidence uploaded through
  ``evidence_upload_url``, the application ``submitted`` and the audit chain complete; a second runner can neither
  claim the task nor get a permit for it while the first holds it.
- Permit denied (a dry run is always denied): no submit click, the task is released back to the queue.
- Permit held for the owner (a question the packet does not hold): no submit click, the task waits.

Needs the runner package and Playwright's Chromium next to the backend, on one ``mcp`` 1.x (see RUNBOOK, "Server
runner", "Testing against the real gateway"). The backend's normal suite skips this module cleanly without them.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("nchito_runner", reason="the server runner package (runner/server) is not installed here")
pytest.importorskip("playwright.async_api", reason="Playwright is not installed here")

from nchito_runner.budget import Budget, Caps
from nchito_runner.config import RunnerConfig
from nchito_runner.gateway import EXPECTED_TOOLS, GatewayError, McpGateway
from nchito_runner.toolbox import Toolbox
from nchito_runner.worker import Runner
from sqlalchemy import select

from app.apply import approval, dispatch, packets
from app.core.clock import FakeClock
from app.core.settings import service as settings_service
from app.gateway import common, server
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    Application,
    DispatchAttempt,
    DispatchStatus,
    SubmitPermit,
)
from app.models.documents import ApplicationDocument
from app.models.platform import AuditEvent
from app.models.search import Availability, Job
from app.pipeline import conflicts
from app.schemas.json_types import PacketFile
from tests.apply.helpers import setup_app, setup_campaign
from tests.gateway.helpers import load, make_token, maker
from tests.pipeline.matching.helpers import NOW


def _chromium_problem() -> str | None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return None
    except Exception as exc:
        return f"Playwright Chromium cannot start here ({type(exc).__name__}); run `playwright install chromium`"


_PROBLEM = _chromium_problem()
pytestmark = pytest.mark.skipif(_PROBLEM is not None, reason=_PROBLEM or "")

CV_BYTES = b"%PDF-1.4 invented example CV for the runner integration test\n"
CONFIRM = "Thank you for applying to Acme Example"
BASE = "http://testserver"

FORM = """<!doctype html><html><head><meta charset=utf-8><title>Acme Example - Data Analyst</title></head><body>
<h1>Data Analyst</h1>
<form method="POST" action="/apply/submit" enctype="multipart/form-data">
  <label for="email">Email</label><input id="email" name="email" type="email">
  <label for="notice">Notice period</label><input id="notice" name="notice" type="text">
  {extra}
  <label for="cv">CV</label><input id="cv" name="cv" type="file">
  <button type="submit">Submit application</button>
</form></body></html>"""
EXTRA = '<label for="salary">Expected salary</label><input id="salary" name="salary" type="text">'
THANKS = f"<!doctype html><html><body><h1>Received</h1><p>{CONFIRM}.</p><p>Reference: AE-778</p></body></html>"


# ----- the static form ------------------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server: _FormServer

    def log_message(self, *a: Any) -> None:
        pass

    def _send(self, body: str) -> None:
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._send(FORM.format(extra=EXTRA if self.path.startswith("/apply-extra") else ""))

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.posts.append({"path": self.path, "body": body})
        self._send(THANKS)


class _FormServer(ThreadingHTTPServer):
    posts: list[dict[str, Any]]


@pytest.fixture(scope="module")
def form() -> Iterator[_FormServer]:
    httpd = _FormServer(("127.0.0.1", 0), _Handler)
    httpd.posts = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _gateway_state(form: _FormServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    async def still_open(session: Any, job: Job) -> None:  # recorded answer of the posting's own page
        job.availability, job.last_checked_at = Availability.open, NOW

    from app.connect import local_store

    monkeypatch.setattr(local_store, "default_file_store", lambda: local_store.LocalFileStore(tmp_path / "files"))
    common.set_clock(FakeClock(NOW))
    server.limiter.reset()
    dispatch.set_open_checker(still_open)
    form.posts.clear()
    yield
    dispatch.set_open_checker(None)
    common.set_clock(None)


# ----- world: an approved browser packet with a CV, its task queued for the server runner ------------------------
# (the file is kind "other": a generated "cv" must come from a checked tailoring spec, which has its own tests)


async def ready_application(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    from app.connect.local_store import default_file_store

    async with maker()() as s:
        await settings_service.set_value(s, "runners.server_runner_enabled", True, actor="owner")
        await settings_service.set_value(s, "budget.monthly_cap_minor", 2000, actor="owner")  # paid agent work on
        campaign = await setup_campaign(s)
        job, app = await setup_app(s, campaign, employer="Acme Example", now=NOW, resolve=False)
        job.apply_url = url
        await conflicts.resolve_employers(s, ["Acme Example"], now=NOW)
        sha = hashlib.sha256(CV_BYTES).hexdigest()
        stored = await default_file_store().put(f"documents/{app.id}/cv.pdf", CV_BYTES, "application/pdf")
        doc = ApplicationDocument(application_id=app.id, kind="cv", fmt="pdf", template_key="classic",
                                  spec_hash="s" * 64, input_hash="i" * 64, content_hash=sha, file_key=stored.key,
                                  size_bytes=len(CV_BYTES), mime_type="application/pdf")
        s.add(doc)
        await s.flush()
        cv = PacketFile(name="cv.pdf", kind="other", sha256=sha, document_id=str(doc.id))
        draft = packets.PacketDraft(channel="browser", destination_url=url, sending_identity="owner@example.com",
                                    answers=[packets.DraftAnswer(question="Notice period", value="One month")],
                                    files=[cv])
        built = await packets.build(s, app, draft, actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="browser", actor="owner", now=NOW)
        queued = await dispatch.queue(s, app.id, actor="owner", now=NOW)  # the one hand-out path: the browser task
        assert queued.status == "queued" and queued.attempt is None, queued
        task = await s.scalar(select(AgentTask).where(AgentTask.application_id == app.id))
        assert task is not None
        task.preferred_runner = "server"  # routing has its own tests; here the server runner takes it
        await s.commit()
        return app.id, task.id


# ----- the runner, wired to the in-process app --------------------------------------------------------------------

Script = Callable[[Toolbox, dict[str, Any]], Awaitable[None]]


class ScriptedDriver:
    """Stands in for the model: a fixed tool-call script. No API call is made."""

    def __init__(self, script: Script) -> None:
        self.script, self.runs, self.error = script, 0, None

    async def run(self, box: Toolbox, task: dict[str, Any], budget: Budget) -> None:
        self.runs += 1
        try:
            await self.script(box, task)
        except BaseException as exc:
            self.error = exc
            raise


def gateway(app: Any, secret: str) -> McpGateway:
    return McpGateway(f"{BASE}/mcp", secret, transport=httpx.ASGITransport(app=app))


async def run_runner(app: Any, secret: str, tmp_path: Path, script: Script, **cfg: Any) -> tuple[str, ScriptedDriver]:
    config = RunnerConfig(nchito_url=BASE, token=secret, profile_dir=tmp_path / "profile", state_dir=tmp_path / "state",
                          heartbeat_seconds=5.0, **cfg)
    budget = Budget(config.state_dir / "budget.json", Caps(config.task_max_cost_usd, config.day_max_cost_usd,
                                                           config.task_max_tokens, config.day_max_tokens))
    driver = ScriptedDriver(script)
    gw = gateway(app, secret)
    try:
        status = await Runner(config, gw, driver, budget, clock=lambda: NOW).run_one()
    finally:
        await gw.close()
    if isinstance(driver.error, AssertionError):  # an assertion inside the scripted model is a test failure
        raise driver.error
    return status, driver


def ref(snapshot: str, name: str) -> int:
    start = snapshot.index(">>>\n") + 4
    body = json.loads(snapshot[start:snapshot.index("\n<<<END_UNTRUSTED_PAGE_DATA")])
    return next(e["ref"] for e in body["elements"]
                if e.get("name") == name or (name == "submit" and e["tag"] == "button"))


async def fill(box: Toolbox, task: dict[str, Any], *, extra: bool = False) -> str:
    packet = json.loads(await box.call("get_packet", {}))
    identity = next(f["value"] for f in packet["fields"] if f["key"] == "sending_identity")
    await box.call("open_url", {"url": task["posting_url"]})
    snap = await box.call("snapshot", {})
    assert await box.call("fill_field", {"ref": ref(snap, "email"), "value": identity, "question": "Email"}) == "ok"
    assert await box.call("fill_field", {"ref": ref(snap, "notice"), "value": "One month",
                                         "question": "Notice period"}) == "ok"
    if extra:
        await box.call("fill_field", {"ref": ref(snap, "salary"), "value": "90000", "question": "Expected salary"})
    out = await box.call("upload_file", {"ref": ref(snap, "cv"), "file_name": "cv.pdf"})
    assert out == "attached cv.pdf", out
    await box.call("save_checkpoint", {"step": "form filled"})
    return snap


async def audit_actions(*subjects: uuid.UUID) -> list[str]:
    async with maker()() as s:
        rows = await s.scalars(select(AuditEvent).where(AuditEvent.subject_id.in_([str(x) for x in subjects]))
                               .order_by(AuditEvent.created_at, AuditEvent.id))
        return [r.action for r in rows]


# ----- tests --------------------------------------------------------------------------------------------------------


async def test_runner_sees_exactly_the_gateway_tools(app):
    _, secret = await make_token("srv", kind="server")
    gw = gateway(app, secret)
    try:
        assert sorted(await gw.list_tools()) == sorted(EXPECTED_TOOLS)
        config = await gw.call("get_runner_config", {})
        assert config["runner_kind"] == "server" and config["model"] and config["evidence_max_bytes"] > 0
    finally:
        await gw.close()


async def test_happy_path_one_submit_with_evidence_and_a_complete_audit(app, form, tmp_path):
    url = f"http://127.0.0.1:{form.server_port}/apply"
    app_id, task_id = await ready_application(url)
    _, secret = await make_token("srv", kind="server")
    _, other = await make_token("srv-2", kind="server")
    seen: dict[str, Any] = {}

    async def script(box: Toolbox, task: dict[str, Any]) -> None:
        assert task["task_id"] == str(task_id) and task["rules"]["stay_on_domain"] == "127.0.0.1"
        snap = await fill(box, task)
        second = gateway(app, other)
        try:  # while this runner holds the task, the second one gets nothing and no permit
            seen["second_claim"] = (await second.call("next_task", {"kinds": ["apply"]}))["task_id"]
            with pytest.raises(GatewayError) as refused:
                await second.call("request_submit_permit", {
                    "task_id": task["task_id"], "summary": "x", "entered_answers": [], "attached_files_sha256": [],
                    "current_url": url})
            seen["second_permit"] = refused.value.code
        finally:
            await second.close()
        out = await box.call("request_submit_permit", {"summary": "all fields filled"})
        assert out.startswith("granted"), out
        assert "Submit clicked" in await box.call("click", {"ref": ref(snap, "submit")})
        assert CONFIRM in await box.call("snapshot", {})
        out = await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM,
                                               "reference": "AE-778"})
        assert out.startswith("Recorded (submitted)"), out

    status, driver = await run_runner(app, secret, tmp_path, script)
    assert status == "worked" and driver.runs == 1
    assert seen == {"second_claim": None, "second_permit": "not_your_task"}
    [post] = form.posts
    assert post["path"] == "/apply/submit" and CV_BYTES in post["body"] and b"One month" in post["body"]

    assert (await load(Application, app_id)).stage.value == "submitted"
    task = await load(AgentTask, task_id)
    assert task.status == AgentTaskStatus.done
    assert len(task.payload["uploads"]) == 2  # the pre-submit checkpoint and the confirmation page
    assert task.checkpoint.data["submit_attempted"] is True
    assert task.released["entered"]["answers"] == [{"question": "Notice period", "value": "One month"}]
    async with maker()() as s:
        [attempt] = (await s.scalars(select(DispatchAttempt).where(DispatchAttempt.application_id == app_id))).all()
    assert attempt.status == DispatchStatus.sent
    assert (attempt.evidence.kind, attempt.evidence.value) == ("reference", "AE-778")
    shot = attempt.evidence.screenshot_ref
    assert shot.startswith(f"evidence:{task_id}/") and shot.rsplit("/", 1)[1] in task.payload["uploads"]
    assert task.payload["uploads"][shot.rsplit("/", 1)[1]]["type"] == "image/png"
    assert task.result["reference"] == "AE-778" and task.result["confirmation_text"] == CONFIRM
    permit = await load(SubmitPermit, attempt.permit_id)
    assert permit.used_at is not None and permit.agent_task_id == task_id
    chain = await audit_actions(task_id, attempt.id, permit.id)
    for step in ("browser.task_queued", "browser.task_claimed", "gateway.packet_released", "gateway.file_downloaded",
                 "permit.granted", "permit.consumed", "browser.cleared", "gateway.permit_granted",
                 "gateway.evidence_uploaded", "gateway.result_reported"):
        assert step in chain, (step, chain)
    assert chain.index("browser.task_claimed") < chain.index("permit.consumed") < chain.index("browser.cleared") \
        < chain.index("gateway.result_reported")


async def test_dry_run_permit_denied_no_click_and_released(app, form, tmp_path):
    url = f"http://127.0.0.1:{form.server_port}/apply"
    app_id, task_id = await ready_application(url)
    _, secret = await make_token("srv", kind="server")

    async def script(box: Toolbox, task: dict[str, Any]) -> None:
        snap = await fill(box, task)
        out = await box.call("request_submit_permit", {"summary": "rehearsal"})
        assert out.startswith("DRY RUN finished"), out
        assert (await box.call("click", {"ref": ref(snap, "submit")})).startswith("STOP")

    status, _ = await run_runner(app, secret, tmp_path, script, dry_run=True)
    assert status == "worked" and form.posts == []
    task = await load(AgentTask, task_id)
    assert task.status == AgentTaskStatus.queued and task.claimed_by_token_id is None
    assert "dry_run" not in task.payload
    assert (await load(Application, app_id)).stage.value == "ready"
    async with maker()() as s:
        assert (await s.scalars(select(DispatchAttempt).where(DispatchAttempt.application_id == app_id))).all() == []
    chain = await audit_actions(task_id)
    assert "gateway.permit_denied" in chain and chain[-1] == "gateway.task_released"


async def test_a_question_the_packet_does_not_hold_waits_for_the_owner_without_a_click(app, form, tmp_path):
    url = f"http://127.0.0.1:{form.server_port}/apply-extra"
    app_id, task_id = await ready_application(url)
    _, secret = await make_token("srv", kind="server")

    async def script(box: Toolbox, task: dict[str, Any]) -> None:
        snap = await fill(box, task, extra=True)
        out = await box.call("request_submit_permit", {"summary": "filled, with one new question"})
        assert '"wait_for_owner"' in out and "Expected salary" in out, out
        assert (await box.call("click", {"ref": ref(snap, "submit")})).startswith("STOP")

    await run_runner(app, secret, tmp_path, script)
    assert form.posts == []
    task = await load(AgentTask, task_id)
    assert task.status == AgentTaskStatus.blocked and task.payload["waiting_for"] == "approval"
    assert (await load(Application, app_id)).stage.value != "submitted"
