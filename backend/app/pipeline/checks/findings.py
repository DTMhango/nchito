"""A check finding, and how findings become the stored ``CheckResult`` rows the Studio shows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.schemas.json_types import CheckResult

Status = Literal["pass", "warn", "block"]
_RANK = {"pass": 0, "warn": 1, "block": 2}


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    detail: str
    path: str | None = None
    guardrail_id: str | None = None
    waived: bool = False

    def result(self) -> CheckResult:
        detail = f"{self.path}: {self.detail}" if self.path else self.detail
        return CheckResult(check=self.check, status=self.status, detail=detail, guardrail_id=self.guardrail_id,
                           waived=self.waived)


def worst(results: Iterable[CheckResult]) -> Status:
    """``block`` if any unwaived block remains, else ``warn`` if any warning, else ``pass``."""
    status: Status = "pass"
    for r in results:
        effective: Status = "warn" if r.status == "block" and r.waived else r.status
        if _RANK[effective] > _RANK[status]:
            status = effective
    return status


def summarise(findings: Iterable[Finding], checks_run: Iterable[str]) -> list[CheckResult]:
    """Findings first (blocks, then warnings), then one ``pass`` row per check that found nothing.
    A finding's check may carry a sub-type after a dot (``guardrails.never_mention``)."""
    found = sorted(findings, key=lambda f: -_RANK["warn" if f.waived else f.status])
    seen = {f.check.split(".", 1)[0] for f in found}
    passes = [CheckResult(check=c, status="pass") for c in checks_run if c not in seen]
    return [f.result() for f in found] + passes
