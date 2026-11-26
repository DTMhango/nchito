"""A fake Nchito gateway: an MCP streamable-HTTP server (official ``mcp`` SDK 1.x, stateless, JSON responses, bearer
auth) with the real gateway's tool list (``EXPECTED_TOOLS``) and its signed file and evidence routes.

State lives in ``FakeNchito`` so tests can queue tasks, choose the permit decision and the runner config, read every
call the runner made, and see what the server would have detected (a submit without a permit suspends the token,
as the contract says). A refused call is a tool error whose text is ``{"code", "reason"}``, like the real one.
Packet files are named by public links on another host (``PUBLIC``); the runner must fetch them from this server.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN = "nch_test_token"
PUBLIC = "https://nchito.example.com"  # the server's public base URL (not how the runner reaches it)


def files_url(name: str) -> str:
    return f"{PUBLIC}/api/gateway/files/{name}"


class FakeNchito:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.queue: list[dict[str, Any]] = []
        self.claimed: dict[str, dict[str, Any]] = {}
        self.packets: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.blockers: list[dict[str, Any]] = []
        self.released: list[dict[str, Any]] = []
        self.permits: dict[str, dict[str, Any]] = {}
        self.permit_decision = "granted"
        self.permit_ttl_seconds = 600
        self.suspended = False
        self.answers: dict[str, dict[str, Any]] = {}
        self.steps_left = 80
        self.files: dict[str, bytes] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.upload_links: dict[str, dict[str, Any]] = {}
        self.downloads: list[str] = []
        self.config: dict[str, Any] = {
            "runner_kind": "server", "enabled": True, "model": "test-model", "currency": "USD",
            "task_cap_minor": 100, "day_cap_minor": 1000, "task_max_tokens": 600_000, "day_max_tokens": 6_000_000,
            "max_steps": 80, "lease_minutes": 20, "evidence_max_bytes": 2048 * 1024}

    def add_task(self, task_id: str, posting_url: str, domain: str, packet: dict[str, Any] | None,
                 *, max_steps: int = 80, checkpoint: dict[str, Any] | None = None, type: str = "apply") -> None:
        self.queue.append({
            "task_id": task_id, "type": type, "instructions": "Work this task.", "posting_url": posting_url,
            "checkpoint": checkpoint, "rules": {"stay_on_domain": domain, "max_steps": max_steps,
                                                "never": ["type passwords or create accounts"]}})
        if packet is not None:
            self.packets[task_id] = packet
        if checkpoint:
            self.checkpoints[task_id] = checkpoint

    def requeue(self, task_id: str) -> None:
        """Simulate the server returning a stale claim to the queue with its last checkpoint."""
        task = self.claimed.pop(task_id)
        task["checkpoint"] = self.checkpoints.get(task_id)
        self.queue.insert(0, task)

    def called(self, tool: str) -> list[dict[str, Any]]:
        return [a for t, a in self.calls if t == tool]

    def own(self, task_id: str) -> dict[str, Any]:
        task = self.claimed.get(task_id)
        if task is None:
            raise ToolError(json.dumps({"code": "not_your_task", "reason": "this runner does not hold the task"}))
        return task


def build_server(fake: FakeNchito) -> FastMCP:
    srv = FastMCP("fake-nchito", stateless_http=True, json_response=True)

    def rec(tool: str, args: dict[str, Any]) -> None:
        fake.calls.append((tool, args))

    def give_back(task_id: str, reason: str) -> None:
        task = fake.claimed.pop(task_id)
        task["checkpoint"] = fake.checkpoints.get(task_id)
        fake.released.append({"task_id": task_id, "reason": reason})
        fake.queue.append(task)

    @srv.tool()
    def next_task(kinds: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
        rec("next_task", {"kinds": kinds, "dry_run": dry_run})
        wanted = [t for t in fake.queue if kinds is None or t["type"] in kinds]
        if fake.suspended or not wanted:
            return {"task_id": None}
        task = wanted[0]
        fake.queue.remove(task)
        fake.claimed[task["task_id"]] = {**task, "dry_run": dry_run}
        return task

    @srv.tool()
    def get_packet(task_id: str) -> dict[str, Any]:
        rec("get_packet", {"task_id": task_id})
        fake.own(task_id)
        return fake.packets[task_id]

    @srv.tool()
    def find_answer(task_id: str, question: str, options: list[str] | None = None) -> dict[str, Any]:
        rec("find_answer", {"task_id": task_id, "question": question})
        return fake.answers.get(question.lower(), {"outcome": "ask_owner"})

    @srv.tool()
    def save_checkpoint(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
        rec("save_checkpoint", {"task_id": task_id, "state": state})
        fake.own(task_id)
        fake.checkpoints[task_id] = state
        fake.steps_left -= 1
        return {"ok": True, "steps_used": 80 - fake.steps_left, "steps_left": fake.steps_left}

    @srv.tool()
    def raise_blocker(task_id: str, type: str, detail: str, url: str | None = None) -> dict[str, Any]:
        rec("raise_blocker", {"task_id": task_id, "type": type, "detail": detail, "url": url})
        fake.own(task_id)
        fake.blockers.append({"task_id": task_id, "type": type, "detail": detail, "url": url})
        fake.claimed.pop(task_id, None)
        return {"pending_action_id": f"pa_{len(fake.blockers)}", "next": "move_on"}

    @srv.tool()
    def request_submit_permit(task_id: str, summary: str, entered_answers: list[dict[str, Any]],
                              attached_files_sha256: list[str], current_url: str) -> dict[str, Any]:
        rec("request_submit_permit", {"task_id": task_id, "summary": summary, "entered_answers": entered_answers,
                                      "attached_files_sha256": attached_files_sha256, "current_url": current_url})
        task = fake.own(task_id)
        if task.get("dry_run"):
            return {"decision": "denied", "reason": "dry run: no permit is ever granted", "changes": []}
        if fake.permit_decision != "granted":
            if fake.permit_decision == "wait_for_owner":
                fake.claimed.pop(task_id, None)  # blocked for the owner
            return {"decision": fake.permit_decision, "reason": "owner must look first", "changes": ["new question"]}
        pid = f"pmt_{len(fake.permits) + 1}"
        exp = (datetime.now(UTC) + timedelta(seconds=fake.permit_ttl_seconds)).isoformat()
        fake.permits[pid] = {"task_id": task_id}
        task["permit_id"] = pid
        return {"decision": "granted", "permit_id": pid, "expires_at": exp, "changes": []}

    @srv.tool()
    def report_result(task_id: str, outcome: str, permit_id: str | None = None, confirmation_text: str | None = None,
                      reference: str | None = None, screenshot_ref: str | None = None,
                      detail: str | None = None) -> dict[str, Any]:
        args = {"task_id": task_id, "outcome": outcome, "permit_id": permit_id, "confirmation_text": confirmation_text,
                "reference": reference, "screenshot_ref": screenshot_ref, "detail": detail}
        rec("report_result", args)
        task = fake.claimed.get(task_id, {})
        if outcome == "submitted" and not task.get("permit_id"):
            fake.suspended = True  # a submission with no cleared permit for this task
        if permit_id is not None and permit_id != task.get("permit_id"):
            fake.suspended = True
        fake.results.append(args)
        if task.get("dry_run") and outcome != "submitted":
            give_back(task_id, f"dry run finished: {outcome}")
            return {"recorded": False, "application_stage": "ready"}
        fake.claimed.pop(task_id, None)
        return {"recorded": True, "application_stage": "submitted" if outcome == "submitted" else outcome}

    @srv.tool()
    def report_jobs(task_id: str, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        rec("report_jobs", {"task_id": task_id, "jobs": jobs})
        return {"accepted": len(jobs), "duplicates": 0}

    @srv.tool()
    def report_check(task_id: str, status: str, evidence: str | None = None,
                     screenshot_ref: str | None = None) -> dict[str, Any]:
        args = {"task_id": task_id, "status": status, "evidence": evidence, "screenshot_ref": screenshot_ref}
        rec("report_check", args)
        fake.own(task_id)
        recorded = "unknown" if status == "closed" and not evidence else status
        fake.checks.append({**args, "recorded": recorded})
        fake.claimed.pop(task_id, None)
        return {"recorded": True, "availability": recorded}

    @srv.tool()
    def release_task(task_id: str, reason: str) -> dict[str, Any]:
        rec("release_task", {"task_id": task_id, "reason": reason})
        task = fake.own(task_id)
        if task.get("permit_id") and not task.get("dry_run"):
            raise ToolError(json.dumps({"code": "permit_given", "reason": "report the result instead"}))
        give_back(task_id, reason)
        return {"released": True, "task_status": "queued"}

    @srv.tool()
    def evidence_upload_url(task_id: str, content_type: str) -> dict[str, Any]:
        rec("evidence_upload_url", {"task_id": task_id, "content_type": content_type})
        fake.own(task_id)
        ref = f"ev_{len(fake.upload_links) + 1}"
        fake.upload_links[ref] = {"task_id": task_id, "content_type": content_type}
        return {"upload_url": f"{PUBLIC}/api/gateway/uploads/{ref}", "ref": f"evidence:{task_id}/{ref}",
                "max_bytes": fake.config["evidence_max_bytes"],
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat()}

    @srv.tool()
    def get_runner_config() -> dict[str, Any]:
        rec("get_runner_config", {})
        return dict(fake.config)

    @srv.custom_route("/api/gateway/files/{signed}", methods=["GET"])
    async def download(request: Request) -> Response:
        signed = request.path_params["signed"]
        fake.downloads.append(signed)
        if signed not in fake.files:
            return JSONResponse({"detail": "invalid link"}, status_code=403)
        return Response(fake.files[signed], media_type="application/octet-stream")

    @srv.custom_route("/api/gateway/uploads/{signed}", methods=["PUT"])
    async def upload(request: Request) -> Response:
        signed = request.path_params["signed"]
        link = fake.upload_links.get(signed)
        if link is None or signed in fake.uploads:
            return JSONResponse({"detail": "invalid or used link"}, status_code=403)
        if request.headers.get("content-type", "").split(";")[0] != link["content_type"]:
            return JSONResponse({"detail": "wrong type"}, status_code=415)
        body = await request.body()
        fake.uploads[signed] = {**link, "bytes": len(body), "head": body[:8]}
        return JSONResponse({"ref": signed}, status_code=201)

    return srv


class _BearerGate:
    """ASGI wrapper: 401 unless ``Authorization: Bearer <TOKEN>`` (MCP and the signed routes alike)."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            headers = dict(scope["headers"])
            if headers.get(b"authorization", b"").decode() != f"Bearer {TOKEN}":
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


class ServerThread:
    def __init__(self, fake: FakeNchito):
        self.fake = fake
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.mcp = build_server(fake)
        app = _BearerGate(self.mcp.streamable_http_app())
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.base}/mcp"

    def start(self) -> None:
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("fake gateway did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
