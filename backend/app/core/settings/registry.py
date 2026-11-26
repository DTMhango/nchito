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
import string
from collections.abc import Callable
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
    "mail": "Mail",
    "ai": "AI",
    "budget": "Budget",
    "documents": "Documents",
    "tailoring": "Tailoring and checks",
    "interview": "Interview pack",
    "retention": "Retention",
    "backups": "Backups",
    "notifications": "Notifications",
    "health": "Health",
    "runners": "Runners",
    "data": "Data import and export",
    "sources": "Discovery sources",
}

AUTOMATION_MODES = ("save_only", "prepare", "ask_then_apply", "auto_apply")
UNKNOWN_POLICIES = ("review", "pass_with_penalty", "pass_blocks_auto", "fail")
ANSWER_SCOPES = ("this_application", "this_employer", "this_country", "all_matching")
NOTIFICATION_CHANNELS = ("telegram", "email", "webhook")
# Notification kinds the owner can switch on or off (the digest is governed by notifications.digest).
NOTIFIABLE_KINDS = ("pending_action", "pending_action_stale", "application_sent", "reply_received", "run_failed",
                    "budget", "health", "backup")
TITLE_FIELDS = frozenset({"title", "app_name", "date", "count"})

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


def _title_template(allowed: frozenset[str]) -> Callable[[Any], None]:
    """A wording template may use only the named ``{fields}`` and must not be empty."""

    def check(value: Any) -> None:
        non_empty(value)
        try:
            fields = {name for _, name, _, _ in string.Formatter().parse(str(value)) if name is not None}
        except ValueError as exc:
            raise SettingValueError(f"not a valid template: {exc}") from exc
        unknown = fields - allowed
        if unknown:
            raise SettingValueError(f"unknown field(s) {sorted(unknown)}; allowed: {sorted(allowed)}")

    return check


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
_add("automation.email_subject_template", "string", "Application email subject",
     "Subject of an application sent by email. Fields: {role}, {employer}, {requisition}.",
     "Application: {role}", "{role} application ({requisition})", str,
     validators=(_title_template(frozenset({"role", "employer", "requisition"})), max_length(200)),
     invalid_example="Application: {salary}", has_invalid_example=True)
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

# Mail (8.5, 12)
MAIL_AUTO_CLASSES = ("confirmation", "rejection", "interview")
_int("mail.check_interval_minutes", "Mailbox check interval",
     "How often each connected mailbox is read for replies.", 10, 30, 1, 1440, "minutes")
_int("mail.initial_lookback_days", "First check lookback",
     "How far back the first check of a new mailbox (or alert source) reads.", 14, 30, 1, 365, "days")
_int("mail.max_messages_per_check", "Messages per check",
     "Most messages read from a mailbox in one check.", 200, 50, 1, 1000)
_add("mail.auto_link_confidence", "float", "Link replies automatically at",
     "A reply matched to an application at or above this confidence is linked; below it goes to review.",
     0.8, 0.9, float, minimum=0.5, maximum=1.0, invalid_example=0.1, has_invalid_example=True)
_add("mail.auto_apply_classes", "list", "Apply stage changes from mail",
     "Reply kinds whose stage change is applied without asking. Empty: every change waits for the owner.",
     [], ["confirmation"], list[str], choices=MAIL_AUTO_CLASSES, validators=(unique_items,),
     invalid_example=["offer"], has_invalid_example=True)
_bool("mail.llm_classify", "Use AI for unclear replies",
      "When the plain rules cannot tell what a reply is, ask the classify-email model (budgeted).", True)
_int("mail.llm_body_max_chars", "Reply text sent to AI",
     "Longest part of a reply's text given to the model, as untrusted data.", 6000, 3000, 500, 50_000, "characters")

def _patterns_check(value: Any) -> None:
    for item in value:
        if not str(item).strip():
            raise SettingValueError("phrases cannot be blank")
        try:
            re.compile(str(item))
        except re.error as exc:
            raise SettingValueError(f"{item!r} is not a valid pattern: {exc}") from exc


