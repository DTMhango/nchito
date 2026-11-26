"""The runner's own budget line: per-task and per-day token and cost caps.

The day ledger is a small JSON file on the state volume, so a restart does not reset it.
A cap of 0 means "no spend allowed" (the runner stops immediately), never "unlimited".
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class BudgetExhausted(Exception):
    def __init__(self, scope: str, detail: str):
        super().__init__(f"{scope} budget exhausted: {detail}")
        self.scope = scope  # "task" or "day"
        self.detail = detail


@dataclass
class Caps:
    task_cost_usd: float
    day_cost_usd: float
    task_tokens: int
    day_tokens: int


class Budget:
    def __init__(self, path: Path, caps: Caps, clock: Callable[[], datetime] | None = None):
        self.path = path
        self.caps = caps
        self._clock = clock or (lambda: datetime.now(UTC))
        self.task_cost = 0.0
        self.task_tokens = 0
        self._day, self.day_cost, self.day_tokens = self._load()

    def _today(self) -> str:
        return self._clock().date().isoformat()

    def _load(self) -> tuple[str, float, int]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if data.get("day") == self._today():
                return data["day"], float(data["cost"]), int(data["tokens"])
        except (OSError, ValueError, KeyError):
            pass
        return self._today(), 0.0, 0

    def _roll(self) -> None:
        if self._day != self._today():
            self._day, self.day_cost, self.day_tokens = self._today(), 0.0, 0

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": self._day, "cost": self.day_cost, "tokens": self.day_tokens}), "utf-8")
        os.replace(tmp, self.path)

    def start_task(self) -> None:
        self.task_cost = 0.0
        self.task_tokens = 0

    def add(self, tokens: int, cost_usd: float) -> None:
        self._roll()
        self.task_tokens += tokens
        self.task_cost += cost_usd
        self.day_tokens += tokens
        self.day_cost += cost_usd
        self._save()

    def check_day(self) -> None:
        self._roll()
        if self.day_cost >= self.caps.day_cost_usd or self.day_tokens >= self.caps.day_tokens:
            raise BudgetExhausted("day", f"{self.day_cost:.2f} USD, {self.day_tokens} tokens today")

    def check(self) -> None:
        self.check_day()
        if self.task_cost >= self.caps.task_cost_usd or self.task_tokens >= self.caps.task_tokens:
            raise BudgetExhausted("task", f"{self.task_cost:.2f} USD, {self.task_tokens} tokens on this task")

    def remaining_cost_usd(self) -> float:
        self._roll()
        return max(0.0, min(self.caps.task_cost_usd - self.task_cost, self.caps.day_cost_usd - self.day_cost))
