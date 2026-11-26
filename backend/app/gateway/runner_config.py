"""``get_runner_config``: the owner's settings a runner needs (budget caps, model, limits). The server enforces the
same limits on its side (steps, task ceiling); the runner uses them to stop before it is stopped."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import service as settings_service
from app.gateway.tools import GetRunnerConfigIn, RunnerConfigOut
from app.models.platform import ApiToken


async def get_runner_config(session: AsyncSession, token: ApiToken, body: GetRunnerConfigIn, *,
                            at: datetime) -> RunnerConfigOut:
    v = await settings_service.values(session)
    enabled = token.suspended_at is None and (token.runner_kind != "server" or bool(v["runners.server_runner_enabled"]))
    return RunnerConfigOut(
        runner_kind=token.runner_kind,  # type: ignore[arg-type]
        enabled=enabled, model=str(v["ai.model_browser_agent"]), currency=str(v["budget.currency"]),
        task_cap_minor=int(v["budget.agent_task_ceiling_minor"]), day_cap_minor=int(v["runners.server_day_cap_minor"]),
        task_max_tokens=int(v["runners.server_task_max_tokens"]),
        day_max_tokens=int(v["runners.server_day_max_tokens"]), max_steps=int(v["automation.agent_max_steps"]),
        lease_minutes=int(v["runners.task_lease_minutes"]),
        evidence_max_bytes=int(v["runners.evidence_max_kb"]) * 1024)
