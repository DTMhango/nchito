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
  wave 2 (apply stream) adds the permit-time gates using the same function: with purpose
  ``permit``, ``application`` carries ``approval``, ``channel``, ``permit_checks``
  (``{name: (outcome, reason[, owner_settles])}``) and ``for_approval``, and ``Decision.permit``
  is ``granted`` / ``wait_for_owner`` / ``denied`` with ``permit_reason``.
- The automation mode is resolved only by ``resolve_mode`` (campaign per-channel override, else
  campaign mode, else ``automation.default_mode``; capped while the campaign is unconfirmed).

Record shapes (built by ``app.pipeline.filters``):

- ``job``: ``filters.job_record(...)``: facets unwrapped, ``pay_state``, ``pay``, ``pay_estimate``,
  ``deadline_state``, ``deadline``, ``availability``, ``last_checked_at``, ``always_ask_first``.
- ``campaign``: ``filters.campaign_record(...)``: ``criteria``, ``unknown_data_policy``,
  ``automation``, ``status``, ``review_state``, ``work_rights`` (``None`` = not known), ``version``.
- ``rubric``: ``{"id", "version", "thresholds": {"shortlist", "tailor", "auto_apply"}}``; a
  ``None`` threshold falls back to the ``scoring.threshold_*`` setting.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from app.core.conditions import CampaignRule, evaluate
from app.schemas.json_types import CampaignCriteria, PayFloor

GateOutcome = Literal["pass", "fail", "unknown"]
Purpose = Literal["discovery", "dry_run", "permit"]
Verdict = Literal["excluded", "review", "below_threshold", "shortlist", "tailor", "ask_owner", "auto_apply"]
Policy = Literal["review", "pass_with_penalty", "pass_blocks_auto", "fail"]
PermitStatus = Literal["granted", "wait_for_owner", "denied"]

# The order gates are evaluated in; later layers cannot override an earlier fail.
LAYERS: tuple[str, ...] = ("exclusion", "eligibility", "score", "automation")
MODES: tuple[str, ...] = ("save_only", "prepare", "ask_then_apply", "auto_apply")
# Unconfirmed campaigns cannot go above this mode (principle 2, 8.1). An invariant, not a setting.
UNCONFIRMED_CEILING = "prepare"
# Lowest mode in which the system itself sends an application the owner approved (8.1).
SYSTEM_APPLIES_FROM = "ask_then_apply"

# Permit purpose (wave 2). Gates that only stand in for the owner's judgement: an owner approval of
# the packet settles them; an automatic approval needs every one to pass.
OWNER_SETTLES: frozenset[str] = frozenset({"auto_threshold", "known_data", "pay_stated", "always_ask_first"})
# Gates about *when* something may go out rather than *whether*: they do not decide an approval and
# are checked again when the permit is requested.
TIMING_GATES: frozenset[str] = frozenset({"global_pause", "daily_cap", "weekly_cap", "quiet_hours", "budget"})


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
    would_change_if: str | None = None


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
    rubric: Mapping[str, Any] | None = None  # id, version, thresholds
    override: Mapping[str, Any] | None = None  # assessment override: by, reason, at, score
    setting_versions: Mapping[str, int] = field(default_factory=dict)
    conflict_note: str | None = None


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    gates: Sequence[GateDecision]
    auto_apply_allowed: bool
    effective_score: int | None = None
    mode: str | None = None
    # Permit purpose only: the outcome of the permit check and its reason (blocking gates named).
    permit: PermitStatus | None = None
    permit_reason: str | None = None

    @property
    def blocking(self) -> list[GateDecision]:
        return [g for g in self.gates if g.mandatory and g.outcome != "pass"]

    def layer(self, name: str) -> list[GateDecision]:
        return [g for g in self.gates if g.layer == name]


class DecisionTable(Protocol):
    def decide(self, data: DecisionInput) -> Decision:
        ...


# ----- helpers ----------------------------------------------------------------------------


