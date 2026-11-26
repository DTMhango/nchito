"""Runner configuration: deployment values from the environment (one place, one default each).

Budget caps belong to this runner's own budget line (DESIGN.md 8.3). The gateway contract
(CONTRACTS.md section 8) does not publish them, so they come from env here; the server still
enforces ``automation.agent_max_steps`` and ``budget.agent_task_ceiling_minor`` on its side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


def _num(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if value < 0:
        raise ConfigError(f"{key} must not be negative")
    return value


@dataclass(frozen=True)
class RunnerConfig:
    mcp_url: str
    token: str
    model: str = "claude-sonnet-5-5"  # DESIGN.md 11 routing default for the server browser agent
    profile_dir: Path = Path("/data/profile")  # persistent Chromium profile (volume)
    state_dir: Path = Path("/data/state")  # budget ledger, screenshots
    headless: bool = True
    poll_seconds: float = 30.0
    heartbeat_seconds: float = 20.0
    task_max_cost_usd: float = 1.0
    day_max_cost_usd: float = 10.0
    task_max_tokens: int = 600_000
    day_max_tokens: int = 6_000_000
    permit_safety_seconds: float = 15.0  # treat a permit as expired this early

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RunnerConfig:
        env = dict(os.environ if env is None else env)
        url = env.get("NCHITO_MCP_URL", "").strip()
        token = env.get("NCHITO_RUNNER_TOKEN", "").strip()
        if not url or not token:
            raise ConfigError("NCHITO_MCP_URL and NCHITO_RUNNER_TOKEN are required")
        d = cls.__dataclass_fields__
        return cls(
            mcp_url=url,
            token=token,
            model=env.get("RUNNER_MODEL", "").strip() or d["model"].default,
            profile_dir=Path(env.get("RUNNER_PROFILE_DIR", "") or d["profile_dir"].default),
            state_dir=Path(env.get("RUNNER_STATE_DIR", "") or d["state_dir"].default),
            headless=env.get("RUNNER_HEADLESS", "1").strip().lower() not in {"0", "false", "no"},
            poll_seconds=_num(env, "RUNNER_POLL_SECONDS", d["poll_seconds"].default),
            heartbeat_seconds=_num(env, "RUNNER_HEARTBEAT_SECONDS", d["heartbeat_seconds"].default),
            task_max_cost_usd=_num(env, "RUNNER_TASK_MAX_COST_USD", d["task_max_cost_usd"].default),
            day_max_cost_usd=_num(env, "RUNNER_DAY_MAX_COST_USD", d["day_max_cost_usd"].default),
            task_max_tokens=int(_num(env, "RUNNER_TASK_MAX_TOKENS", d["task_max_tokens"].default)),
            day_max_tokens=int(_num(env, "RUNNER_DAY_MAX_TOKENS", d["day_max_tokens"].default)),
        )
