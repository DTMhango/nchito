"""Runner configuration: deployment values from the environment (one place, one default each).

The owner's settings come from the gateway (``get_runner_config``): the model, the per-task and per-day caps,
the step limit, the evidence size limit and whether this runner is switched on. The budget values here are
this deployment's upper bound: the runner uses the lower of the two, so the environment can only tighten what
the owner set, never loosen it.

Environment (the same names in compose, ``runner/local`` and the RUNBOOK):

- ``NCHITO_URL``: the instance, for example ``https://nchito.example.com`` (the gateway is ``<NCHITO_URL>/mcp``).
- ``NCHITO_RUNNER_TOKEN``: the runner token (``nch_...``) from Settings, Runners.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

TASK_KINDS = ("apply", "check_posting")  # the kinds this runner can work (sweeps stay with the PC runner)


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


def _flag(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be 1 or 0, got {raw!r}")


def _url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ConfigError(f"NCHITO_URL must look like https://nchito.example.com, got {raw!r}")
    if parts.path.endswith("/mcp"):
        raise ConfigError("NCHITO_URL is the instance address without /mcp; the runner adds /mcp itself")
    return url


def _kinds(raw: str) -> tuple[str, ...]:
    kinds = tuple(k.strip() for k in raw.split(",") if k.strip())
    unknown = [k for k in kinds if k not in TASK_KINDS]
    if not kinds or unknown:
        raise ConfigError(f"RUNNER_TASK_KINDS must be a comma list of {', '.join(TASK_KINDS)}")
    return kinds


@dataclass(frozen=True)
class RunnerConfig:
    nchito_url: str
    token: str
    profile_dir: Path = Path("/data/profile")  # persistent Chromium profile (volume)
    state_dir: Path = Path("/data/state")  # budget ledger
    headless: bool = True
    poll_seconds: float = 30.0
    heartbeat_seconds: float = 20.0
    # Upper bounds on the owner's caps from get_runner_config (USD: what the Agent SDK reports).
    task_max_cost_usd: float = 1.0
    day_max_cost_usd: float = 10.0
    task_max_tokens: int = 600_000
    day_max_tokens: int = 6_000_000
    permit_safety_seconds: float = 15.0  # treat a permit as expired this early
    dry_run: bool = False  # rehearsal: next_task(dry_run), never a permit, every task released at the end
    task_kinds: tuple[str, ...] = TASK_KINDS

    @property
    def mcp_url(self) -> str:
        return f"{self.nchito_url}/mcp"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RunnerConfig:
        env = dict(os.environ if env is None else env)
        url = env.get("NCHITO_URL", "").strip()
        token = env.get("NCHITO_RUNNER_TOKEN", "").strip()
        if not url or not token:
            raise ConfigError("NCHITO_URL and NCHITO_RUNNER_TOKEN are required")
        if not token.startswith("nch_"):
            raise ConfigError("NCHITO_RUNNER_TOKEN does not look like a runner token (nch_...)")
        d = cls.__dataclass_fields__
        return cls(
            nchito_url=_url(url),
            token=token,
            profile_dir=Path(env.get("RUNNER_PROFILE_DIR", "") or d["profile_dir"].default),
            state_dir=Path(env.get("RUNNER_STATE_DIR", "") or d["state_dir"].default),
            headless=_flag(env, "RUNNER_HEADLESS", d["headless"].default),
            poll_seconds=_num(env, "RUNNER_POLL_SECONDS", d["poll_seconds"].default),
            heartbeat_seconds=_num(env, "RUNNER_HEARTBEAT_SECONDS", d["heartbeat_seconds"].default),
            task_max_cost_usd=_num(env, "RUNNER_TASK_MAX_COST_USD", d["task_max_cost_usd"].default),
            day_max_cost_usd=_num(env, "RUNNER_DAY_MAX_COST_USD", d["day_max_cost_usd"].default),
            task_max_tokens=int(_num(env, "RUNNER_TASK_MAX_TOKENS", d["task_max_tokens"].default)),
            day_max_tokens=int(_num(env, "RUNNER_DAY_MAX_TOKENS", d["day_max_tokens"].default)),
            dry_run=_flag(env, "RUNNER_DRY_RUN", d["dry_run"].default),
            task_kinds=_kinds(env.get("RUNNER_TASK_KINDS", "") or ",".join(d["task_kinds"].default)),
        )