class _Ctx:
    """Reads settings and campaign values and produces ``RuleRef``s that say where they came from."""

    def __init__(self, data: DecisionInput) -> None:
        self.data = data
        self.campaign_version = str(data.campaign.get("version")) if data.campaign.get("version") else None
        self.rubric_version = (str(data.rubric.get("version")) if data.rubric and data.rubric.get("version")
                               is not None else (str(data.rubric_version) if data.rubric_version else None))

    def setting(self, key: str) -> tuple[Any, RuleRef]:
        value = self.data.settings.get(key)
        version = self.data.setting_versions.get(key)
        return value, RuleRef(key, value, "setting", f"v{version}" if version is not None else None)

    def campaign_ref(self, rule: str, value: Any) -> RuleRef:
        return RuleRef(rule, value, "campaign", self.campaign_version)

    def policy(self, kind: str) -> tuple[Policy, RuleRef]:
        own = (self.data.campaign.get("unknown_data_policy") or {}).get(kind)
        if own:
            return own, self.campaign_ref(f"unknown_data_policy.{kind}", own)
        value, ref = self.setting(f"scoring.unknown_{kind}")
        return value, ref

    def threshold(self, name: str) -> tuple[int, RuleRef]:
        thresholds = (self.data.rubric or {}).get("thresholds") or {}
        own = thresholds.get(name)
        if own is not None:
            return int(own), RuleRef(f"rubric.thresholds.{name}", own, "rubric", self.rubric_version)
        value, ref = self.setting(f"scoring.threshold_{name}")
        return int(value), ref


def _norm(value: Any) -> str:
    return str(value).strip().casefold()


def _facet(job: Mapping[str, Any], name: str) -> Any:
    value = (job.get("facets") or {}).get(name)
    return "not_stated" if value in (None, "", []) else value


def _apply_policy(gate: str, layer: str, kind: str, reason: str, rules: list[RuleRef], ctx: _Ctx,
                  would_change_if: str) -> tuple[GateDecision, int, bool]:
    """Turn a raw ``unknown`` into the gate the campaign's unknown-data policy asks for.

    Returns the gate, penalty points and whether the unknown must block automation. Unknown is
    never yes: every policy except ``fail`` keeps the outcome ``unknown`` (non-mandatory when
    the policy lets the role through) and blocks automatic actions.
    """
    policy, ref = ctx.policy(kind)
    rules = [*rules, ref]
    if policy == "fail":
        return GateDecision(gate, layer, "fail", f"{reason}; unknown treated as fail by policy", tuple(rules),
                            True, would_change_if), 0, True
    if policy == "review":
        return GateDecision(gate, layer, "unknown", f"{reason}; needs your review (policy)", tuple(rules),
                            True, would_change_if), 0, True
    if policy == "pass_with_penalty":
        points, pref = ctx.setting("scoring.unknown_penalty")
        return GateDecision(gate, layer, "unknown", f"{reason}; passed with a {points}-point penalty (policy)",
                            (*rules, pref), False, would_change_if), int(points or 0), True
    return GateDecision(gate, layer, "unknown", f"{reason}; passed, blocks automatic applying (policy)",
                        tuple(rules), False, would_change_if), 0, True


def _rules(campaign: Mapping[str, Any]) -> list[CampaignRule]:
    return _criteria(campaign).rules


def _criteria(campaign: Mapping[str, Any]) -> CampaignCriteria:
    raw = campaign.get("criteria")
    if isinstance(raw, CampaignCriteria):
        return raw
    return CampaignCriteria.model_validate(raw or {})


def _job_places(job: Mapping[str, Any]) -> set[str]:
    loc = job.get("location") or {}
    places = {_norm(v) for v in (loc.get("country"), loc.get("region"), loc.get("city")) if v}
    where = _facet(job, "where_must_live")
    if isinstance(where, Mapping):
        places |= {_norm(p) for p in where.get("places") or []}
    places |= {_norm(p) for p in (job.get("facets") or {}).get("remote_regions") or []}
    return places


# ----- layer 1: hard exclusions -----------------------------------------------------------


def _exclusions(data: DecisionInput, ctx: _Ctx) -> list[GateDecision]:
    job, gates = data.job, []
    for index, rule in enumerate(_rules(data.campaign)):
        if rule.effect not in ("exclude", "include"):
            continue
        name = rule.reason or f"rule {index + 1}"
        ref = ctx.campaign_ref(f"criteria.rules[{index}]", f"{rule.effect}: {name}")
        matched = evaluate(rule.conditions, job)
        if rule.effect == "exclude":
            gates.append(GateDecision(
                f"rule:{index}", "exclusion", "fail" if matched else "pass",
                f"matches exclusion '{name}'" if matched else f"does not match exclusion '{name}'", (ref,),
                would_change_if=f"remove or narrow the exclusion '{name}'" if matched else None))
        else:
            gates.append(GateDecision(
                f"rule:{index}", "exclusion", "pass" if matched else "fail",
                f"matches inclusion '{name}'" if matched else f"does not match inclusion '{name}'", (ref,),
                would_change_if=None if matched else f"widen the inclusion '{name}'"))

    deny = [loc.place for loc in _criteria(data.campaign).locations if loc.kind == "deny"]
    if deny:
        hit = _job_places(job) & {_norm(p) for p in deny}
        ref = ctx.campaign_ref("criteria.locations.deny", deny)
        gates.append(GateDecision("location_deny", "exclusion", "fail" if hit else "pass",
                                  f"location in deny list: {sorted(hit)}" if hit else "location not denied", (ref,),
                                  would_change_if="remove the place from the deny list" if hit else None))

    never = job.get("never_apply")
    if never is not None:  # the owner's per-employer "never apply" (7.1): never tailored, never sent
        gates.append(GateDecision("employer_never_apply", "exclusion", "fail",
                                  "you never apply to this employer" + (f": {never}" if never else ""),
                                  (RuleRef("employer_policy.never_apply", True, "employer policy"),),
                                  would_change_if="remove 'never apply' from the employer"))
    state, deadline = job.get("deadline_state") or "not_stated", job.get("deadline")
    if state == "dated" and isinstance(deadline, date) and deadline < data.now.date():
        gates.append(GateDecision("deadline_passed", "exclusion", "fail", f"deadline passed on {deadline}",
                                  (RuleRef("job.deadline", str(deadline), "job"),)))
    if job.get("availability") == "closed":
        gates.append(GateDecision("role_closed", "exclusion", "fail", "the role is closed",
                                  (RuleRef("job.availability", "closed", "job"),)))
    return gates


