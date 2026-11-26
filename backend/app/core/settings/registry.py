"""The settings registry: the one place every business setting and its default is defined.

Rules (DESIGN.md section 1, configurability guardrails):

- A setting needs a real second option someone would plausibly choose.
- Invariants are never settings: audit logging, the submit permit, duplicate protection,
  secret handling, untrusted-content isolation, spend ledger integrity.
- Each setting has one default (here), a validator, and an ``example`` non-default value
  that the generated tests validate. Changes are versioned and audited by ``service.py``.
- Pay floors, countries, seniority, visa and relocation answers have no defaults in code:
  they are Kit data confirmed by the owner.

Deployment choices (database URL, secrets, base URL) live in env (``app.core.config``).
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_config
from app.core.settings.types import (
    SettingDef,
    SettingKind,
    SettingValueError,
    cron_expr,
    currency_code,
    hex_color,
    max_length,
    model_name,
    non_empty,
    slug,
    time_of_day,
    timezone_name,
    unique_items,
)

GROUPS: dict[str, str] = {
    "general": "General",
    "appearance": "Appearance",
    "schedule": "Schedule",
    "scoring": "Scoring",
    "matching": "Matching",
    "automation": "Automation",
    "tracking": "Tracking",
    "answers": "Answer bank",
    "reconcile": "Reconciliation",
    "ai": "AI",
    "budget": "Budget",
    "documents": "Documents",
    "retention": "Retention",
    "backups": "Backups",
    "notifications": "Notifications",
    "runners": "Runners",
}

AUTOMATION_MODES = ("save_only", "prepare", "ask_then_apply", "auto_apply")
UNKNOWN_POLICIES = ("review", "pass_with_penalty", "pass_blocks_auto", "fail")
ANSWER_SCOPES = ("this_application", "this_employer", "this_country", "all_matching")
NOTIFICATION_CHANNELS = ("telegram", "email", "webhook")

_DEFS: list[SettingDef] = []


def _add(
    key: str,
    kind: SettingKind,
    label: str,
    description: str,
    default: Any,
    example: Any,
    python_type: Any,
    **kwargs: Any,
) -> None:
    group = key.split(".", 1)[0]
    if group not in GROUPS:
        raise ValueError(f"unknown settings group for {key}")
    _DEFS.append(
        SettingDef(
            key=key,
            kind=kind,
            group=group,
            label=label,
            description=description,
            default=default,
            example=example,
            python_type=python_type,
            **kwargs,
        )
    )


_THEME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _theme_id_check(value: Any) -> None:
    """A theme id is a slug (built-ins, owner themes created with one) or a UUID."""
    if not _THEME_ID_RE.match(str(value)):
        raise SettingValueError(f"not a valid theme id: {value!r}")


def _accent_check(value: Any) -> None:
    """An accent swatch id (frontend accents.json) or a #RRGGBB colour."""
    if str(value).startswith("#"):
        hex_color(value)
    else:
        slug(value)


def _int(key: str, label: str, description: str, default: int | None, example: int, lo: int, hi: int,
         unit: str | None = None, nullable: bool = False) -> None:
    _add(key, "int", label, description, default, example, int | None if nullable else int,
         minimum=lo, maximum=hi, unit=unit, nullable=nullable,
         invalid_example=hi + 1, has_invalid_example=True)


def _enum(key: str, label: str, description: str, default: str, example: str, choices: tuple[str, ...]) -> None:
    _add(key, "enum", label, description, default, example, str, choices=choices,
         invalid_example="__not_a_choice__", has_invalid_example=True)


def _bool(key: str, label: str, description: str, default: bool) -> None:
    _add(key, "bool", label, description, default, not default, bool,
         invalid_example="yes", has_invalid_example=True)


def _model(key: str, label: str, description: str, default: str, example: str) -> None:
    _add(key, "string", label, description, default, example, str, validators=(model_name,),
         invalid_example="bad model name!", has_invalid_example=True)


def _cron(key: str, label: str, description: str, default: str, example: str) -> None:
    _add(key, "cron", label, description, default, example, str, validators=(cron_expr,),
         invalid_example="every day at six", has_invalid_example=True)


# ---------------------------------------------------------------------------------------
# General
_add("general.app_name", "string", "App name",
     "Shown in the title bar and emails. Env APP_NAME sets the default; this setting overrides it.",
     None, "Kazi", str, validators=(non_empty, max_length(40)),
     default_factory=lambda: get_config().app_name, invalid_example="", has_invalid_example=True)