def _phrases(key: str, label: str, description: str, default: list[str], example: list[str]) -> None:
    _add(key, "list", label, description + " Each entry is a case-insensitive regular expression.", default, example,
         list[str], validators=(unique_items, _patterns_check), invalid_example=["(unclosed"],
         has_invalid_example=True)


_phrases("mail.rejection_phrases", "Rejection wording", "Wording that marks a reply as a rejection.", [
    r"\bunfortunately\b", r"regret to (inform|tell|let)", r"not (been )?(selected|successful|shortlisted)",
    r"(will|would) not be (moving|proceeding|progressing) (forward|further|with)",
    r"decided to (move|go|proceed) (forward )?with (other|another|different)", r"pursue (other|another) candidate",
    r"position (has been|is now) filled", r"your application was unsuccessful",
    r"not (be )?(taking|moving) .{0,30}forward"], [r"\bunfortunately\b"])
_phrases("mail.interview_phrases", "Interview wording", "Wording that marks a reply as an interview invitation.", [
    r"invit\w+ you to (an? |a )?(\w+ )?interview", r"interview (invitation|invite|request)",
    r"(schedule|arrange|set up|book) (an? |your |a )?(\w+ )?(interview|call|phone screen|chat|meeting)",
    r"(would|like) to (speak|talk|meet) with you", r"calendly\.com", r"your availability (for|this|next)",
    r"available for (an? )?(interview|call|chat)"], [r"interview (invitation|invite)"])
_phrases("mail.info_request_phrases", "Information request wording",
         "Wording that marks a reply as a request for more information or documents.", [
             r"(please|kindly) (provide|send|share|submit|upload|attach|supply)\b",
             r"could you (please )?(provide|send|share|submit)",
             r"we (still )?need (some |the |your )?(additional |further |more )?"
             r"(information|documents|details|certificates)",
             r"(additional|further|missing) (information|documents|details) (is|are)? ?(required|needed)"],
         [r"please (provide|send)"])
_phrases("mail.confirmation_phrases", "Acknowledgement wording",
         "Wording that marks a reply as a confirmation that the application arrived.", [
             r"(thank you|thanks) for (applying|your application|your interest|submitting)",
             r"we (have |'ve )?(successfully )?received your (application|cv|resume)",
             r"your application (has been |was )?(successfully )?(received|submitted|sent)",
             r"application (received|confirmation)",
             r"successfully (applied|submitted)"], [r"thank you for applying"])
_phrases("mail.auto_reply_phrases", "Automatic reply wording", "Wording of out-of-office and automatic replies.",
         [r"out of (the )?office", r"automatic reply", r"auto-?reply", r"away from (my|the) (desk|office)"],
         [r"out of (the )?office"])
_phrases("mail.bounce_subject_phrases", "Delivery failure subjects", "Subjects of delivery failure notices.",
         [r"delivery status notification", r"undeliverable", r"delivery (has )?failed",
          r"mail delivery (failed|subsystem)", r"returned mail", r"could not be delivered"], [r"undeliverable"])
_add("mail.bounce_senders", "list", "Delivery failure senders",
     "Sender names (the part before @) that send delivery failure notices.", ["mailer-daemon", "postmaster"],
     ["mailer-daemon"], list[str], validators=(unique_items, _patterns_check),
     invalid_example=["mailer-daemon", "mailer-daemon"], has_invalid_example=True)

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
_add("documents.letter_template", "string", "Letter template", "Default cover letter template (by template key).",
     "letter-plain", "letter-formal", str, validators=(slug,), invalid_example="Not A Key", has_invalid_example=True)
_add("documents.letter_salutation", "string", "Letter salutation",
     "Opening line when the letter has no named recipient.", "Dear Hiring Manager,", "Dear Hiring Team,", str,
     validators=(non_empty, max_length(80)), invalid_example="", has_invalid_example=True)
_add("documents.letter_signoff", "string", "Letter sign-off", "Closing line before the name.",
     "Kind regards,", "Yours sincerely,", str, validators=(non_empty, max_length(80)), invalid_example="",
     has_invalid_example=True)