# ----- layer 2: eligibility ---------------------------------------------------------------


@dataclass
class _Eligibility:
    gates: list[GateDecision] = field(default_factory=list)
    penalty: int = 0
    blocks_auto: list[str] = field(default_factory=list)


def _add(result: _Eligibility, gate_penalty_block: tuple[GateDecision, int, bool]) -> None:
    gate, penalty, blocks = gate_penalty_block
    result.gates.append(gate)
    result.penalty += penalty
    if blocks:
        result.blocks_auto.append(gate.gate)


def _pay_meets(amount: int | None, currency: str | None, period: str | None,
               floor: PayFloor) -> GateOutcome:
    if amount is None or currency is None:
        return "unknown"
    if _norm(currency) != _norm(floor.currency) or _norm(period or "year") != _norm(floor.period):
        return "unknown"  # no conversion guesswork
    return "pass" if amount >= floor.amount_minor else "fail"


def _pay_against_floors(amount: int | None, currency: str | None, period: str | None,
                        floors: list[PayFloor]) -> GateOutcome:
    outcomes = {_pay_meets(amount, currency, period, f) for f in floors}
    if outcomes == {"pass"}:
        return "pass"
    if outcomes == {"fail"}:
        return "fail"
    return "unknown"


def _pay(data: DecisionInput, ctx: _Ctx, out: _Eligibility) -> None:
    job = data.job
    criteria = _criteria(data.campaign)
    employment = _facet(job, "employment_type")
    floors = [f for f in criteria.pay_floors if employment == "not_stated" or f.employment_type == employment]
    state = job.get("pay_state") or "not_stated"
    floor_ref = ctx.campaign_ref("criteria.pay_floors", [f.model_dump() for f in floors])
    if not criteria.pay_floors:
        out.gates.append(GateDecision("pay_floor", "eligibility", "pass", "no pay floor set for this campaign",
                                      (ctx.campaign_ref("criteria.pay_floors", []),), mandatory=False))
        if state != "stated":
            out.blocks_auto.append("pay_floor")
        return
    if not floors:
        out.gates.append(GateDecision("pay_floor", "eligibility", "pass",
                                      f"no pay floor for employment type '{employment}'", (floor_ref,), False))
        if state != "stated":
            out.blocks_auto.append("pay_floor")
        return
    if state == "stated":
        pay = job.get("pay") or {}
        amount = pay.get("max_minor") if pay.get("max_minor") is not None else pay.get("min_minor")
        outcome = _pay_against_floors(amount, pay.get("currency"), pay.get("period"), floors)
        stated_ref = RuleRef("job.pay (stated)", f"{amount} {pay.get('currency')}/{pay.get('period')}", "job")
        if outcome == "pass":
            out.gates.append(GateDecision("pay_floor", "eligibility", "pass", "stated pay meets the floor",
                                          (stated_ref, floor_ref)))
        elif outcome == "fail":
            out.gates.append(GateDecision("pay_floor", "eligibility", "fail", "stated pay is below the floor",
                                          (stated_ref, floor_ref), would_change_if="lower the pay floor"))
        else:
            _add(out, _apply_policy("pay_floor", "eligibility", "pay",
                                    "stated pay cannot be compared (currency, period or employment type differs)",
                                    [stated_ref, floor_ref], ctx, "state the pay in the floor's currency and period"))
        return
    if state == "estimated":
        est = job.get("pay_estimate") or {}
        amount = est.get("max_minor") if est.get("max_minor") is not None else est.get("min_minor")
        outcome = _pay_against_floors(amount, est.get("currency"), est.get("period"), floors)
        est_ref = RuleRef("pay_estimate", f"{amount} {est.get('currency')}/{est.get('period')}",
                          f"estimate: {est.get('source') or 'unknown source'}",
                          str(est.get("estimated_on")) if est.get("estimated_on") else None)
        if outcome == "pass":
            # Meets the floor on an estimate: passes the filter, but an estimate is not stated pay.
            out.gates.append(GateDecision("pay_floor", "eligibility", "unknown",
                                          "estimated pay meets the floor; not stated by the employer",
                                          (est_ref, floor_ref), mandatory=False,
                                          would_change_if="the employer states the pay"))
            out.blocks_auto.append("pay_floor")
        else:
            why = "estimated pay is below the floor" if outcome == "fail" else "estimate cannot be compared"
            _add(out, _apply_policy("pay_floor", "eligibility", "pay", why, [est_ref, floor_ref], ctx,
                                    "the employer states pay at or above the floor"))
        return
    _add(out, _apply_policy("pay_floor", "eligibility", "pay", "pay not stated",
                            [RuleRef("job.pay_state", "not_stated", "job"), floor_ref], ctx,
                            "the employer states the pay, or you add an estimate"))