_add("general.timezone", "timezone", "Time zone",
     "Times are stored in UTC and displayed in this zone. Quiet hours use it too.",
     "Africa/Lusaka", "Europe/London", str, validators=(timezone_name,),
     invalid_example="Mars/Olympus", has_invalid_example=True)
_add("general.display_currency", "currency", "Display currency",
     "Currency used when amounts are shown side by side.",
     "USD", "ZMW", str, validators=(currency_code,), invalid_example="usd", has_invalid_example=True)

# Appearance (also served by /api/settings/appearance)
_add("appearance.theme_id", "string", "Theme", "Active theme (a theme id: slug or UUID).",
     "copperbelt", "paper", str, validators=(_theme_id_check,), invalid_example="Not A Theme!",
     has_invalid_example=True)
_enum("appearance.mode", "Mode", "Light, dark, or follow the device.", "system", "dark",
      ("light", "dark", "system"))
_enum("appearance.density", "Density", "Spacing of lists and tables.", "comfortable", "compact",
      ("comfortable", "compact"))
_add("appearance.radius", "int", "Corner radius",
     "Override the theme's corner radius in pixels. Empty uses the theme's own.",
     None, 6, int | None, nullable=True, minimum=0, maximum=24, unit="px",
     invalid_example=99, has_invalid_example=True)
_add("appearance.font_scale", "float", "Font size", "Root text size relative to 14px.",
     1.0, 15 / 14, float, minimum=0.85, maximum=1.25, invalid_example=3.0, has_invalid_example=True)
_add("appearance.accent_override", "string", "Accent override",
     "Replace the theme's primary colour: an accent swatch id or a #RRGGBB colour. Empty uses the theme's own.",
     None, "cobalt", str | None, nullable=True, validators=(_accent_check,),
     invalid_example="not a colour!", has_invalid_example=True)
_bool("appearance.reduced_motion", "Reduce motion", "Turn off non-essential animation.", False)

# Schedule
_cron("schedule.sweep_cron", "Sweep schedule", "Default schedule for new campaign sweeps (cron, owner's time zone).",
      "0 6 * * *", "0 6,18 * * *")
_enum("schedule.missed_run", "Missed runs",
      "After downtime: run once to catch up, or skip until the next scheduled time.",
      "catch_up_once", "skip", ("catch_up_once", "skip"))
_int("schedule.concurrent_sweeps", "Concurrent sweeps", "How many sweeps may run at the same time.", 1, 2, 1, 4)
_int("schedule.overlap_days", "Sweep overlap",
     "Each incremental sweep searches from the last successful sweep minus this many days.", 2, 3, 0, 14, "days")
_cron("schedule.expiry_check_cron", "Expiry check schedule",
      "When open roles are rechecked for closure.", "0 12 * * *", "0 */6 * * *")
_int("schedule.expiry_check_batch", "Expiry check batch",
     "At most this many open or unconfirmed roles are rechecked in one expiry run (oldest check first).",
     200, 50, 1, 2000, "roles")

# Scoring
_int("scoring.threshold_shortlist", "Shortlist threshold", "Minimum score to shortlist.", 60, 55, 0, 100, "points")
_int("scoring.threshold_tailor", "Tailor threshold", "Minimum score to tailor documents.", 70, 75, 0, 100, "points")
_int("scoring.threshold_auto_apply", "Auto-apply threshold",
     "Minimum score to apply without asking.", 85, 90, 0, 100, "points")
_enum("scoring.unknown_pay", "Unknown pay",
      "What a missing or estimated pay figure does at the filter stage.",
      "pass_blocks_auto", "review", UNKNOWN_POLICIES)
_enum("scoring.unknown_eligibility", "Unknown eligibility",
      "What an unknown work-rights or location eligibility does.", "review", "fail", UNKNOWN_POLICIES)
_enum("scoring.unknown_deadline", "Unknown deadline",
      "What a posting with no stated deadline does (only a passed date excludes a role).",
      "pass_blocks_auto", "review", UNKNOWN_POLICIES)
_int("scoring.backtest_default_jobs", "Backtest sample",
     "How many recent saved roles a backtest scores when you do not pick them.", 50, 100, 1, 500, "roles")
_int("scoring.escalation_margin", "Escalation margin",
     "Re-score with the stronger model when within this many points of a threshold.", 5, 3, 0, 20, "points")
_int("scoring.unknown_penalty", "Unknown-data penalty",
     "Points deducted when the unknown-data policy is 'pass with penalty'.", 10, 5, 0, 50, "points")