# Tailoring and checks (9, 18.5)
def _terms(key: str, label: str, description: str, default: list[str], example: list[str]) -> None:
    _add(key, "list", label, description, default, example, list[str], validators=(unique_items, _no_blank_items),
         invalid_example=["led", "led"], has_invalid_example=True)


def _no_blank_items(value: Any) -> None:
    if any(not str(v).strip() for v in value):
        raise SettingValueError("terms cannot be blank")


_int("tailoring.max_facts", "Facts sent per draft",
     "Most Kit facts selected for one tailored draft (lead facts first, then the best keyword matches).",
     60, 40, 5, 500, "facts")
_bool("tailoring.claim_check_enabled", "Model claim check",
      "After the code checks, a second model pass looks for unsupported claims. It can only add warnings or "
      "blocks; it never clears a code check.", True)
_enum("tailoring.claim_check_severity", "Model claim check result",
      "What a sentence flagged by the model claim check does.", "warn", "block", ("warn", "block"))
_terms("tailoring.ownership_weak_terms", "Supporting-role wording",
       "Wording that marks a supporting role in a fact. A draft that turns it into leading wording is claim drift.",
       ["contributed to", "supported", "assisted", "helped", "participated in", "worked on", "part of"],
       ["contributed to", "supported"])
_terms("tailoring.ownership_strong_terms", "Leading-role wording",
       "Wording that claims ownership. Allowed only when a cited fact uses leading wording too.",
       ["led", "owned", "headed", "directed", "spearheaded", "drove", "managed", "ran", "founded"],
       ["led", "owned"])
_terms("tailoring.scope_terms", "Scope wording",
       "Wording that widens scope. A draft may use it only when a cited fact does.",
       ["company-wide", "organisation-wide", "organization-wide", "group-wide", "enterprise-wide", "global",
        "globally", "worldwide", "nationwide", "across the business"],
       ["global", "company-wide"])
_terms("tailoring.period_terms", "Period wording",
       "Wording that states a period for a figure. A draft may use it only when a cited fact does.",
       ["per month", "monthly", "per year", "annually", "per annum", "a year", "a month", "per week", "weekly",
        "per quarter", "quarterly", "per day", "daily"],
       ["per month", "per year"])
_terms("tailoring.qualification_terms", "Qualification words",
       "Words that name a degree, certificate or membership. A draft may use one only when a cited fact does.",
       ["bachelor", "bsc", "b.sc", "master", "masters", "msc", "m.sc", "mba", "phd", "doctorate", "diploma",
        "certificate", "certified", "certification", "chartered", "acca", "cima", "cfa", "cpa", "frm", "pmp",
        "fellow"],
       ["mba", "phd", "cfa"])

# Interview pack (10.3a)
INTERVIEW_SECTIONS = ("role_brief", "why_you", "questions", "stories", "questions_to_ask", "gaps", "pay_sheet",
                      "crib_sheet")
INTERVIEW_TRIGGERS = ("off", "invite_or_stage", "stage_only")


def _topic_lines(value: Any) -> None:
    for item in value:
        topic, _, question = str(item).partition("|")
        if not topic.strip() or not question.strip():
            raise SettingValueError(f"{item!r}: write 'Topic|Question the employer may ask'")


_enum("interview.auto_offer", "Offer a pack when",
      "When to offer an interview pack: when a reply is classified as an interview invitation or the stage moves "
      "to interview, only when the stage moves, or never (build it from the job page).", "invite_or_stage",
      "stage_only", INTERVIEW_TRIGGERS)
_bool("interview.auto_generate", "Build offered packs straight away",
      "Off: an offer waits on Today for your yes. On: the pack is generated at once (budgeted).", False)
_add("interview.sections", "list", "Pack sections",
     "Which sections a pack has, in this order. The crib sheet is built from the others.",
     list(INTERVIEW_SECTIONS), ["role_brief", "questions", "stories", "pay_sheet", "crib_sheet"], list[str],
     choices=INTERVIEW_SECTIONS, validators=(unique_items, non_empty), invalid_example=["company_news"],
     has_invalid_example=True)