def _location(data: DecisionInput, ctx: _Ctx, out: _Eligibility) -> None:
    allow = [loc.place for loc in _criteria(data.campaign).locations if loc.kind == "allow"]
    if not allow:
        return
    job = data.job
    ref = ctx.campaign_ref("criteria.locations.allow", allow)
    remote_world = _facet(job, "work_model") == "remote" and _facet(job, "remote_scope") == "worldwide"
    where = _facet(job, "where_must_live")
    anywhere = isinstance(where, Mapping) and where.get("kind") == "anywhere"
    places = _job_places(job)
    if remote_world or anywhere:
        out.gates.append(GateDecision("location", "eligibility", "pass", "open to applicants anywhere", (ref,)))
    elif places & {_norm(p) for p in allow}:
        out.gates.append(GateDecision("location", "eligibility", "pass",
                                      f"location allowed: {sorted(places & {_norm(p) for p in allow})}", (ref,)))
    elif not places:
        _add(out, _apply_policy("location", "eligibility", "eligibility", "location not stated", [ref], ctx,
                                "the posting states where the role is"))
    else:
        out.gates.append(GateDecision("location", "eligibility", "fail", f"location {sorted(places)} not allowed",
                                      (ref,), would_change_if="add the place to the campaign's locations"))


def _work_model(data: DecisionInput, ctx: _Ctx, out: _Eligibility) -> None:
    wanted = _criteria(data.campaign).work_models
    if not wanted:
        return
    ref = ctx.campaign_ref("criteria.work_models", wanted)
    actual = _facet(data.job, "work_model")
    if actual == "not_stated":
        _add(out, _apply_policy("work_model", "eligibility", "eligibility", "work model not stated", [ref], ctx,
                                "the posting states the work model"))
    elif actual in wanted:
        out.gates.append(GateDecision("work_model", "eligibility", "pass", f"work model {actual} wanted", (ref,)))
    else:
        out.gates.append(GateDecision("work_model", "eligibility", "fail", f"work model {actual} not wanted", (ref,),
                                      would_change_if=f"add {actual} to the campaign's work models"))


def _kit_fact_text(fact: Mapping[str, Any] | None, label: str) -> str:
    if not fact or fact.get("value") is None:
        return ""
    return f"; your answer '{fact.get('question')}' ({label})"


