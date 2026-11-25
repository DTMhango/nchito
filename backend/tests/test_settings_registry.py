"""Generated from the registry: every setting validates at its default and at one other value,
rejects its invalid example, and can be stored, versioned and audited."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.settings import service
from app.core.settings.registry import GROUPS, REGISTRY, cross_check, get_def
from app.core.settings.types import SettingValueError
from app.models.platform import AuditEvent, SettingRevision

KEYS = sorted(REGISTRY)

# Section 16 catalogue plus 6.1, 7.1, 8, 18 additions that must exist.
REQUIRED = {
    "general.app_name", "general.timezone", "general.display_currency",
    "schedule.sweep_cron", "schedule.missed_run", "schedule.concurrent_sweeps", "schedule.overlap_days",
    "scoring.threshold_shortlist", "scoring.threshold_tailor", "scoring.threshold_auto_apply",
    "scoring.unknown_pay", "scoring.unknown_eligibility",
    "automation.default_mode", "automation.daily_cap", "automation.weekly_cap",
    "automation.quiet_hours_start", "automation.quiet_hours_end", "matching.employer_cooldown_days",
    "automation.email_send_delay_minutes", "matching.roles_per_employer_scope",
    "matching.max_live_per_employer", "matching.conflict_winner", "automation.unknown_question",
    "automation.blocker_handling", "automation.follow_up_days", "ai.provider", "ai.model_score",
    "budget.monthly_cap_minor", "budget.per_run_cap_minor", "budget.warning_percent",
    "documents.cv_pages", "documents.letter_pages", "documents.letter_paragraphs", "documents.cv_template",
    "retention.below_threshold_text_days", "retention.unsubmitted_archive_days",
    "reconcile.confirmation_wait_hours", "backups.cron", "backups.keep", "notifications.digest",
    "notifications.channels", "appearance.theme_id", "appearance.mode", "appearance.density",
    "answers.routine_default_scope", "answers.material_default_scope", "automation.agent_max_steps",
    "budget.agent_task_ceiling_minor", "automation.paused",
}


@pytest.mark.nodb
def test_catalogue_complete():
    assert set(REGISTRY) >= REQUIRED, sorted(REQUIRED - set(REGISTRY))


@pytest.mark.nodb
@pytest.mark.parametrize("key", KEYS)
def test_definition_is_complete(key):
    d = get_def(key)
    assert d.group in GROUPS
    assert d.label and d.description
    assert d.has_invalid_example, f"{key}: give it an invalid_example"


@pytest.mark.nodb
@pytest.mark.parametrize("key", KEYS)
def test_default_is_valid(key):
    d = get_def(key)
    assert d.coerce(d.effective_default()) == d.effective_default()


@pytest.mark.nodb
@pytest.mark.parametrize("key", KEYS)
def test_other_value_is_valid_and_different(key):
    d = get_def(key)
    assert d.example != d.effective_default()
    assert d.coerce(d.example) == d.example


@pytest.mark.nodb
@pytest.mark.parametrize("key", KEYS)
def test_invalid_value_rejected(key):
    d = get_def(key)
    with pytest.raises(SettingValueError):
        d.coerce(d.invalid_example)


@pytest.mark.nodb
def test_defaults_pass_cross_checks():
    cross_check({k: d.effective_default() for k, d in REGISTRY.items()})


@pytest.mark.nodb
def test_no_defaults_for_personal_criteria():
    """Pay floors, countries, seniority, visa and relocation answers come from the Kit only."""
    forbidden = ("pay_floor", "country", "seniority", "visa", "relocation", "salary")
    assert not [k for k in REGISTRY if any(f in k for f in forbidden)]


@pytest.mark.nodb
def test_app_name_default_comes_from_env(monkeypatch):
    from app.core.config import get_config

    monkeypatch.setenv("APP_NAME", "Kazi")
    get_config.cache_clear()
    try:
        assert get_def("general.app_name").effective_default() == "Kazi"
    finally:
        monkeypatch.delenv("APP_NAME")
        get_config.cache_clear()


@pytest.mark.parametrize("key", KEYS)
async def test_store_example_value(key, session):
    d = get_def(key)
    state = await service.set_value(session, key, d.example, actor="owner", reason="test")
    assert state.value == d.example
    assert state.version == 1
    assert not state.is_default
    assert await service.get_value(session, key) == d.example

    back = await service.set_value(session, key, d.effective_default(), actor="owner")
    assert back.version == 2 and back.is_default

    revs = (await session.scalars(select(SettingRevision).where(SettingRevision.key == key)
                                  .order_by(SettingRevision.version))).all()
    assert [(r.old_value, r.new_value) for r in revs] == [
        (d.effective_default(), d.example), (d.example, d.effective_default())]
    audits = (await session.scalars(select(AuditEvent).where(AuditEvent.subject_id == key))).all()
    assert len(audits) == 2 and all(a.action == "setting.changed" for a in audits)
