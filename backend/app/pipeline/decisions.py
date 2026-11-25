"""The decision table: one module that serves discovery, dry runs and the submit-permit check,
so they cannot disagree (DESIGN.md 7, 8.1, 18.2).

Module boundary (contract):

- Input is a frozen ``DecisionInput`` snapshot assembled by the caller (no database access
  inside this module, no clock reads: ``now`` is passed in). Pure functions only.
- Precedence is fixed in code: **hard exclusions -> eligibility -> weighted score ->
  automation gates.** A high score cannot rescue an excluded role.
- **Unknown is not yes.** Every gate returns ``pass``, ``fail`` or ``unknown``; ``unknown``
  never permits an automatic outward action.
- Every gate result carries a human reason and the effective value and source of each rule
  (setting key, campaign field, rubric version), which the "Why?" panel displays.
- ``decide`` is the only public entry point. Wave 1 (filters/scoring stream) implements it;
  wave 2 (apply stream) adds the permit-time gates using the same function.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

GateOutcome = Literal["pass", "fail", "unknown"]
Purpose = Literal["discovery", "dry_run", "permit"]
Verdict = Literal["excluded", "review", "below_threshold", "shortlist", "tailor", "ask_owner", "auto_apply"]

# The order gates are evaluated in; later layers cannot override an earlier fail.
LAYERS: tuple[str, ...] = ("exclusion", "eligibility", "score", "automation")


@dataclass(frozen=True)
class RuleRef:
    rule: str
    effective_value: Any
    source: str
    version: str | None = None


@dataclass(frozen=True)
class GateDecision:
    gate: str
    layer: str
    outcome: GateOutcome
    reason: str
    rules: tuple[RuleRef, ...] = ()
    mandatory: bool = True


@dataclass(frozen=True)
class DecisionInput:
    purpose: Purpose
    now: datetime
    job: Mapping[str, Any]
    campaign: Mapping[str, Any]
    settings: Mapping[str, Any]
    score: int | None
    rubric_version: int | None
    conflict_state: Literal["none", "winner", "held", "released"]
    counters: Mapping[str, int] = field(default_factory=dict)  # sent today / this week, live per employer
    application: Mapping[str, Any] | None = None  # packet, checks, answers (permit purpose)


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    gates: Sequence[GateDecision]
    auto_apply_allowed: bool

    @property
    def blocking(self) -> list[GateDecision]:
        return [g for g in self.gates if g.mandatory and g.outcome != "pass"]


class DecisionTable(Protocol):
    def decide(self, data: DecisionInput) -> Decision:
        ...