def _work_rights_from_kit(data: DecisionInput, ctx: _Ctx, out: _Eligibility, kit: Mapping[str, Any]) -> None:
    """Work rights from the Kit's confirmed answers against the job's where-you-must-live, work-rights-needed
    and sponsorship-offered facets. Unconfirmed answers never reach here: they resolve to unknown."""
    job = data.job
    need = _facet(job, "work_rights")
    offered = _facet(job, "visa_sponsorship")
    sponsored = need == "sponsorship_possible" or offered == "yes"
    right, needs = kit.get("right") or {}, kit.get("needs_sponsorship") or {}
    campaign_rights = data.campaign.get("work_rights")
    held: bool | None = right.get("value")
    if held is None and campaign_rights is not None and (places := _job_places(job)):
        held = bool(places & {_norm(r) for r in campaign_rights}) or None
    ref = RuleRef("kit.work_rights", {"right": right.get("value"), "needs_sponsorship": needs.get("value")}, "kit")
    ask = "answer the work-rights question in your Kit and confirm it"
    if held is True:
        out.gates.append(GateDecision("work_rights", "eligibility", "pass",
                                      "you have the right to work there" + _kit_fact_text(right, "yes"), (ref,)))
    elif sponsored:
        why = "sponsorship is offered"
        if needs.get("value") is True:
            why += " and you need it" + _kit_fact_text(needs, "yes")
        elif held is False:
            why += "; you have no right to work there" + _kit_fact_text(right, "no")
        out.gates.append(GateDecision("work_rights", "eligibility", "pass", why, (ref,)))
    elif need == "not_stated" and offered == "not_stated":
        _add(out, _apply_policy("work_rights", "eligibility", "eligibility", "work-rights requirement not stated",
                                [ref], ctx, "the posting states its work-rights requirement"))
    elif held is False:
        no_sponsor = "; sponsorship is not offered" if offered == "no" else ""
        out.gates.append(GateDecision(
            "work_rights", "eligibility", "fail",
            "existing right to work required where you have none" + no_sponsor + _kit_fact_text(right, "no"),
            (ref,), would_change_if="the employer offers sponsorship"))
    else:
        _add(out, _apply_policy("work_rights", "eligibility", "eligibility",
                                "existing right to work required; your rights there are not known"
                                + (f" ({right['note']})" if right.get("note") else ""), [ref], ctx, ask))


def _work_rights(data: DecisionInput, ctx: _Ctx, out: _Eligibility) -> None:
    job = data.job
    kit = job.get("kit_work_rights")
    if isinstance(kit, Mapping):
        _work_rights_from_kit(data, ctx, out, kit)
        return
    need = _facet(job, "work_rights")
    rights = data.campaign.get("work_rights")
    ref = RuleRef("kit.work_rights", rights if rights is not None else "not known", "kit")
    if need == "sponsorship_possible":
        out.gates.append(GateDecision("work_rights", "eligibility", "pass", "sponsorship possible", (ref,)))
        return
    if need == "not_stated":
        _add(out, _apply_policy("work_rights", "eligibility", "eligibility", "work-rights requirement not stated",
                                [ref], ctx, "the posting states its work-rights requirement"))
        return
    places = _job_places(job)
    if rights is None or not places:
        _add(out, _apply_policy("work_rights", "eligibility", "eligibility",
                                "existing right to work required; your rights there are not known", [ref], ctx,
                                "answer the work-rights question in your Kit"))
        return
    if places & {_norm(r) for r in rights}:
        out.gates.append(GateDecision("work_rights", "eligibility", "pass", "you have the right to work there",
                                      (ref,)))
    else:
        out.gates.append(GateDecision("work_rights", "eligibility", "fail",
                                      "existing right to work required where you have none", (ref,),
                                      would_change_if="the employer offers sponsorship"))


def _deadline(data: DecisionInput, ctx: _Ctx, out: _Eligibility) -> None:
    state = data.job.get("deadline_state") or "not_stated"
    ref = RuleRef("job.deadline_state", state, "job")
    if state == "open_until_filled":
        out.gates.append(GateDecision("deadline", "eligibility", "pass", "open until filled", (ref,)))
    elif state == "dated":
        out.gates.append(GateDecision("deadline", "eligibility", "pass",
                                      f"deadline {data.job.get('deadline')}", (ref,)))
    else:
        _add(out, _apply_policy("deadline", "eligibility", "deadline", "deadline not stated", [ref], ctx,
                                "the posting states a deadline"))


def _eligibility(data: DecisionInput, ctx: _Ctx) -> _Eligibility:
    out = _Eligibility()
    _location(data, ctx, out)
    _work_rights(data, ctx, out)
    _work_model(data, ctx, out)
    _pay(data, ctx, out)
    _deadline(data, ctx, out)
    return out


# ----- layer 3: score ---------------------------------------------------------------------


