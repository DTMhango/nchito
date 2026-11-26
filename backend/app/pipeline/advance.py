"""After scoring, a real run moves roles on (DESIGN.md 7, 8): tailoring for each employer's winner.

The verdict comes from the one decision table (``decisions.decide``, purpose ``discovery``), so a real run
does exactly what its dry run proposed. A role whose verdict is ``tailor``, ``ask_owner`` or ``auto_apply``
(mode ``prepare`` or above, score at or over the tailor threshold, not held in its employer group) gets an
application for the run's campaign, if it has none, and a tailoring request. Dry runs never call this.
When tailoring and its checks pass, ``app.apply.prepare`` renders the documents and builds the packet;
the policy then approves it or asks the owner, and dispatch sends it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import prepare
from app.connect.filestore import FileStore
from app.connect.local_store import default_file_store
from app.models.applications import Application, Stage, TailoringRequest
from app.models.search import Assessment, AssessmentState, Campaign, Job, Run
from app.pipeline import conflicts, scoring
from app.pipeline.decisions import decide
from app.pipeline.filters import campaign_record, load_records

TAILOR_VERDICTS = frozenset({"tailor", "ask_owner", "auto_apply"})
ORIGIN = "system"


async def _application(session: AsyncSession, job: Job, campaign: Campaign) -> Application | None:
    """The role's live application (any campaign), or a new shortlisted one for this campaign."""
    existing = await session.scalar(select(Application).where(Application.job_id == job.id)
                                    .order_by(Application.created_at.desc()).limit(1))
    if existing is not None:
        return existing if existing.stage == Stage.shortlisted else None
    app = Application(job_id=job.id, campaign_id=campaign.id, stage=Stage.shortlisted, origin=ORIGIN)
    session.add(app)
    await session.flush()
    return app


async def tailor_winners(session: AsyncSession, run: Run, job_ids: Sequence[uuid.UUID], *, now: datetime
                         ) -> list[TailoringRequest]:
    """Request tailoring for the roles a real run should prepare. Returns the requests that need queueing
    (the caller commits first, then queues them)."""
    from app.pipeline.tailoring import tasks as tailoring

    if run.dry_run or run.campaign_id is None or not job_ids:
        return []
    campaign = await session.get(Campaign, run.campaign_id)
    if campaign is None:
        return []
    settings, versions = await scoring.setting_versions(session)
    rubric = await scoring.active_rubric(session, campaign.rubric_id)
    crecord = campaign_record(campaign)
    assessments = {a.job_id: a for a in (await session.scalars(select(Assessment).where(
        Assessment.campaign_id == campaign.id, Assessment.job_id.in_(list(job_ids))))).all()}
    queued: list[TailoringRequest] = []
    for job, record in await load_records(session, now=now, job_ids=list(job_ids)):
        assessment = assessments.get(job.id)
        if assessment is None or assessment.state in (AssessmentState.parked, AssessmentState.pending):
            continue
        counters = await conflicts.employer_counters(session, job, now=now)
        override = assessment.override.model_dump() if assessment.override else None
        decision = decide(scoring.decision_input(
            now=now, record=record, crecord=crecord, settings=settings, versions=versions, rubric=rubric,
            base_score=assessment.base_score, job=job, override=override, counters=counters, purpose="discovery"))
        if decision.verdict not in TAILOR_VERDICTS:
            continue
        app = await _application(session, job, campaign)
        if app is None:
            continue
        request, needs_queue = await tailoring.tailor(session, app.id, actor="system", run_id=run.id)
        if needs_queue:
            queued.append(request)
    return queued


async def after_tailored(session: AsyncSession, application_id: uuid.UUID, *, store: FileStore | None = None,
                         now: datetime | None = None) -> prepare.Prepared | None:
    """Once a tailored draft is stored and checked: render and build the packet (the caller commits).
    A draft whose check is stale or blocking stops here; the Studio shows why."""
    app = await session.get(Application, application_id)
    if app is None or app.stage not in (Stage.shortlisted, Stage.tailoring, Stage.ready):
        return None
    return await prepare.prepare_packet(session, store or default_file_store(), app, now=now)