# Matching (6, 6.1, 7.1)
_add("matching.dedupe_similarity", "float", "Duplicate similarity",
     "Content similarity above which two postings with the same employer, title and location are one job.",
     0.9, 0.85, float, minimum=0.5, maximum=1.0, invalid_example=1.5, has_invalid_example=True)
_add("matching.recruiter_similarity", "float", "Recruiter posting similarity",
     "Title similarity above which a recruiter posting is flagged as possibly the same vacancy as a direct one.",
     0.8, 0.7, float, minimum=0.5, maximum=1.0, invalid_example=0.1, has_invalid_example=True)
_enum("matching.roles_per_employer_scope", "One role per employer: scope",
      "Which roles at one employer compete so that only the highest-scoring is pursued.",
      "same_department", "whole_employer", ("same_department", "whole_employer", "off"))
_enum("matching.conflict_winner", "One role per employer: winner",
      "How the winner is chosen across campaigns.",
      "highest_score", "campaign_priority_then_score", ("highest_score", "campaign_priority_then_score"))
_int("matching.max_live_per_employer", "Live applications per employer",
     "Maximum applications in flight (applying until an end state) at one employer.", 1, 2, 1, 10)
_int("matching.employer_cooldown_days", "Employer cooldown",
     "Days after an end state (or the applied date, if no reply) before another application to the employer.",
     30, 60, 0, 365, "days")

# Automation (8)
_enum("automation.default_mode", "Default mode", "Automation mode for a new or imported campaign.",
      "prepare", "save_only", AUTOMATION_MODES)
_bool("automation.paused", "Paused", "Global pause: stops every new outward action at once.", False)
_int("automation.daily_cap", "Daily cap", "Maximum applications sent per day.", 5, 3, 0, 100)
_int("automation.weekly_cap", "Weekly cap", "Maximum applications sent per week.", 20, 10, 0, 500)
_add("automation.quiet_hours_start", "time", "Quiet hours start",
     "No outward action starts after this time (owner's time zone).",
     "21:00", "22:30", str, validators=(time_of_day,), invalid_example="25:00", has_invalid_example=True)
_add("automation.quiet_hours_end", "time", "Quiet hours end", "Outward actions may resume at this time.",
     "07:00", "06:00", str, validators=(time_of_day,), invalid_example="7am", has_invalid_example=True)
_int("automation.email_send_delay_minutes", "Email send delay",
     "Emails wait in the outbox this long and can be cancelled.", 10, 30, 0, 1440, "minutes")
_enum("automation.unknown_question", "Unknown form question",
      "What happens when a form asks something the answer bank cannot answer.",
      "ask_and_save", "skip_role", ("ask_and_save", "skip_role"))
_enum("automation.blocker_handling", "CAPTCHA or sign-in",
      "When a runner meets a sign-in or CAPTCHA.",
      "handoff_continue_others", "handoff_stop_runner", ("handoff_continue_others", "handoff_stop_runner"))
_int("automation.follow_up_days", "Follow-up reminder",
     "Remind to follow up this many days after applying with no reply.", 10, 14, 1, 90, "days")
_int("automation.open_check_max_age_hours", "Open-check freshness",
     "A role must have been confirmed open within this many hours to be applied to automatically.",
     24, 12, 1, 168, "hours")
_int("automation.agent_max_steps", "Agent step limit", "Maximum steps an agent task may take.", 80, 120, 5, 500)
_int("automation.permit_valid_minutes", "Submit permit validity",
     "A submit permit is single use and expires this many minutes after it is granted.", 10, 5, 1, 60, "minutes")
_enum("automation.permit_unknown_open", "Posting not confirmed open",
      "At permit time, when the role has not been confirmed open recently: refuse until it is rechecked, or let an "
      "application the owner approved go ahead. Automatic approvals always need a recent check.",
      "refuse", "allow_when_owner_approved", ("refuse", "allow_when_owner_approved"))
_int("automation.dispatch_max_retries", "Send retries",
     "How many times a send that definitely failed before leaving (for example the mailbox refused it) is tried "
     "again, each time with a new permit. An uncertain send is never retried.", 1, 2, 0, 5)
_add("automation.receipt_pay_terms", "list", "Receipt: pay questions",
     "Words that put a form answer under 'pay' on the approval receipt.",
     ["salary", "pay", "compensation", "remuneration", "rate"], ["salary", "expected pay"], list[str],
     validators=(unique_items,), invalid_example=["salary", "salary"], has_invalid_example=True)
