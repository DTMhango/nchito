"""End-to-end flows: real Chromium, real MCP transport to a fake gateway, scripted model.

Skipped as a group (with a reason) when Playwright's Chromium is not installed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nchito_runner.budget import Budget
from nchito_runner.driver import build_task_prompt
from nchito_runner.gateway import GatewayError, McpGateway
from nchito_runner.toolbox import Toolbox
from nchito_runner.worker import Runner
from tests.fake_gateway import TOKEN
from tests.helpers import ScriptedDriver, make_budget, make_cfg, packet, ref

pytestmark = pytest.mark.browser

CONFIRM = "Thank you, your application has been received."


async def run_task(fake, gw_url, tmp_path, web, script, *, posting="/greenhouse", gateway=None,
                   cfg_kw=None, task_id="t1", checkpoint=None, budget=None, runner_cb=None, packet_=None):
    if posting is not None:
        fake.add_task(task_id, web.base + posting, "127.0.0.1", packet_ or packet(web.base), checkpoint=checkpoint)
    cfg = make_cfg(tmp_path, gw_url, TOKEN, **(cfg_kw or {}))
    driver = ScriptedDriver(script)
    gw = gateway or McpGateway(gw_url, TOKEN)
    runner = Runner(cfg, gw, driver, budget or make_budget(cfg))
    if runner_cb:
        runner_cb(runner)
    try:
        status = await runner.run_one()
    finally:
        await gw.close()
    if isinstance(driver.error, AssertionError):  # an assertion inside the scripted 'model' is a test failure
        raise driver.error
    return runner, driver, status


async def fill_greenhouse(box: Toolbox, task: dict[str, Any]) -> str:
    await box.call("get_packet", {})
    await box.call("open_url", {"url": task["posting_url"]})
    snap = await box.call("snapshot", {})
    await box.call("fill_field", {"ref": ref(snap, name="first_name"), "value": "Test", "question": "First Name"})
    await box.call("fill_field", {"ref": ref(snap, name="last_name"), "value": "Applicant", "question": "Last Name"})
    await box.call("fill_field", {"ref": ref(snap, name="email"), "value": "test.applicant@example.com", "question": "Email"})
    await box.call("select_option", {"ref": ref(snap, name="source"), "value": "Job board", "question": "How did you hear"})
    out = await box.call("upload_file", {"ref": ref(snap, name="resume"), "file_name": "cv.pdf"})
    assert out.startswith("attached"), out
    await box.call("save_checkpoint", {"step": "form filled"})
    return snap


async def greenhouse_happy(box: Toolbox, task: dict[str, Any]) -> None:
    snap = await fill_greenhouse(box, task)
    out = await box.call("request_submit_permit", {"summary": "Greenhouse form complete"})
    assert out.startswith("granted"), out
    out = await box.call("click", {"ref": ref(snap, type="submit")})
    assert "Submit clicked" in out, out
    after = await box.call("snapshot", {})
    assert CONFIRM in after
    await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM, "reference": "APP-12345"})


# ----- happy paths -----------------------------------------------------------------------------------
async def test_greenhouse_happy_path_submits_once_with_evidence(fake, gw_url, tmp_path, web):
    _, driver, status = await run_task(fake, gw_url, tmp_path, web, greenhouse_happy)
    assert status == "worked"
    assert len(web.submissions) == 1
    [res] = fake.results
    assert res["outcome"] == "submitted" and res["permit_id"] == "pmt_1"
    assert res["confirmation_text"] == CONFIRM and res["reference"] == "APP-12345"
    assert res["screenshot_ref"].startswith("runner-local:") and "sha256=" in res["screenshot_ref"]
    assert list((tmp_path / "state" / "evidence").glob("t1-*.png"))
    [permit_req] = fake.called("request_submit_permit")
    qs = {a["question"]: a["value"] for a in permit_req["entered_answers"]}
    assert qs["First Name"] == "Test" and qs["Email"] == "test.applicant@example.com"
    assert len(permit_req["attached_files_sha256"]) == 1
    assert permit_req["current_url"].startswith(web.base)
    assert not fake.suspended and not fake.blockers
    assert fake.called("save_checkpoint"), "checkpoints are saved along the way"
    assert driver.runs == 1


async def test_lever_like_form(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        await box.call("fill_field", {"ref": ref(snap, name="name"), "value": "Test Applicant", "question": "Full name"})
        await box.call("fill_field", {"ref": ref(snap, name="email"), "value": "test.applicant@example.com", "question": "Email"})
        await box.call("fill_field", {"ref": ref(snap, name="comments"), "value": "Happy to chat.", "question": "Cover note"})
        assert (await box.call("request_submit_permit", {"summary": "lever"})).startswith("granted")
        await box.call("click", {"ref": ref(snap, text="Submit application")})
        await box.call("snapshot", {})
        await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM})

    await run_task(fake, gw_url, tmp_path, web, script, posting="/lever")
    assert len(web.submissions) == 1 and fake.results[0]["outcome"] == "submitted"


async def test_multistep_form_next_needs_no_permit_submit_does(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        s1 = await box.call("snapshot", {})
        await box.call("fill_field", {"ref": ref(s1, name="fn"), "value": "Test Applicant", "question": "Full name"})
        await box.call("fill_field", {"ref": ref(s1, name="em"), "value": "test.applicant@example.com", "question": "Email"})
        assert await box.call("click", {"ref": ref(s1, text="Next")}) == "clicked"
        s2 = await box.call("snapshot", {})
        assert "Step 2 of 2" in s2
        out = await box.call("find_answer", {"question": "Are you legally authorised to work in Zambia?"})
        assert "ask_owner" in out or "value" in out
        await box.call("select_option", {"ref": ref(s2, name="auth"), "value": "Yes",
                                         "question": "Authorised to work in Zambia?"})
        early = await box.call("click", {"ref": ref(s2, text="Submit application")})
        assert early.startswith("REFUSED [submit_without_permit]"), early
        assert web.submissions == []
        assert (await box.call("request_submit_permit", {"summary": "two steps"})).startswith("granted")
        await box.call("click", {"ref": ref(s2, text="Submit application")})
        await box.call("snapshot", {})
        await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM})

    fake.answers["are you legally authorised to work in zambia?"] = {"outcome": "value", "value": "Yes"}
    await run_task(fake, gw_url, tmp_path, web, script, posting="/multistep")
    assert len(web.submissions) == 1 and fake.results[0]["outcome"] == "submitted"


# ----- the rails hold --------------------------------------------------------------------------------
async def test_no_submit_without_permit_and_no_enter_key(fake, gw_url, tmp_path, web):
    async def script(box, task):
        snap = await fill_greenhouse(box, task)
        out = await box.call("click", {"ref": ref(snap, type="submit")})
        assert out.startswith("REFUSED [submit_without_permit]"), out
        await box.call("click", {"ref": ref(snap, name="email")})
        enter = await box.call("press_key", {"key": "Enter"})
        assert enter.startswith("REFUSED [enter_submits]"), enter
        await box.call("request_submit_permit", {"summary": "x"})  # owner decides
        again = await box.call("click", {"ref": ref(snap, type="submit")})
        assert again.startswith("REFUSED [submit_without_permit]"), again
        await box.call("raise_blocker", {"type": "declaration", "detail": "owner must review"})

    fake.permit_decision = "wait_for_owner"
    await run_task(fake, gw_url, tmp_path, web, script)
    assert web.submissions == []
    assert [b["type"] for b in fake.blockers] == ["declaration"]
    assert fake.results == []


async def test_expired_permit_is_refused(fake, gw_url, tmp_path, web):
    async def script(box, task):
        snap = await fill_greenhouse(box, task)
        out = await box.call("request_submit_permit", {"summary": "x"})
        assert out.startswith("granted")
        out = await box.call("click", {"ref": ref(snap, type="submit")})
        assert out.startswith("REFUSED [submit_without_permit]") and "expired" in out, out
        await box.call("report_result", {"outcome": "failed", "detail": "permit expired"})

    fake.permit_ttl_seconds = 5  # inside the runner's safety margin: effectively already expired
    await run_task(fake, gw_url, tmp_path, web, script)
    assert web.submissions == [] and fake.results[0]["outcome"] == "failed"


async def test_permit_is_single_use(fake, gw_url, tmp_path, web):
    async def script(box, task):
        snap = await fill_greenhouse(box, task)
        await box.call("request_submit_permit", {"summary": "x"})
        await box.call("click", {"ref": ref(snap, type="submit")})
        s2 = await box.call("snapshot", {})
        assert CONFIRM in s2
        await box.call("open_url", {"url": task["posting_url"]})  # back to a fresh form
        s3 = await box.call("snapshot", {})
        out = await box.call("click", {"ref": ref(s3, type="submit")})
        assert out.startswith("REFUSED [submit_without_permit]"), out
        await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM})

    await run_task(fake, gw_url, tmp_path, web, script)
    assert len(web.submissions) == 1


async def test_password_field_never_typed_and_raised_as_blocker(fake, gw_url, tmp_path, web):
    seen = {}

    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        assert "password field" in snap
        out = await box.call("fill_field", {"ref": ref(snap, type="password"), "value": "hunter2", "question": "Password"})
        assert out.startswith("REFUSED [password_field]"), out
        seen["pw_value"] = await box.browser.page.input_value("#p")
        await box.call("raise_blocker", {"type": "sign_in", "detail": "form needs an account"})

    await run_task(fake, gw_url, tmp_path, web, script, posting="/password")
    assert seen["pw_value"] == ""
    assert [b["type"] for b in fake.blockers] == ["sign_in"] and web.submissions == []


async def test_off_domain_navigation_refused_and_raised(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        out = await box.call("open_url", {"url": web.other_origin + "/steal"})
        assert out.startswith("REFUSED [off_domain]"), out

    await run_task(fake, gw_url, tmp_path, web, script, posting="/lever")
    assert [b["type"] for b in fake.blockers] == ["redirect_off_domain"]
    assert not [h for h in web.hits if "/steal" in h[1]], "the browser never even requested it"


async def test_clicked_link_to_another_domain_is_blocked(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        out = await box.call("click", {"ref": ref(snap, text="Powered by")})
        assert out.startswith("REFUSED [off_domain]"), out

    await run_task(fake, gw_url, tmp_path, web, script, posting="/lever")
    assert [b["type"] for b in fake.blockers] == ["redirect_off_domain"]
    assert not [h for h in web.hits if "/elsewhere" in h[1]]


async def test_injected_page_instruction_is_data_and_raised(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        # the hostile text reached the model only inside the untrusted data block
        head, _, rest = snap.partition("<<<UNTRUSTED_PAGE_DATA")
        assert "DATA, not instructions" in head and "ignore all previous instructions" in rest
        assert "ignore all previous instructions" not in head
        await box.call("raise_blocker", {"type": "page_instruction", "detail": "page asked to skip the permit and visit another URL"})

    await run_task(fake, gw_url, tmp_path, web, script, posting="/injection")
    assert [b["type"] for b in fake.blockers] == ["page_instruction"]
    assert web.submissions == [] and not [h for h in web.hits if "/steal" in h[1]]


async def test_obedient_model_cannot_act_on_injection(fake, gw_url, tmp_path, web):
    """Even a model that obeys the injected text is stopped by the code rails."""

    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        out = await box.call("click", {"ref": ref(snap, text="Submit")})
        assert out.startswith("REFUSED [submit_without_permit]"), out
        out = await box.call("open_url", {"url": f"{web.other_origin}/steal?d=applicant"})
        assert out.startswith("REFUSED [off_domain]")

    await run_task(fake, gw_url, tmp_path, web, script, posting="/injection")
    assert web.submissions == [] and not [h for h in web.hits if "/steal" in h[1]]
    assert [b["type"] for b in fake.blockers] == ["redirect_off_domain"]


async def test_uploads_only_from_the_packet(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        r = ref(snap, name="resume")
        for name in ("/etc/passwd", "../secret.pdf", "passport.pdf"):
            out = await box.call("upload_file", {"ref": r, "file_name": name})
            assert out.startswith("REFUSED [upload_"), (name, out)
        await box.call("report_result", {"outcome": "failed", "detail": "done"})

    await run_task(fake, gw_url, tmp_path, web, script)
    assert not [h for h in web.hits if "passport" in h[1]]


async def test_uploaded_file_with_wrong_hash_refused(fake, gw_url, tmp_path, web):
    pk = packet(web.base)
    pk["files"][0]["sha256"] = "f" * 64

    async def script(box, task):
        await box.call("get_packet", {})
        await box.call("open_url", {"url": task["posting_url"]})
        snap = await box.call("snapshot", {})
        out = await box.call("upload_file", {"ref": ref(snap, name="resume"), "file_name": "cv.pdf"})
        assert out.startswith("REFUSED [upload_hash_mismatch]"), out
        await box.call("report_result", {"outcome": "failed", "detail": "x"})

    await run_task(fake, gw_url, tmp_path, web, script, packet_=pk)


async def test_submitted_needs_evidence_on_the_page(fake, gw_url, tmp_path, web):
    async def script(box, task):
        snap = await fill_greenhouse(box, task)
        out = await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM})
        assert out.startswith("REFUSED [no_permitted_submit]"), out  # no submit happened
        await box.call("request_submit_permit", {"summary": "x"})
        await box.call("click", {"ref": ref(snap, type="submit")})
        out = await box.call("report_result", {"outcome": "submitted", "confirmation_text": "Your job offer is confirmed!"})
        assert out.startswith("REFUSED [evidence_not_on_page]"), out
        await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM})

    await run_task(fake, gw_url, tmp_path, web, script)
    assert len(fake.results) == 1 and fake.results[0]["outcome"] == "submitted" and not fake.suspended


# ----- crash, restart, shutdown --------------------------------------------------------------------
class CutGateway(McpGateway):
    """Simulates the process dying: after a trigger call every gateway call fails."""

    def __init__(self, *a, cut_after: str, state: dict | None = None):
        super().__init__(*a)
        self.cut_after = cut_after
        self.cut = False

    async def call(self, tool, args):
        if self.cut:
            raise GatewayError("process killed")
        out = await super().call(tool, args)
        if tool == "save_checkpoint" and self.cut_after == (args["state"].get("step") or ""):
            self.cut = True
        return out

    async def ping(self):
        if self.cut:
            raise GatewayError("process killed")
        await super().ping()


async def test_crash_after_submit_click_restarts_without_second_submit(fake, gw_url, tmp_path, web):
    async def dies_after_click(box, task):
        snap = await fill_greenhouse(box, task)
        await box.call("request_submit_permit", {"summary": "x"})
        await box.call("click", {"ref": ref(snap, type="submit")})  # POST goes out; gateway then goes dark
        await box.call("snapshot", {})
        await box.call("report_result", {"outcome": "submitted", "confirmation_text": CONFIRM})  # never lands

    cut = CutGateway(gw_url, TOKEN, cut_after="submitting")
    await run_task(fake, gw_url, tmp_path / "run1", web, dies_after_click, gateway=cut)
    assert len(web.submissions) == 1
    assert fake.results == [], "the dying process could not report anything"
    assert fake.checkpoints["t1"]["data"]["submit_attempted"] is True

    fake.requeue("t1")  # the server returns the stale claim with its last checkpoint
    permits_before = len(fake.called("request_submit_permit"))
    resubmits = ScriptedDriver(greenhouse_happy)  # would submit again if it were ever allowed to run

    cfg = make_cfg(tmp_path / "run2", gw_url, TOKEN)
    runner = Runner(cfg, McpGateway(gw_url, TOKEN), resubmits, make_budget(cfg))
    await runner.run_one()
    await runner.gw.close()

    assert resubmits.runs == 0, "the model is not even started for a task that was already submitted once"
    assert len(web.submissions) == 1
    assert len(fake.called("request_submit_permit")) == permits_before
    [res] = fake.results
    assert res["outcome"] == "uncertain" and not fake.suspended


async def test_crash_before_submit_resumes_from_checkpoint_and_submits_once(fake, gw_url, tmp_path, web):
    async def dies_midway(box, task):
        await fill_greenhouse(box, task)  # ends with save_checkpoint('form filled'); gateway then goes dark
        await box.call("request_submit_permit", {"summary": "x"})
        raise RuntimeError("never reached: the process is gone")

    cut = CutGateway(gw_url, TOKEN, cut_after="form filled")
    await run_task(fake, gw_url, tmp_path / "run1", web, dies_midway, gateway=cut)
    assert web.submissions == [] and fake.results == []
    assert fake.checkpoints["t1"]["step"] == "form filled"
    assert fake.checkpoints["t1"]["data"]["entered"]["Email"] == "test.applicant@example.com"

    fake.requeue("t1")
    got = {}

    async def resumes(box, task):
        got["prompt"] = build_task_prompt(task)
        assert task["checkpoint"]["step"] == "form filled"
        await greenhouse_happy(box, task)

    await run_task(fake, gw_url, tmp_path / "run2", web, resumes, posting=None)
    assert "RESUMING" in got["prompt"] and "form filled" in got["prompt"]
    assert len(web.submissions) == 1
    assert fake.results[-1]["outcome"] == "submitted"


async def test_agent_error_after_submit_click_reports_uncertain_not_failed(fake, gw_url, tmp_path, web):
    async def script(box, task):
        snap = await fill_greenhouse(box, task)
        await box.call("request_submit_permit", {"summary": "x"})
        await box.call("click", {"ref": ref(snap, type="submit")})
        raise RuntimeError("model API fell over")

    await run_task(fake, gw_url, tmp_path, web, script)
    assert len(web.submissions) == 1
    assert [r["outcome"] for r in fake.results] == ["uncertain"]


async def test_agent_error_before_submit_reports_failed(fake, gw_url, tmp_path, web):
    async def script(box, task):
        raise RuntimeError("model API fell over")

    await run_task(fake, gw_url, tmp_path, web, script)
    assert [r["outcome"] for r in fake.results] == ["failed"] and web.submissions == []


async def test_graceful_shutdown_checkpoints_and_does_not_fail_the_task(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await fill_greenhouse(box, task)
        runner_ref["r"].stop.set()  # SIGTERM arrives mid-task
        await asyncio.sleep(30)

    runner_ref: dict[str, Runner] = {}
    await run_task(fake, gw_url, tmp_path, web, script, runner_cb=lambda r: runner_ref.update(r=r))
    assert fake.results == [] and web.submissions == []
    assert fake.checkpoints["t1"]["step"] == "paused"
    assert fake.checkpoints["t1"]["data"]["paused_reason"] == "runner shutting down"
    fake.requeue("t1")  # resumable


async def test_heartbeat_pings_during_a_long_task(fake, gw_url, tmp_path, web):
    pings = {"n": 0}

    class Spy(McpGateway):
        async def ping(self):
            pings["n"] += 1
            await super().ping()

    async def script(box, task):
        await asyncio.sleep(0.4)
        await box.call("report_result", {"outcome": "failed", "detail": "nothing to do"})

    await run_task(fake, gw_url, tmp_path, web, script, gateway=Spy(gw_url, TOKEN))
    assert pings["n"] >= 2


async def test_step_limit(fake, gw_url, tmp_path, web):
    async def script(box, task):
        outs = [await box.call("snapshot", {}) for _ in range(5)]
        assert outs[-1].startswith("STOP: the step limit"), outs[-1]
        await box.call("report_result", {"outcome": "failed", "detail": "step limit"})

    fake.add_task("t1", web.base + "/lever", "127.0.0.1", packet(web.base), max_steps=3)
    await run_task(fake, gw_url, tmp_path, web, script, posting=None)
    assert fake.results[0]["outcome"] == "failed"


# ----- budget -----------------------------------------------------------------------------------------
async def test_task_budget_exhausted_stops_cleanly_and_reports(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        box.budget.add(100, 5.0)  # the model spent more than the task cap
        out = await box.call("open_url", {"url": task["posting_url"]})
        assert out.startswith("STOP: task budget exhausted"), out

    await run_task(fake, gw_url, tmp_path, web, script, cfg_kw={"task_max_cost_usd": 1.0})
    [res] = fake.results
    assert res["outcome"] == "failed" and "budget" in res["detail"].lower()
    assert web.hits == []


async def test_day_budget_exhausted_pauses_task_with_checkpoint(fake, gw_url, tmp_path, web):
    async def script(box, task):
        await box.call("get_packet", {})
        box.budget.add(100, 50.0)
        out = await box.call("snapshot", {})
        assert out.startswith("STOP: day budget exhausted"), out

    await run_task(fake, gw_url, tmp_path, web, script, cfg_kw={"day_max_cost_usd": 10.0})
    assert fake.results == [], "a day cap is not the task's failure"
    assert fake.checkpoints["t1"]["step"] == "paused"


async def test_no_task_is_claimed_when_the_day_budget_is_spent(fake, gw_url, tmp_path, web):
    cfg = make_cfg(tmp_path, gw_url, TOKEN, day_max_cost_usd=1.0)
    budget = make_budget(cfg)
    budget.add(10, 2.0)
    fake.add_task("t1", web.base + "/lever", "127.0.0.1", packet(web.base))
    driver = ScriptedDriver(greenhouse_happy)
    runner = Runner(cfg, McpGateway(gw_url, TOKEN), driver, budget)
    try:
        assert await runner.run_one() == "day_budget"
    finally:
        await runner.gw.close()
    assert fake.called("next_task") == [] and driver.runs == 0


async def test_empty_queue_is_idle(fake, gw_url, tmp_path, web):
    cfg = make_cfg(tmp_path, gw_url, TOKEN)
    runner = Runner(cfg, McpGateway(gw_url, TOKEN), ScriptedDriver(greenhouse_happy), Budget(tmp_path / "b.json", make_budget(cfg).caps))
    try:
        assert await runner.run_one() == "idle"
    finally:
        await runner.gw.close()