def _score(data: DecisionInput, ctx: _Ctx, unknown_penalty: int) -> tuple[list[GateDecision], int | None]:
    gates: list[GateDecision] = []
    base, refs = data.score, []
    if data.override and data.override.get("score") is not None:
        base = int(data.override["score"])
        refs.append(RuleRef("assessment.override", base, f"override by {data.override.get('by')}",
                            str(data.override.get("at")) if data.override.get("at") else None))
    if base is None:
        gates.append(GateDecision("score", "score", "unknown", "not scored yet", (), True, "score the role"))
        return gates, None
    refs.append(RuleRef("rubric.score", data.score, "rubric", ctx.rubric_version))
    total = base
    for index, rule in enumerate(_rules(data.campaign)):
        if rule.effect not in ("penalty", "bonus") or not evaluate(rule.conditions, data.job):
            continue
        points = int(rule.points or 0) * (-1 if rule.effect == "penalty" else 1)
        total += points
        gates.append(GateDecision(f"rule:{index}", "score", "pass",
                                  f"{rule.effect} {points:+d}: {rule.reason or f'rule {index + 1}'}",
                                  (ctx.campaign_ref(f"criteria.rules[{index}]", points),), mandatory=False))
    if unknown_penalty:
        total -= unknown_penalty
        _, pref = ctx.setting("scoring.unknown_penalty")
        gates.append(GateDecision("unknown_penalty", "score", "pass",
                                  f"-{unknown_penalty} for unknown data passed with penalty", (pref,), False))
    total = max(0, min(100, total))
    shortlist, sref = ctx.threshold("shortlist")
    ok = total >= shortlist
    gates.insert(0, GateDecision(
        "score", "score", "pass" if ok else "fail",
        f"score {total} {'>=' if ok else '<'} shortlist threshold {shortlist}", (*refs, sref),
        would_change_if=None if ok else f"score {shortlist - total} more points, or lower the shortlist threshold"))
    return gates, total


# ----- layer 4: automation ----------------------------------------------------------------


@dataclass(frozen=True)
class ModeResolution:
    """The automation mode in force for one campaign and channel, and why (DESIGN.md 8.1)."""

    mode: str
    rules: tuple[RuleRef, ...]
    confirmed: bool
    reason: str


def resolve_mode(campaign: Mapping[str, Any], channel: str | None, *, default_mode: Any = None,
                 default_version: str | None = None) -> ModeResolution:
    """The one place the automation mode is resolved: the campaign's per-channel override, else its
    mode, else ``automation.default_mode``; then capped at ``prepare`` while the campaign is not confirmed.
    Pure; the reason names the rule, value, source and version used."""
    version = str(campaign.get("version")) if campaign.get("version") else None
    automation = campaign.get("automation") or {}
    per_channel = automation.get("per_channel") or {}
    if channel and per_channel.get(channel):
        wanted = per_channel[channel]
        ref = RuleRef(f"automation.per_channel.{channel}", wanted, "campaign", version)
    elif automation.get("mode"):
        wanted = automation["mode"]
        ref = RuleRef("automation.mode", wanted, "campaign", version)
    else:
        wanted = default_mode or UNCONFIRMED_CEILING
        ref = RuleRef("automation.default_mode", wanted, "setting", default_version)
    refs = [ref]
    reason = f"mode {wanted} from {ref.rule} ({ref.source}{f' {ref.version}' if ref.version else ''})"
    confirmed = campaign.get("review_state") == "confirmed" and bool(campaign.get("confirmed", True))
    if not confirmed and MODES.index(wanted) > MODES.index(UNCONFIRMED_CEILING):
        refs.append(RuleRef("mode_ceiling", UNCONFIRMED_CEILING, "campaign not confirmed", version))
        reason += f"; capped at {UNCONFIRMED_CEILING} until the campaign is confirmed"
        return ModeResolution(UNCONFIRMED_CEILING, tuple(refs), confirmed, reason)
    return ModeResolution(wanted, tuple(refs), confirmed, reason)


def _effective_mode(data: DecisionInput, ctx: _Ctx) -> tuple[str, list[RuleRef], bool]:
    channel = (data.application or {}).get("channel")
    version = data.setting_versions.get("automation.default_mode")
    res = resolve_mode(data.campaign, channel, default_mode=data.settings.get("automation.default_mode"),
                       default_version=f"v{version}" if version is not None else None)
    return res.mode, list(res.rules), res.confirmed


def _in_quiet_hours(data: DecisionInput) -> bool | None:
    start, end = data.settings.get("automation.quiet_hours_start"), data.settings.get("automation.quiet_hours_end")
    tz = data.settings.get("general.timezone")
    if not start or not end or not tz:
        return None
    local = data.now.astimezone(ZoneInfo(tz)).time()
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    return (s <= local or local < e) if s > e else (s <= local < e)


