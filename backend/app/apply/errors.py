"""Stable machine codes for refusals on packet build, approval, permit and dispatch (CONTRACTS.md, wave 2
send-flow). Every 409/422 these endpoints raise is ``{"detail": {"code": <code>, "reason": <words>, ...}}``;
clients switch on ``code`` and show ``reason``. A refusal decided by the gates takes the code of its first
blocking gate (``GATE_CODES``); the decision table's own words never become a code.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# The codes, one place. Adding one is a contract change (document it in CONTRACTS.md).
CODES: tuple[str, ...] = (
    "no_spec", "check_stale", "check_blocking", "document_not_rendered", "answers_waiting", "no_destination",
    "no_identity", "unknown_template", "invalid_packet", "no_packet", "packet_superseded", "packet_changed",
    "channel_mismatch", "illegal_stage", "not_approved", "mode_not_allowed", "excluded", "held_by_conflict",
    "employer_cooldown", "paused", "quiet_hours", "cap_reached", "budget", "duplicate", "permit_outstanding",
    "posting_changed", "role_closed", "deadline_passed", "email_unconfirmed", "destination_unverified",
    "untrusted_site", "answers_not_automatic", "runner_refused", "channel_unavailable", "retry_limit",
    "waiver_reason_required", "note_required", "not_found", "already_handed_over", "already_settled",
    "not_uncertain", "not_started", "still_queued", "nothing_to_submit", "system_channel", "invalid_address",
    "no_address", "below_auto_threshold", "unknown_data", "pay_not_stated", "always_ask_first",
    "campaign_unconfirmed", "refused",
)

GATE_CODES: dict[str, str] = {
    "global_pause": "paused", "quiet_hours": "quiet_hours", "daily_cap": "cap_reached", "weekly_cap": "cap_reached",
    "conflict_winner": "held_by_conflict", "employer_conflict": "held_by_conflict", "employer_live": "held_by_conflict",
    "employer_cooldown": "employer_cooldown", "document_checks": "check_blocking", "packet_current":
    "packet_superseded", "packet_sources": "packet_changed", "approval_bound": "not_approved", "channel_bound":
    "channel_mismatch", "duplicate": "duplicate", "outstanding_permit": "permit_outstanding", "job_version":
    "posting_changed", "role_open": "role_closed", "deadline": "deadline_passed", "budget": "budget",
    "recipient_confirmed": "email_unconfirmed", "destination_verified": "destination_unverified", "trusted_site":
    "untrusted_site", "answers_auto": "answers_not_automatic", "runner": "runner_refused",
    "auto_threshold": "below_auto_threshold", "known_data": "unknown_data", "pay_stated": "pay_not_stated",
    "always_ask_first": "always_ask_first", "campaign_ready": "campaign_unconfirmed",
}


def for_spec(reason: str) -> str:
    """The code of a ``prepare.spec_gate`` / ``spec_state`` refusal."""
    if "no tailored spec" in reason:
        return "no_spec"
    if "is stale" in reason:
        return "check_stale"
    if "not a document rendered" in reason:
        return "document_not_rendered"
    return "check_blocking"


def for_gate(gate: str, reason: str = "") -> str:
    if gate == "spec_checked":
        return for_spec(reason)
    return GATE_CODES.get(gate, "refused")


def for_gate_results(results: Iterable[Mapping[str, Any]], reason: str = "") -> str:
    """The code of the first failing gate in ``Evaluation.gate_results()`` form (hard failures first)."""
    rows = [r for r in results if not r.get("passed", r.get("outcome") == "pass")]
    for outcome in ("fail", "unknown"):
        for r in rows:
            if r.get("outcome", "fail") == outcome:
                return for_gate(str(r.get("gate")), str(r.get("detail", "")))
    return for_reason(reason)


def for_reason(reason: str) -> str:
    """Codes for decisions that name no gate (the permit outcome's own words)."""
    if reason.startswith("excluded"):
        return "excluded"
    if "does not let the system apply" in reason or "needs your approval" in reason:
        return "mode_not_allowed"
    if "not approved" in reason:
        return "not_approved"
    return "refused"


def for_permit_reason(reason: str, gate_names: Iterable[str] = ()) -> str:
    """The code of a refused permit or approval from its reason: the decision table names the first
    blocking gate first (``"<gate>: <why>; ..."``), else says why in its own words."""
    head, _, rest = reason.partition(":")
    if head.strip() in set(gate_names) | set(GATE_CODES) | {"spec_checked"}:
        return for_gate(head.strip(), rest)
    return for_reason(reason)


def for_evaluation(evaluation: Any) -> str:
    """The code of a refused ``gates.Evaluation``."""
    if evaluation.decision.verdict == "excluded":
        return "excluded"
    return for_permit_reason(evaluation.reason, (g.gate for g in evaluation.decision.gates))


def detail(code: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "reason": reason, **extra}
