"""Shared builders for the matching tests (invented data only)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.settings.registry import REGISTRY
from app.pipeline.decisions import DecisionInput

NOW = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)  # 12:00 in Lusaka: outside default quiet hours


def default_settings(**overrides: Any) -> dict[str, Any]:
    values = {key: d.effective_default() for key, d in REGISTRY.items()}
    values.update({k.replace("__", "."): v for k, v in overrides.items()})
    return values


def job(**over: Any) -> dict[str, Any]:
    """A fully stated, open, eligible job record."""
    base: dict[str, Any] = {
        "id": "job-1", "title": "Data Analyst", "employer": "Acme Example", "function": "analytics",
        "level": "senior", "tags": [], "custom": {},
        "facets": {"work_model": "remote", "remote_scope": "worldwide", "work_rights": "sponsorship_possible",
                   "employment_type": "permanent", "relocation_required": "no", "visa_sponsorship": "yes",
                   "required_skills": ["Python", "SQL"], "years_experience": 5, "remote_regions": []},
        "location": {"country": "Zambia", "region": None, "city": "Lusaka", "raw": "Lusaka"},
        "pay_state": "stated",
        "pay": {"min_minor": 50_000_00, "max_minor": 60_000_00, "currency": "USD", "period": "year"},
        "pay_estimate": None,
        "deadline_state": "dated", "deadline": date(2026, 12, 31),
        "availability": "open", "last_checked_at": NOW - timedelta(hours=1),
        "always_ask_first": False,
    }
    for key, value in over.items():
        if key == "facets":
            base["facets"] = {**base["facets"], **value}
        else:
            base[key] = value
    return base


def campaign(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "camp-1", "name": "Analytics", "status": "active", "review_state": "confirmed", "confirmed": True,
        "priority": 0, "criteria": {"pay_floors": [{"employment_type": "permanent", "amount_minor": 40_000_00,
                                                    "currency": "USD", "period": "year"}]},
        "unknown_data_policy": {}, "automation": {"mode": "auto_apply"}, "work_rights": ["Zambia"],
        "version": "2026-11-01T00:00:00+00:00",
    }
    base.update(over)
    return base


def counters(**over: int) -> dict[str, int]:
    return {"sent_today": 0, "sent_week": 0, "employer_live": 0, **over}


def data(*, job_rec: dict[str, Any] | None = None, camp: dict[str, Any] | None = None, score: int | None = 95,
         settings: dict[str, Any] | None = None, conflict_state: str = "winner", **kw: Any) -> DecisionInput:
    return DecisionInput(purpose=kw.pop("purpose", "discovery"), now=NOW, job=job_rec or job(),
                         campaign=camp or campaign(), settings=settings or default_settings(), score=score,
                         rubric_version=1, conflict_state=conflict_state,  # type: ignore[arg-type]
                         counters=kw.pop("counters", counters()), **kw)