_model("interview.model_role_brief", "Model: role brief", "Reads the posting for the role brief.",
       "claude-sonnet-5-5", "claude-haiku-5-5")
_model("interview.model_why_you", "Model: why you", "Writes the talking points from approved facts.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_model("interview.model_questions", "Model: likely questions", "Writes likely questions and suggested answers.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_model("interview.model_stories", "Model: story bank", "Builds STAR stories from approved facts.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_model("interview.model_questions_to_ask", "Model: questions to ask", "Suggests questions to ask the employer.",
       "claude-haiku-5-5", "claude-sonnet-5-5")
_model("interview.model_gaps", "Model: gaps", "Finds gaps and honest ways to address them.",
       "claude-sonnet-5-5", "claude-opus-5-5")
_model("interview.model_practice", "Model: practice feedback", "Gives feedback on a practice answer.",
       "claude-sonnet-5-5", "claude-haiku-5-5")
_int("interview.questions_per_category", "Questions per category",
     "Most likely questions in each category (behavioural, technical, role, motivation, logistics).",
     5, 3, 1, 15, "questions")
_int("interview.max_stories", "Stories in the bank", "Most STAR stories in the story bank.", 6, 4, 1, 20,
     "stories")
_int("interview.regenerate_attempts", "Retries after a failed truth check",
     "How many times a section that fails fact tracing is regenerated before it is shown flagged.", 1, 2, 0, 3)
_int("interview.practice_answer_max_chars", "Practice answer length", "Longest practice answer accepted.",
     4000, 2000, 200, 20_000, "characters")
_add("interview.pay_topics", "list", "Pay and logistics topics",
     "One line per topic on the pay and logistics sheet, as 'Topic|Question'. The question is matched against "
     "your confirmed answers and the answers you gave on the form.",
     ["Salary expectation|What are your salary expectations?", "Notice period|What is your notice period?",
      "Right to work|Do you have the right to work in this country?",
      "Relocation|Are you willing to relocate?", "Start date|When can you start?"],
     ["Salary expectation|What are your salary expectations?"], list[str],
     validators=(unique_items, _topic_lines), invalid_example=["no separator"], has_invalid_example=True)
_add("interview.decide_wording", "string", "Undecided wording",
     "What the pay sheet says where no confirmed answer exists.", "Decide before the interview",
     "Settle this before the call", str, validators=(non_empty, max_length(120)), invalid_example="",
     has_invalid_example=True)
_add("interview.research_note", "string", "Research note",
     "Shown on the role brief: where company notes come from.",
     "No web research was done: company notes come only from the posting and your own notes.",
     "Company notes are from the posting and your notes only.", str, validators=(non_empty, max_length(300)),
     invalid_example="", has_invalid_example=True)

# Retention (14)
_int("retention.below_threshold_text_days", "Below-threshold text",
     "Drop full posting text of below-threshold roles after this many days.", 30, 14, 1, 3650, "days")
_int("retention.unsubmitted_archive_days", "Archive unsubmitted roles",
     "Archive roles never applied to after this many days.", 60, 90, 1, 3650, "days")
_cron("retention.cron", "Retention schedule", "When the retention job runs.", "30 4 * * *", "0 5 * * 0")
_int("retention.notifications_days", "Keep notifications",
     "Delete notifications older than this many days. Applications, the audit and duplicate-protection "
     "history are never deleted.", 90, 30, 7, 3650, "days")
_int("retention.temp_files_days", "Keep temporary files",
     "Delete files in the temporary folder older than this many days. Submitted snapshots and the vault are "
     "never touched.", 7, 1, 1, 365, "days")

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
_add("notifications.events", "list", "Events that notify",
     "Which kinds of event send a message to the channels. The digest has its own setting.",
     ["pending_action", "pending_action_stale", "reply_received", "run_failed", "budget", "health", "backup"],
     ["pending_action"], list[str], choices=NOTIFIABLE_KINDS, validators=(unique_items,),
     invalid_example=["everything"], has_invalid_example=True)
_bool("notifications.quiet_hours_enabled", "Notification quiet hours",
      "Hold messages during quiet hours and send them when quiet hours end.", True)
_add("notifications.quiet_hours_start", "time", "Notification quiet hours start",
     "No message is sent after this time (owner's time zone).",
     "21:00", "22:30", str, validators=(time_of_day,), invalid_example="25:00", has_invalid_example=True)
_add("notifications.quiet_hours_end", "time", "Notification quiet hours end",
     "Held messages are sent from this time.",
     "07:00", "06:00", str, validators=(time_of_day,), invalid_example="7am", has_invalid_example=True)
_enum("notifications.detail_level", "Message detail",
      "titles: role and employer names appear in messages. generic: messages only say that something needs you.",
      "titles", "generic", ("titles", "generic"))
_add("notifications.needs_you_title", "string", "Wording: needs you",
     "Title of a message about something waiting for you. Fields: {title}, {app_name}, {date}, {count}.",
     "Needs you: {title}", "{app_name}: {title}", str, validators=(_title_template(TITLE_FIELDS), max_length(120)),
     invalid_example="Needs you: {nonsense}", has_invalid_example=True)
_add("notifications.alert_title", "string", "Wording: other alerts",
     "Title of replies, failures, budget and health messages. Fields: {title}, {app_name}, {date}, {count}.",
     "{title}", "{app_name}: {title}", str, validators=(_title_template(TITLE_FIELDS), max_length(120)),
     invalid_example="{missing", has_invalid_example=True)
_add("notifications.digest_title", "string", "Wording: digest title",
     "Title of the digest. Fields: {app_name}, {date}, {count}.",
     "{app_name} digest for {date}", "Daily summary, {date}", str,
     validators=(_title_template(frozenset({"app_name", "date", "count"})), max_length(120)),
     invalid_example="Digest {title}", has_invalid_example=True)
_add("notifications.digest_time", "time", "Morning digest time",
     "When the digest is sent if the digest setting is 'morning' (owner's time zone).",
     "07:30", "08:15", str, validators=(time_of_day,), invalid_example="7.30", has_invalid_example=True)
_bool("notifications.digest_skip_empty", "Skip an empty digest",
      "Send no digest on a day with nothing to report.", True)
_int("notifications.digest_max_items", "Digest list length", "Most roles or actions listed per digest section.",
     5, 10, 1, 25)
_int("notifications.lookback_hours", "Notification look-back",
     "Only events newer than this are sent, so enabling a channel does not flood it with old items.",
     48, 24, 1, 720, "hours")
_int("notifications.retry_attempts", "Delivery attempts", "Give up on a message after this many failed attempts.",
     3, 5, 1, 20)
_int("notifications.retry_minutes", "Retry wait",
     "Wait this long before the second attempt; each further wait doubles.", 10, 5, 1, 1440, "minutes")

# Health
_int("health.sweep_stale_hours", "Sweep overdue after",
     "Raise an alert when no sweep has succeeded for this long.", 36, 72, 1, 720, "hours")
_int("health.backup_stale_hours", "Backup overdue after",
     "Raise an alert when no backup has succeeded for this long.", 36, 72, 1, 720, "hours")
_int("health.disk_min_free_mb", "Low disk space", "Raise an alert when the files volume has less free space.",
     500, 2000, 10, 10_000_000, "MB")

# Runners (8.3)
_bool("runners.server_runner_enabled", "Server runner",
      "Run the optional server browser runner. It costs API tokens.", False)
_int("runners.stale_after_minutes", "Runner offline after",
     "Show a runner as offline when not seen for this long.", 15, 30, 1, 1440, "minutes")

# Data import and export (kit-io)
_int("data.import_max_zip_mb", "Largest upload", "Refuse an uploaded kit or old-kit zip larger than this.",
     50, 20, 1, 500, "MB")
_int("data.import_max_file_mb", "Largest file in a zip", "Refuse a zip holding a file larger than this once unpacked.",
     25, 10, 1, 200, "MB")
_int("data.import_max_files", "Most files in a zip", "Refuse a zip with more files than this.", 500, 100, 1, 5000)
_int("data.export_link_minutes", "Export link lifetime", "How long a prepared export stays downloadable.",
     60, 15, 1, 1440, "minutes")
_int("data.import_staging_hours", "Import preview lifetime",
     "How long a previewed import waits for confirmation before it is discarded.", 24, 48, 1, 168, "hours")
_bool("data.old_kit_ai_extraction", "AI for unrecognised old-kit files",
      "Send old-kit files the built-in parser does not recognise to your chosen AI provider, as data, to propose "
      "facts. Off means only the built-in parser runs.", False)

# Discovery sources: JobSpy, careers pages, web search (DESIGN 6). A source row's own config may override each of
# these per source (same last word of the key, e.g. ``results_per_board``).
JOBSPY_BOARDS = ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter")


def _query_template_check(value: Any) -> None:
    text = str(value)
    if "{title}" not in text:
        raise SettingValueError("the template must contain {title}")
    try:
        string.Formatter().vformat(text, (), {"title": "x", "location": "y"})
    except (KeyError, IndexError, ValueError) as exc:
        raise SettingValueError("only {title} and {location} may be used") from exc


_bool("sources.jobspy.enabled", "JobSpy boards",
      "Let JobSpy search the scraped job boards (LinkedIn, Indeed, Glassdoor, Google Jobs). Off by default: "
      "datacentre IPs get blocked and the boards forbid automated reading. Discovery only, never applying.", False)
_add("sources.jobspy.boards", "list", "JobSpy boards searched", "Which boards JobSpy reads when it is enabled.",
     ["indeed", "google"], ["linkedin"], list[str], choices=JOBSPY_BOARDS, validators=(unique_items,),
     invalid_example=["myspace"], has_invalid_example=True)
_int("sources.jobspy.results_per_board", "JobSpy results per board and query",
     "Most postings requested from one board for one search phrase.", 20, 50, 1, 100, "postings")
_int("sources.jobspy.board_delay_seconds", "JobSpy pause between requests",
     "Wait this long between two board searches so the boards are not hammered.", 8, 15, 0, 300, "seconds")
_int("sources.jobspy.max_age_hours", "JobSpy oldest posting",
     "Ask the boards only for postings newer than this (the sweep window can only narrow it).",
     72, 168, 1, 720, "hours")
_bool("sources.jobspy.verify_links", "JobSpy link check",
      "Open every found link to confirm the posting is real and live before it enters the pipeline. A blocked page "
      "stays, marked unverified.", True)
_int("sources.careers.max_postings", "Careers page postings per employer",
     "Most postings read from one employer's careers page in one sweep.", 100, 40, 1, 500, "postings")
_int("sources.careers.max_detail_pages", "Careers page detail pages",
     "Most individual posting pages opened per employer in one sweep (listing links and sitemap entries).",
     40, 20, 1, 200, "pages")
_bool("sources.careers.llm_extraction", "Model reading of careers pages",
      "When no structured data or listing pattern is found, a model reads the listing page (as data) to name the "
      "posting links. Costs API tokens, within the budget caps.", False)
_int("sources.careers.llm_max_cost_micros", "Model reading cost cap per page",
     "A page whose model read would cost more than this (millionths of the budget currency) is skipped.",
     50_000, 20_000, 1_000, 5_000_000, "micros")
_int("sources.search.max_queries", "Web search queries per sweep",
     "Most search phrases sent to the search provider in one sweep.", 5, 3, 1, 20, "queries")
_int("sources.search.results_per_query", "Web search results per query",
     "Most results taken from one search.", 10, 5, 1, 50, "results")
_int("sources.search.max_leads", "Web search leads opened per sweep",
     "Most result pages fetched and checked for a real posting in one sweep.", 30, 15, 1, 200, "pages")
_add("sources.search.query_template", "string", "Web search phrase",
     "How a campaign title and location become a search phrase. Fields: {title}, {location}.",
     "{title} {location} job vacancy apply", "{title} careers {location}", str,
     validators=(_query_template_check, max_length(200)), invalid_example="jobs for {role}",
     has_invalid_example=True)


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