def _automation(data: DecisionInput, ctx: _Ctx, score: int | None, blocks: list[str],
                confirmed: bool) -> list[GateDecision]:
    gates: list[GateDecision] = []
    job, counters = data.job, data.counters

    def gate(name: str, outcome: GateOutcome, reason: str, *rules: RuleRef, change: str | None = None) -> None:
        gates.append(GateDecision(name, "automation", outcome, reason, rules, True, change))

    status = data.campaign.get("status")
    ok = status == "active" and confirmed
    gate("campaign_ready", "pass" if ok else "fail",
         "campaign active and confirmed" if ok else f"campaign is {status}"
         f"{'' if confirmed else ', criteria not confirmed'}",
         ctx.campaign_ref("status", status), ctx.campaign_ref("review_state", data.campaign.get("review_state")),
         change=None if ok else "activate and confirm the campaign")

    auto, aref = ctx.threshold("auto_apply")
    if score is None:
        gate("auto_threshold", "unknown", "not scored yet", aref)
    else:
        gate("auto_threshold", "pass" if score >= auto else "fail",
             f"score {score} {'>=' if score >= auto else '<'} auto-apply threshold {auto}", aref,
             change=None if score >= auto else f"score {auto - score} more points")

    gate("known_data", "unknown" if blocks else "pass",
         f"unknown data blocks automatic applying: {', '.join(blocks)}" if blocks else "no unknowns on filters",
         change="resolve the unknowns" if blocks else None)
    pay_state = job.get("pay_state") or "not_stated"
    gate("pay_stated", "pass" if pay_state == "stated" else "unknown", f"pay is {pay_state.replace('_', ' ')}",
         RuleRef("job.pay_state", pay_state, "job"),
         change=None if pay_state == "stated" else "the employer states the pay")

    max_age, mref = ctx.setting("automation.open_check_max_age_hours")
    checked = job.get("last_checked_at")
    fresh = (job.get("availability") == "open" and isinstance(checked, datetime) and max_age is not None
             and data.now - checked <= timedelta(hours=int(max_age)))
    gate("role_open", "pass" if fresh else "unknown",
         "open as of the last check" if fresh else "not confirmed open recently", mref,
         change=None if fresh else "recheck that the role is open")

    scope, scope_ref = ctx.setting("matching.roles_per_employer_scope")
    cstate = data.conflict_state
    if cstate in ("winner", "released") or (cstate == "none" and scope == "off"):
        gate("conflict_winner", "pass", f"conflict group: {cstate}", scope_ref)
    elif cstate == "held":
        gate("conflict_winner", "fail", data.conflict_note or "held: outranked in its employer group", scope_ref,
             change="the winner closes or is skipped, or you release this role")
    else:
        gate("conflict_winner", "unknown", "employer conflict group not decided yet", scope_ref)

    if job.get("always_ask_first"):
        gate("always_ask_first", "fail", "employer flagged 'always ask first'",
             RuleRef("watched_employer.always_ask_first", True, "watched employer"))
    max_live, lref = ctx.setting("matching.max_live_per_employer")
    live = counters.get("employer_live")
    if live is not None and max_live is not None:
        gate("employer_live", "pass" if live < int(max_live) else "fail",
             f"{live} live application(s) at this employer (max {max_live})", lref)
    if counters.get("employer_cooldown_days_left"):
        _, cref = ctx.setting("matching.employer_cooldown_days")
        gate("employer_cooldown", "fail", f"employer cooldown: {counters['employer_cooldown_days_left']} day(s) left",
             cref)

    paused, pref = ctx.setting("automation.paused")
    gate("global_pause", "fail" if paused else "pass", "automation paused" if paused else "not paused", pref)
    for key, counter, label in (("automation.daily_cap", "sent_today", "today"),
                                ("automation.weekly_cap", "sent_week", "this week")):
        cap, cref = ctx.setting(key)
        sent = counters.get(counter)
        if sent is None or cap is None:
            gate(key.split(".")[1], "unknown", f"sent {label} not known", cref)
        else:
            gate(key.split(".")[1], "pass" if sent < int(cap) else "fail", f"{sent} sent {label} (cap {cap})", cref)
    quiet = _in_quiet_hours(data)
    _, qref = ctx.setting("automation.quiet_hours_start")
    gate("quiet_hours", "unknown" if quiet is None else ("fail" if quiet else "pass"),
         "quiet hours not known" if quiet is None else ("inside quiet hours" if quiet else "outside quiet hours"),
         qref)
    if data.purpose == "permit":
        # Permit-time checks (packet binding, approval, document checks, answers, channel, trusted site,
        # duplicates, budget) are assembled by ``app.apply.gates``. Until they are evaluated, the permit
        # is not granted.
        app = data.application or {}
        checks = app.get("permit_checks")
        if not checks:
            gate("permit_checks", "unknown", "permit-time checks not evaluated")
        else:
            for name, check in checks.items():
                gate(name, check[0], check[1])
    return gates


def _owner_settled_checks(data: DecisionInput) -> set[str]:
    """Permit checks supplied as ``(outcome, reason, True)``: the owner's approval settles them."""
    checks = (data.application or {}).get("permit_checks") or {}
    return {name for name, check in checks.items() if len(check) > 2 and check[2]}


