"""Entry point: ``python -m nchito_runner`` (the container's command)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from .budget import Budget, Caps
from .config import ConfigError, RunnerConfig
from .driver import ClaudeSdkDriver
from .gateway import McpGateway
from .worker import Runner


async def _amain(cfg: RunnerConfig) -> None:
    budget = Budget(cfg.state_dir / "budget.json",
                    Caps(cfg.task_max_cost_usd, cfg.day_max_cost_usd, cfg.task_max_tokens, cfg.day_max_tokens))
    runner = Runner(cfg, McpGateway(cfg.mcp_url, cfg.token), ClaudeSdkDriver(cfg.model), budget)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(runner.stop.set))
    logging.getLogger("nchito_runner").info("runner up: model=%s url=%s", cfg.model, cfg.mcp_url)
    await runner.run_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        cfg = RunnerConfig.from_env()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("config error: ANTHROPIC_API_KEY is required (the server runner bills API tokens)", file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(_amain(cfg))


if __name__ == "__main__":
    main()
