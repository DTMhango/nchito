"""Test helpers: a scripted 'model', snapshot parsing, config and packet builders."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from nchito_runner.budget import Budget, Caps
from nchito_runner.config import RunnerConfig
from nchito_runner.toolbox import Toolbox
from tests.webfixtures import CV_BYTES

Script = Callable[[Toolbox, dict[str, Any]], Awaitable[None]]


class ScriptedDriver:
    """Stands in for the model: runs a fixed tool-call script. No API calls are made."""

    def __init__(self, script: Script):
        self.script = script
        self.runs = 0
        self.trace: list[tuple[str, dict[str, Any], str]] = []
        self.error: BaseException | None = None

    async def run(self, box: Toolbox, task: dict[str, Any], budget: Budget) -> None:
        self.runs += 1
        original = box.call

        async def traced(name: str, args: dict[str, Any]) -> str:
            out = await original(name, args)
            self.trace.append((name, args, out))
            return out

        box.call = traced  # type: ignore[method-assign]
        try:
            await self.script(box, task)
        except BaseException as exc:
            self.error = exc
            raise

    def outputs(self, tool: str) -> list[str]:
        return [o for n, _, o in self.trace if n == tool]


def elements(snapshot: str) -> list[dict[str, Any]]:
    m = re.search(r"<<<UNTRUSTED_PAGE_DATA \w+ source=[^>]*>>>\n(.*)\n<<<END_UNTRUSTED_PAGE_DATA", snapshot, re.S)
    assert m, f"snapshot is not wrapped as untrusted data: {snapshot[:200]}"
    return json.loads(m.group(1))["elements"]


def ref(snapshot: str, *, name: str | None = None, type: str | None = None, text: str | None = None,
        label: str | None = None) -> int:
    for e in elements(snapshot):
        if name is not None and e.get("name") != name:
            continue
        if type is not None and e.get("type") != type:
            continue
        if text is not None and text.lower() not in e.get("text", "").lower():
            continue
        if label is not None and label.lower() not in e.get("label", "").lower():
            continue
        return e["ref"]
    raise AssertionError(f"no element name={name} type={type} text={text} label={label} in {elements(snapshot)}")


def make_cfg(tmp: Path, url: str, token: str, **kw: Any) -> RunnerConfig:
    base = dict(mcp_url=url, token=token, profile_dir=tmp / "profile", state_dir=tmp / "state", headless=True,
                poll_seconds=0.05, heartbeat_seconds=0.05)
    base.update(kw)
    return RunnerConfig(**base)


def make_budget(cfg: RunnerConfig) -> Budget:
    return Budget(cfg.state_dir / "budget.json",
                  Caps(cfg.task_max_cost_usd, cfg.day_max_cost_usd, cfg.task_max_tokens, cfg.day_max_tokens))


def packet(web_base: str, *, with_file: bool = True) -> dict[str, Any]:
    files = []
    if with_file:
        files.append({"name": "cv.pdf", "kind": "cv", "sha256": hashlib.sha256(CV_BYTES).hexdigest(),
                      "download_url": f"{web_base}/files/cv.pdf", "attach_rule": "always"})
        files.append({"name": "passport.pdf", "kind": "vault", "sha256": "0" * 64,
                      "download_url": f"{web_base}/files/passport.pdf", "attach_rule": "never"})
    return {"packet_version": 1, "packet_hash": "h" * 64, "destination_domain": "127.0.0.1",
            "fields": [{"key": "first_name", "label": "First name", "value": "Test"},
                       {"key": "last_name", "label": "Last name", "value": "Applicant"},
                       {"key": "email", "label": "Email", "value": "test.applicant@example.com"}],
            "answers": [], "files": files}