def _permit(data: DecisionInput, verdict: Verdict, mode: str, gates: Sequence[GateDecision],
            auto_gates: Sequence[GateDecision]) -> tuple[PermitStatus, str]:
    """The permit outcome (wave 2). ``application``: ``approval`` (``owner`` / ``auto`` / ``None``),
    ``channel``, ``permit_checks`` and ``for_approval`` (True when deciding an automatic approval, so the
    timing gates are left for the permit itself).

    Precedence holds: an excluded role is denied whatever its score or approval. Every other gate that
    is not passing denies, except the ones an owner approval settles (``OWNER_SETTLES``, plus a role not
    confirmed open recently when ``automation.permit_unknown_open`` allows it), which send an automatic
    approval back to the owner. Unknown never grants."""
    app = data.application or {}
    approval, channel = app.get("approval"), app.get("channel")
    if verdict == "excluded":
        first = next(g for g in gates if g.layer in ("exclusion", "eligibility") and g.outcome == "fail"
                     and g.mandatory)
        return "denied", f"excluded: {first.reason}"
    settles = set(OWNER_SETTLES) | _owner_settled_checks(data)
    if approval == "owner" and data.settings.get("automation.permit_unknown_open") == "allow_when_owner_approved":
        settles.add("role_open")
    blocking = [g for g in auto_gates if g.mandatory and g.outcome != "pass"]
    if app.get("for_approval"):
        # An owner's approval is not about freshness either: the open check is repeated at permit time.
        later = TIMING_GATES | ({"role_open"} if approval == "owner" else set())
        blocking = [g for g in blocking if g.gate not in later]
    hard = [g for g in blocking if g.gate not in settles]
    soft = [g for g in blocking if g.gate in settles]
    if hard:
        return "denied", "; ".join(f"{g.gate}: {g.reason}" for g in hard)
    if approval == "owner":
        if channel != "manual" and MODES.index(mode) < MODES.index(SYSTEM_APPLIES_FROM):
            return "denied", f"effective mode {mode} does not let the system apply; use the manual handoff"
        return "granted", "approved by the owner; every permit gate passes"
    if approval == "auto":
        if mode != "auto_apply":
            return "wait_for_owner", f"effective mode {mode} needs your approval"
        if soft:
            return "wait_for_owner", "; ".join(f"{g.gate}: {g.reason}" for g in soft)
        if verdict in ("review", "below_threshold") or data.conflict_state == "held":
            return "wait_for_owner", f"verdict {verdict} needs your approval"
        return "granted", "automatic approval; every gate passes with no unknowns"
    return "denied", "the packet is not approved"


# ----- decide -----------------------------------------------------------------------------


def decide(data: DecisionInput) -> Decision:
    """The decision table. Fixed precedence; see the module docstring."""
    ctx = _Ctx(data)
    gates: list[GateDecision] = list(_exclusions(data, ctx))
    excluded = any(g.outcome == "fail" for g in gates)
    elig = _eligibility(data, ctx)
    gates += elig.gates
    ineligible = any(g.outcome == "fail" and g.mandatory for g in elig.gates)
    review = any(g.outcome == "unknown" and g.mandatory for g in elig.gates)
    score_gates, score = _score(data, ctx, elig.penalty)
    gates += score_gates
    mode, mode_refs, confirmed = _effective_mode(data, ctx)
    auto_gates = _automation(data, ctx, score, elig.blocks_auto, confirmed)
    gates += auto_gates

    tailor, _ = ctx.threshold("tailor")
    verdict: Verdict
    if excluded or ineligible:
        verdict = "excluded"
    elif review or score is None:
        verdict = "review"
    elif score < ctx.threshold("shortlist")[0]:
        verdict = "below_threshold"
    elif data.conflict_state == "held":
        verdict = "shortlist"  # listed with the outranking reason; not tailored, not applied
    elif mode == "save_only" or score < tailor:
        verdict = "shortlist"
    elif mode == "prepare":
        verdict = "tailor"
    elif mode == "ask_then_apply":
        verdict = "ask_owner"
    else:
        all_pass = all(g.outcome == "pass" for g in auto_gates if g.mandatory)
        verdict = "auto_apply" if all_pass else "ask_owner"
    gates.append(GateDecision("mode", "automation", "pass", f"effective mode: {mode}", tuple(mode_refs), False))
    permit: PermitStatus | None = None
    permit_reason: str | None = None
    if data.purpose == "permit":
        permit, permit_reason = _permit(data, verdict, mode, gates, auto_gates)
    return Decision(verdict=verdict, gates=tuple(gates), auto_apply_allowed=verdict == "auto_apply",
                    effective_score=score, mode=mode, permit=permit, permit_reason=permit_reason)


class Table:
    """``DecisionTable`` implementation (the module function is the same thing)."""

    def decide(self, data: DecisionInput) -> Decision:
        return decide(data)


TABLE: DecisionTable = Table()
