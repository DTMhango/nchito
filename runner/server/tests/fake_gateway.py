"""A fake Nchito gateway: an MCP streamable-HTTP server implementing CONTRACTS.md section 8.

State lives in ``FakeNchito`` so tests can queue tasks, choose the permit decision, read every
call the runner made, and see what the server would have detected (a submit without a permit
suspends the token, as the contract says).
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer

TOKEN = "nch_test_token"


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
        self.blockers: list[dict[str, Any]] = []
        self.permits: dict[str, dict[str, Any]] = {}
        self.permit_decision = "granted"
        self.permit_ttl_seconds = 600
        self.suspended = False
        self.pings = 0
        self.answers: dict[str, dict[str, Any]] = {}
        self.steps_left = 80

    def add_task(self, task_id: str, posting_url: str, domain: str, packet: dict[str, Any],
                 *, max_steps: int = 80, checkpoint: dict[str, Any] | None = None) -> None:
        self.queue.append({
            "task_id": task_id, "type": "apply", "instructions": "Apply to this role.", "posting_url": posting_url,
            "checkpoint": checkpoint, "rules": {"stay_on_domain": domain, "max_steps": max_steps,
                                                "never": ["type passwords or create accounts"]}})
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


def build_server(fake: FakeNchito) -> MCPServer:
    srv = MCPServer("fake-nchito")

    def rec(tool: str, args: dict[str, Any]) -> None:
        fake.calls.append((tool, args))

    @srv.tool()
    def next_task(kinds: list[str] | None = None) -> dict[str, Any]:
        rec("next_task", {"kinds": kinds})
        if fake.suspended or not fake.queue:
            return {"task_id": None}
        task = fake.queue.pop(0)
        fake.claimed[task["task_id"]] = dict(task)
        return task

    @srv.tool()
    def get_packet(task_id: str) -> dict[str, Any]:
        rec("get_packet", {"task_id": task_id})
        return fake.packets[task_id]

    @srv.tool()
    def find_answer(task_id: str, question: str, options: list[str] | None = None) -> dict[str, Any]:
        rec("find_answer", {"task_id": task_id, "question": question})
        return fake.answers.get(question.lower(), {"outcome": "ask_owner"})

    @srv.tool()
    def save_checkpoint(task_id: str, state: dict[str, Any]) -> dict[str, Any]:
        rec("save_checkpoint", {"task_id": task_id, "state": state})
        fake.checkpoints[task_id] = state
        fake.steps_left -= 1
        return {"ok": True, "steps_used": 80 - fake.steps_left, "steps_left": fake.steps_left}

    @srv.tool()
    def raise_blocker(task_id: str, type: str, detail: str, url: str | None = None) -> dict[str, Any]:
        rec("raise_blocker", {"task_id": task_id, "type": type, "detail": detail, "url": url})
        fake.blockers.append({"task_id": task_id, "type": type, "detail": detail, "url": url})
        fake.claimed.pop(task_id, None)
        return {"pending_action_id": f"pa_{len(fake.blockers)}", "next": "move_on"}

    @srv.tool()
    def request_submit_permit(task_id: str, summary: str, entered_answers: list[dict[str, Any]],
                              attached_files_sha256: list[str], current_url: str) -> dict[str, Any]:
        rec("request_submit_permit", {"task_id": task_id, "summary": summary, "entered_answers": entered_answers,
                                      "attached_files_sha256": attached_files_sha256, "current_url": current_url})
        if fake.permit_decision != "granted":
            return {"decision": fake.permit_decision, "reason": "owner must look first", "changes": ["new question"]}
        pid = f"pmt_{len(fake.permits) + 1}"
        exp = (datetime.now(UTC) + timedelta(seconds=fake.permit_ttl_seconds)).isoformat()
        fake.permits[pid] = {"task_id": task_id, "used": False}
        return {"decision": "granted", "permit_id": pid, "expires_at": exp, "changes": []}

    @srv.tool()
    def report_result(task_id: str, outcome: str, permit_id: str | None = None, confirmation_text: str | None = None,
                      reference: str | None = None, screenshot_ref: str | None = None,
                      detail: str | None = None) -> dict[str, Any]:
        args = {"task_id": task_id, "outcome": outcome, "permit_id": permit_id, "confirmation_text": confirmation_text,
                "reference": reference, "screenshot_ref": screenshot_ref, "detail": detail}
        rec("report_result", args)
        fake.results.append(args)
        if outcome == "submitted" and not (permit_id in fake.permits and fake.permits[permit_id]["task_id"] == task_id):
            fake.suspended = True
        fake.claimed.pop(task_id, None)
        return {"recorded": True, "application_stage": "applied" if outcome == "submitted" else outcome}

    return srv


class _BearerGate:
    """ASGI wrapper: 401 unless ``Authorization: Bearer <TOKEN>``; counts MCP pings as last-seen."""

    def __init__(self, app: Any, fake: FakeNchito):
        self.app, self.fake = app, fake

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
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
        app = _BearerGate(build_server(fake).streamable_http_app(), fake)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

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
