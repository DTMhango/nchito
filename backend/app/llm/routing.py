"""Model routing: which provider and model serve a stage (settings ``ai.provider`` and ``ai.model_*``)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, get_args

from app.llm.client import LLMConfigError, Stage

STAGES: tuple[str, ...] = get_args(Stage)

# Stages without a model setting of their own borrow a sibling's (documented in DESIGN.md 11).
STAGE_SETTING: dict[str, str] = {
    "extract": "ai.model_extract",
    "classify_email": "ai.model_classify_email",
    "score": "ai.model_score",
    "custom_facet": "ai.model_custom_facet",
    "tailor": "ai.model_tailor",
    "claim_check": "ai.model_claim_check",
    "browser_agent": "ai.model_browser_agent",
    "interview": "ai.model_tailor",
    "import": "ai.model_extract",
}
ESCALATION_SETTING = "ai.model_score_escalation"
SCORE_THRESHOLD_SETTINGS = ("scoring.threshold_shortlist", "scoring.threshold_tailor", "scoring.threshold_auto_apply")


@dataclass(frozen=True)
class Route:
    stage: str
    provider: str
    model: str
    billed: bool


def resolve_route(values: Mapping[str, Any], stage: str, model: str | None = None) -> Route:
    if stage not in STAGE_SETTING:
        raise LLMConfigError(f"unknown stage {stage!r}")
    provider = values["ai.provider"]
    if provider == "claude_cli" and not values["ai.claude_cli_enabled"]:
        raise LLMConfigError("the Claude Code CLI is selected but not allowed (Settings > AI)")
    return Route(stage=stage, provider=provider, model=model or values[STAGE_SETTING[stage]],
                 billed=provider != "claude_cli")


def within_margin(score: float, thresholds: Iterable[float], margin: float) -> bool:
    """True when ``score`` lies within ``margin`` points of any threshold (inclusive)."""
    return any(abs(score - t) <= margin for t in thresholds)


def escalation_model(values: Mapping[str, Any], score: float) -> str | None:
    """The stronger model to re-score with when a score sits near a threshold, else ``None``.

    Pass the result as ``model=`` to ``complete("score", ...)``. Thresholds and the margin are
    the ``scoring.*`` settings; the model is ``ai.model_score_escalation``.
    """
    thresholds = [values[k] for k in SCORE_THRESHOLD_SETTINGS]
    if not within_margin(score, thresholds, values["scoring.escalation_margin"]):
        return None
    escalated = values[ESCALATION_SETTING]
    return None if escalated == values[STAGE_SETTING["score"]] else escalated