_add("automation.receipt_work_rights_terms", "list", "Receipt: work-rights questions",
     "Words that put a form answer under 'work rights' on the approval receipt.",
     ["visa", "sponsor", "right to work", "work permit", "authorised", "authorized", "relocat"],
     ["visa", "work permit"], list[str], validators=(unique_items,), invalid_example=["visa", "visa"],
     has_invalid_example=True)

# Tracking (4, 18.4)
_int("tracking.imminent_deadline_days", "Imminent deadline",
     "A snooze is ignored when a role's deadline or a pending action's deadline is this close.", 3, 5, 0, 30,
     "days")
_int("tracking.stale_pending_days", "Stale pending action",
     "Remind the owner when an open pending action has waited this long.", 3, 7, 1, 90, "days")

# Answer bank (5.4)
_enum("answers.routine_default_scope", "Default scope: routine answers",
      "Scope pre-selected when the owner answers a routine new question.",
      "all_matching", "this_employer", ANSWER_SCOPES)
_enum("answers.material_default_scope", "Default scope: material answers",
      "Scope pre-selected for pay, work rights, relocation and declarations.",
      "this_application", "this_country", ANSWER_SCOPES)
_add("answers.match_similarity", "float", "Question match similarity",
     "Normalised similarity at which a form question matches a stored answer without asking a model.",
     0.85, 0.9, float, minimum=0.5, maximum=1.0, invalid_example=0.2, has_invalid_example=True)

# Reconciliation (8.5)
_int("reconcile.confirmation_wait_hours", "Wait for confirmation",
     "Watch the mailbox this long for a confirmation before asking the owner.", 24, 48, 1, 336, "hours")
_int("reconcile.check_every_minutes", "Reconcile interval",
     "How often an uncertain send is checked again with its channel (sent items, confirmations).",
     15, 30, 1, 1440, "minutes")
_int("reconcile.in_flight_timeout_minutes", "In-flight timeout",
     "A send handed to its channel with no outcome recorded after this long (a worker stopped) becomes "
     "uncertain. It is reconciled, never resent.", 15, 30, 1, 1440, "minutes")

# AI (11)
_enum("ai.provider", "Provider", "Default LLM provider.", "anthropic", "openai_compatible",
      ("anthropic", "openai_compatible", "claude_cli"))
_bool("ai.claude_cli_enabled", "Allow Claude Code CLI",
      "Use the owner's Claude subscription through the CLI on the PC. Never used on a VPS.", False)
_model("ai.model_extract", "Model: extract and normalise", "Extracts structure from postings.",
       "claude-haiku-5-5", "claude-sonnet-5-5")
_model("ai.model_classify_email", "Model: classify email", "Classifies replies.",
       "claude-haiku-5-5", "claude-sonnet-5-5")
_model("ai.model_score", "Model: score", "Scores roles against the rubric.", "claude-haiku-5-5", "claude-sonnet-5-5")
_model("ai.model_score_escalation", "Model: score escalation",
       "Re-scores roles near a threshold.", "claude-sonnet-5-5", "claude-opus-5-5")
_model("ai.model_custom_facet", "Model: custom facets", "Answers the owner's yes/no questions per job.",
       "claude-haiku-5-5", "claude-sonnet-5-5")
