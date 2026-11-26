"""Dry-run proposals: what a real run would do with the roles it just scored (DESIGN.md 7, 8).

The proposals come from the one decision table (``decisions.decide`` with purpose ``dry_run``),
so a dry run and a real run cannot disagree. Roles are taken best score first; each simulated
automatic application counts against the daily and weekly caps and the per-employer live limit,
so the list shows where a real run would stop. The conflict-group winner comes from the job's
``conflict_state`` (a held role is never proposed for applying). Nothing here writes anything.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application
from app.models.search import Assessment, AssessmentState, Campaign
from app.pipeline import conflicts, scoring
from app.pipeline.decisions import decide
from app.pipeline.filters import campaign_record, load_records

ACTION_BY_VERDICT = {"auto_apply": "apply", "ask_owner": "ask_owner", "tailor": "prepare",
                     "shortlist": "add_to_matches", "review": "review", "below_threshold": "skip",
                     "excluded": "skip"}


async def sent_counters(session: AsyncSession, now: datetime, tz_name: str) -> dict[str, int]:
    """Applications sent today and this week (Monday start), in the owner's time zone."""
    local = now.astimezone(ZoneInfo(tz_name))
    day_start = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
    week_start = day_start - timedelta(days=local.weekday())

    async def since(start: datetime) -> int:
        return int(await session.scalar(select(func.count()).select_from(Application).where(
            Application.applied_at >= start, Application.applied_at <= now)) or 0)

    return {"sent_today": await since(day_start), "sent_week": await since(week_start)}


async def propose_actions(session: AsyncSession, campaign: Campaign, job_ids: Sequence[uuid.UUID], *,
                          now: datetime, limit: int) -> list[dict[str, Any]]:
    settings, versions = await scoring.setting_versions(session)
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    crecord = campaign_record(campaign)
    records = await load_records(session, now=now, job_ids=list(job_ids))
    assessments = {a.job_id: a for a in (await session.scalars(select(Assessment).where(
        Assessment.campaign_id == campaign.id, Assessment.job_id.in_(list(job_ids))))).all()}
    sent = await sent_counters(session, now, settings["general.timezone"])
    simulated: Counter[str] = Counter()
    simulated_live: Counter[str] = Counter()

    def rank(item: tuple[Any, dict[str, Any]]) -> tuple[int, str]:
        found = assessments.get(item[0].id)
        return (-(found.score if found and found.score is not None else -1), str(item[0].id))

    proposals: list[dict[str, Any]] = []
    for job, record in sorted(records, key=rank):
        assessment = assessments.get(job.id)
        entry: dict[str, Any] = {"job_id": str(job.id), "title": job.title, "employer": job.employer,
                                 "score": assessment.score if assessment else None}
        if assessment is None or assessment.state == AssessmentState.parked or (
                assessment.state == AssessmentState.pending):
            proposals.append({**entry, "action": "parked",
                              "reason": "Not scored yet: paused for budget or waiting for a rubric."})
            continue
        employer_counts = await conflicts.employer_counters(session, job, now=now)
        counters = {**employer_counts,
                    "employer_live": employer_counts.get("employer_live", 0) + simulated_live[job.canonical_employer],
                    "sent_today": sent["sent_today"] + simulated["today"],
                    "sent_week": sent["sent_week"] + simulated["week"]}
        override = assessment.override.model_dump() if assessment.override else None
        decision = decide(scoring.decision_input(
            now=now, record=record, crecord=crecord, settings=settings, versions=versions, rubric=rubric,
            base_score=assessment.base_score, job=job, override=override, counters=counters, purpose="dry_run"))
        action = ACTION_BY_VERDICT[decision.verdict]
        if action == "apply":
            simulated["today"] += 1
            simulated["week"] += 1
            simulated_live[job.canonical_employer] += 1
            reason = "Every automation gate passes."
        else:
            blocking = [g for g in decision.gates if g.mandatory and g.outcome != "pass"
                        and g.layer in ("exclusion", "eligibility", "automation")]
            reason = blocking[0].reason if blocking else f"Verdict: {decision.verdict.replace('_', ' ')}."
            if job.conflict_state.value == "held":
                reason = job.conflict_note or "Held: outranked by another role at this employer."
        proposals.append({**entry, "score": decision.effective_score, "action": action, "reason": reason})
        if len(proposals) >= limit:
            break
    return proposals