_model("ai.model_tailor", "Model: tailor", "Writes CVs, letters and requirement matches.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_model("ai.model_claim_check", "Model: unsupported-claim check", "Second-pass truth check.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_model("ai.model_browser_agent", "Model: server browser agent", "Drives the optional server runner.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_int("ai.max_output_tokens", "Output token limit",
     "Most tokens a model may write in one call (bounds each call's reserved cost).",
     8192, 4096, 256, 128_000, "tokens")
_int("ai.request_timeout_seconds", "Request timeout", "Give up on one model call after this long.",
     120, 60, 5, 1800, "seconds")
_int("ai.max_retries", "Retries", "Retries after a failed or invalid model reply. Each attempt is budgeted.",
     2, 3, 0, 6)
_int("ai.route_test_valid_minutes", "Route test validity",
     "A model route can be activated only after a successful test within this window.", 60, 240, 1, 10_080, "minutes")

# Budget (13)
_add("budget.currency", "currency", "Budget currency", "Currency of the spend ledger.",
     "USD", "EUR", str, validators=(currency_code,), invalid_example="dollars", has_invalid_example=True)
_int("budget.monthly_cap_minor", "Monthly cap",
     "Monthly spend cap in minor units. Unset means paid work stays off.", None, 2000, 0, 10_000_000,
     "minor units", nullable=True)
_int("budget.per_run_cap_minor", "Per-run cap", "Spend cap per run in minor units. Unset means no per-run cap.",
     None, 200, 0, 10_000_000, "minor units", nullable=True)
_int("budget.monthly_cap_micros", "Monthly cap (micro-units)",
     "Monthly cap in millionths of the major unit; when set it wins over the minor-unit cap, which is kept in "
     "step (rounded).", None, 20_000_000, 0, 100_000_000_000, "micros", nullable=True)
_int("budget.per_run_cap_micros", "Per-run cap (micro-units)",
     "Per-run cap in millionths of the major unit; when set it wins over the minor-unit cap.",
     None, 2_000_000, 0, 100_000_000_000, "micros", nullable=True)
_int("budget.warning_percent", "Warning", "Warn when month-to-date spend passes this share of the cap.",
     80, 90, 1, 100, "%")
_int("budget.agent_task_ceiling_minor", "Agent task ceiling", "Maximum spend for one agent task, in minor units.",
     100, 250, 1, 100_000, "minor units")
_int("budget.reservation_stale_minutes", "Reservation expiry",
     "An unreconciled reservation older than this is closed and charged at its estimate.", 30, 60, 1, 1440, "minutes")

# Documents (9)
_int("documents.cv_pages", "CV pages", "Maximum CV length.", 2, 3, 1, 6, "pages")
_int("documents.vault_max_upload_mb", "Vault upload limit", "Largest file the vault accepts.", 25, 10, 1, 200,
     "MB")
_int("documents.letter_pages", "Letter pages", "Maximum cover letter length.", 1, 2, 1, 3, "pages")
_int("documents.letter_paragraphs", "Letter paragraphs", "Maximum cover letter paragraphs.", 4, 5, 1, 10)
_add("documents.cv_template", "string", "CV template", "Default CV template (by template key).",
     "classic", "modern", str, validators=(slug,), invalid_example="Not A Key", has_invalid_example=True)

# Retention (14)
_int("retention.below_threshold_text_days", "Below-threshold text",
     "Drop full posting text of below-threshold roles after this many days.", 30, 14, 1, 3650, "days")
_int("retention.unsubmitted_archive_days", "Archive unsubmitted roles",
     "Archive roles never applied to after this many days.", 60, 90, 1, 3650, "days")

# Backups (14)
_cron("backups.cron", "Backup schedule", "When the nightly backup runs.", "0 2 * * *", "30 3 * * *")
_int("backups.keep", "Copies kept", "Number of backups kept.", 14, 30, 1, 365)
_enum("backups.target", "Backup target", "Where backups are written.", "local", "s3", ("local", "s3", "gdrive"))

# Notifications
_enum("notifications.digest", "Digest", "When the digest is sent.",
      "after_daily_sweep", "off", ("after_daily_sweep", "morning", "off"))
_add("notifications.channels", "list", "Channels",
     "Where notifications go. Empty until a channel is connected.",
     [], ["telegram"], list[str], choices=NOTIFICATION_CHANNELS, validators=(unique_items,),
     invalid_example=["pigeon"], has_invalid_example=True)

# Runners (8.3)
_bool("runners.server_runner_enabled", "Server runner",
      "Run the optional server browser runner. It costs API tokens.", False)
_int("runners.stale_after_minutes", "Runner offline after",
     "Show a runner as offline when not seen for this long.", 15, 30, 1, 1440, "minutes")


REGISTRY: dict[str, SettingDef] = {d.key: d for d in _DEFS}
if len(REGISTRY) != len(_DEFS):  # pragma: no cover - guards against copy-paste errors
    raise RuntimeError("duplicate setting key in registry")


def get_def(key: str) -> SettingDef:
    try:
        return REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unknown setting: {key}") from exc


def cross_check(values: dict[str, Any]) -> None:
    """Rules that span several settings. ``values`` is the full effective map after a change."""
    s, t, a = (
        values["scoring.threshold_shortlist"],
        values["scoring.threshold_tailor"],
        values["scoring.threshold_auto_apply"],
    )
    if not (s <= t <= a):
        raise SettingValueError("thresholds must satisfy shortlist <= tailor <= auto-apply")
    if values["automation.daily_cap"] > values["automation.weekly_cap"]:
        raise SettingValueError("the daily cap cannot exceed the weekly cap")
