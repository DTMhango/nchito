"""Bulk actions on Matches and Applications selections (DESIGN 10.3).

One rule runs through everything here: **a bulk action is the single-item action, repeated.** Each item
goes through the same service function the single-item endpoint uses (``stages.transition``,
``approval.reject``, ``tailoring.service.request``, ``prepare.prepare_packet``, ``approval.approve``,
``recheck.recheck_job`` and the job and application field updates below), so gates, conflict groups,
employer limits, permits and the audit trail apply to every item exactly as they do to one.

Preview and run share one code path: an item is *tried* inside a savepoint. A preview rolls the savepoint
back and reports what would have happened; a run keeps it. Refusals carry a stable code and a reason and
are grouped by code in the preview ("42 selected: 37 will change, 5 can't because ...").

Bulk approval of sending is never offered: each approval is a per-packet decision. ``approve_reviewed``
(off by default, ``bulk.allow_approve_reviewed``) only approves, one by one through the normal approval,
packets that already exist and pass every gate with no unknowns.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, get_args

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import approval, gates, packets, stages
from app.apply import prepare as apply_prepare
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.models.applications import END_STAGES, Application, Stage
from app.models.bulk import BulkItem, BulkOperation
from app.models.search import Assessment, Campaign, ConflictState, Job
from app.pipeline import conflicts, employers
from app.schemas.json_types import BulkActionName, BulkSubject, BulkVerdict

log = logging.getLogger(__name__)

ACTIONS: tuple[str, ...] = get_args(BulkActionName)
# Actions that only make sense for applications, or only for jobs.
APPLICATION_ONLY = frozenset({"move_stage", "approve_reviewed"})
REVERSIBLE = frozenset({"tag", "untag", "snooze", "skip", "archive"})
MAX_TAG = 60

CODE_TITLES: dict[str, str] = {
    "illegal_stage": "its stage does not allow this",
    "illegal_transition": "that stage move is not allowed from where it is",
    "held": "it is held in its employer group (outranked by another role)",
    "never_apply": "you never apply to this employer",
    "cooldown": "its employer is cooling down",
    "feedback_excluded": "it matches an exclusion you accepted from feedback",
    "no_application": "it has no application yet",
    "duplicate": "it already has an application",
    "merged": "it was merged into another role",
    "spec_not_ready": "its tailored draft is missing or not checked",
    "answers_waiting": "an answer is still waiting for you",
    "no_destination": "there is nowhere to apply",
    "no_packet": "no packet has been built",
    "gates": "a gate does not pass (or has an unknown)",
    "not_finished": "only finished applications can be archived",
    "tailoring": "tailoring cannot be requested",
    "approval": "the approval was refused",
    "not_found": "it no longer exists",
    "error": "it could not be processed",
    "disabled": "this action is switched off in settings",
}


class BulkError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = "bulk_error") -> None:
        super().__init__(message)
        self.status, self.code = status, code


class Refuse(Exception):
    """This item cannot take the action now (a stable code and a reason the owner can read)."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code, self.reason = code, reason


class Unchanged(Exception):
    """Already as asked: nothing to do (re-running an action is harmless)."""

    def __init__(self, reason: str = "already as asked") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ItemResult:
    verdict: BulkVerdict
    code: str | None = None
    reason: str | None = None
    undo: dict[str, Any] | None = None
    after_commit: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


@dataclass
class Params:
    tag: str | None = None
    until: datetime | None = None
    reason: str | None = None
    stage: str | None = None
    campaign_id: uuid.UUID | None = None
    note: str | None = None

    def dump(self) -> dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, uuid.UUID) else v)
                for k, v in self.__dict__.items() if v is not None}


RecheckFn = Callable[[AsyncSession, Job, str], Awaitable[dict[str, Any]]]
TailorEnqueue = Callable[[Any], Awaitable[None]]


@dataclass
class Deps:
    """What the worker supplies; tests replace them (no network, no queue, no files)."""

    enqueue_tailoring: TailorEnqueue
    recheck: RecheckFn
    store: Callable[[], Any]


async def _default_enqueue_tailoring(req: Any) -> None:
    from app.pipeline.tailoring.tasks import enqueue
    from app.worker.queue import queue_app

    async with queue_app.open_async():
        await enqueue(req)


async def _default_recheck(session: AsyncSession, job: Job, actor: str) -> dict[str, Any]:
    from app.pipeline import orchestrator, scoring
    from app.pipeline import recheck as recheck_pipeline

    factory = orchestrator.DEPS.llm_factory
    llm = await factory(session, None) if factory is not None else await scoring.client_for(session)
    result = await recheck_pipeline.recheck_job(session, job, actor=actor, llm=llm)
    return {"availability": result.availability_after, "content_changed": result.content_changed,
            "note": result.note}


def default_deps() -> Deps:
    from app.connect.local_store import default_file_store

    return Deps(_default_enqueue_tailoring, _default_recheck, default_file_store)


@dataclass
class Ctx:
    session: AsyncSession
    actor: str
    params: Params
    settings: dict[str, Any]
    now: datetime
    deps: Deps
    dry: bool = False


# ----- the single-item services (also used by the single-item endpoints) --------------------------------


async def patch_job_fields(session: AsyncSession, job: Job, changes: dict[str, Any], *, actor: str,
                           reason: str | None = None) -> None:
    """Triage, pin, snooze, notes and manual tags on one job. Skipping a conflict winner promotes the next
    role. The one function behind ``PATCH /jobs/{id}`` and the bulk tag, skip, snooze and archive."""
    for key, value in changes.items():
        setattr(job, key, value)
    await session.flush()
    if "triage" in changes:
        await conflicts.on_job_changed(session, job)
    detail = {k: str(v) for k, v in changes.items()}
    if reason:
        detail["reason"] = reason
    await audit.record(session, actor=actor, action="job.updated", subject_type="job", subject_id=job.id,
                       detail=detail)


async def create_application(session: AsyncSession, job: Job, campaign_id: uuid.UUID | None, *, actor: str
                             ) -> Application:
    """Shortlist a role into an application. Raises ``Refuse('merged' | 'duplicate')``."""
    if job.merged_into_id is not None:
        raise Refuse("merged", "this job was merged into another; use that one")
    existing = await stages.blocking_application(session, job.id)
    if existing is not None:
        raise Refuse("duplicate", f"this job already has an application ({existing.stage.value})")
    app = Application(job_id=job.id, campaign_id=campaign_id, stage=Stage.shortlisted, origin="owner")
    session.add(app)
    await session.flush()
    await stages.add_event(session, app.id, "created", actor, {"origin": "owner"})
    await publish(session, "application.updated", {"application_id": str(app.id)})
    return app


# ----- subjects -------------------------------------------------------------------------------------


def label_of(job: Job) -> str:
    return f"{job.title} at {job.employer}"[:400]


async def _job_of(ctx: Ctx, subject: Job | Application) -> Job:
    if isinstance(subject, Job):
        return subject
    job = await ctx.session.get(Job, subject.job_id)
    if job is None:
        raise Refuse("not_found", "the role no longer exists")
    return job


async def _application_of(ctx: Ctx, subject: Job | Application) -> Application | None:
    if isinstance(subject, Application):
        return subject
    app = await stages.blocking_application(ctx.session, subject.id)
    if app is None:
        return None
    return await ctx.session.get(Application, app.id, with_for_update=True)


def _clean_tag(ctx: Ctx) -> str:
    tag = (ctx.params.tag or "").strip().lower()
    if not tag or len(tag) > MAX_TAG:
        raise BulkError(f"give a tag of 1 to {MAX_TAG} characters", 422, "bad_params")
    return tag


# ----- handlers: each tries one item through the single-item service ----------------------------------


async def _tag(ctx: Ctx, subject: Job | Application) -> ItemResult:
    job, tag = await _job_of(ctx, subject), _clean_tag(ctx)
    if tag in job.tags:
        raise Unchanged(f"already tagged '{tag}'")
    before = list(job.tags)
    await patch_job_fields(ctx.session, job, {"tags": [*job.tags, tag]}, actor=ctx.actor)
    return ItemResult("change", undo={"before": before, "after": list(job.tags)})


async def _untag(ctx: Ctx, subject: Job | Application) -> ItemResult:
    job, tag = await _job_of(ctx, subject), _clean_tag(ctx)
    if tag not in job.tags:
        raise Unchanged(f"not tagged '{tag}'")
    before = list(job.tags)
    await patch_job_fields(ctx.session, job, {"tags": [t for t in job.tags if t != tag]}, actor=ctx.actor)
    return ItemResult("change", undo={"before": before, "after": list(job.tags)})


async def _archive(ctx: Ctx, subject: Job | Application) -> ItemResult:
    job = await _job_of(ctx, subject)
    if isinstance(subject, Application) and subject.stage not in END_STAGES:
        raise Refuse("not_finished", f"it is {subject.stage.value}; only finished applications can be archived")
    if job.triage == "archived":
        raise Unchanged("already archived")
    before = job.triage
    await patch_job_fields(ctx.session, job, {"triage": "archived"}, actor=ctx.actor, reason=ctx.params.reason)
    return ItemResult("change", undo={"before": before, "after": "archived"})


async def _snooze(ctx: Ctx, subject: Job | Application) -> ItemResult:
    until = ctx.params.until
    if until is None or until <= ctx.now:
        raise BulkError("give a snooze time in the future", 422, "bad_params")
    if isinstance(subject, Application):
        if subject.snoozed_until == until:
            raise Unchanged("already snoozed until then")
        before = subject.snoozed_until
        subject.snoozed_until = until
        await stages.add_event(ctx.session, subject.id, "edit", ctx.actor, {"changes": {"snoozed_until": {
            "before": before.isoformat() if before else None, "after": until.isoformat()}}})
        await publish(ctx.session, "application.updated", {"application_id": str(subject.id)})
        return ItemResult("change", undo={"before": before.isoformat() if before else None,
                                          "after": until.isoformat()})
    if subject.snoozed_until == until:
        raise Unchanged("already snoozed until then")
    before = subject.snoozed_until
    await patch_job_fields(ctx.session, subject, {"snoozed_until": until}, actor=ctx.actor)
    return ItemResult("change", undo={"before": before.isoformat() if before else None, "after": until.isoformat()})


async def _skip(ctx: Ctx, subject: Job | Application) -> ItemResult:
    reason = (ctx.params.reason or "").strip()
    if not reason:
        raise BulkError("say why you are skipping them", 422, "reason_required")
    if isinstance(subject, Job):
        if subject.triage == "skipped":
            raise Unchanged("already skipped")
        before = subject.triage
        await patch_job_fields(ctx.session, subject, {"triage": "skipped"}, actor=ctx.actor, reason=reason)
        return ItemResult("change", undo={"before": before, "after": "skipped"})
    job = await _job_of(ctx, subject)
    if subject.stage == Stage.skipped:
        raise Unchanged("already skipped")
    before_stage, before_triage = subject.stage.value, job.triage
    try:  # the Applications "skip": retire the packet, close the approval, promote the next role
        await approval.reject(ctx.session, subject, actor=ctx.actor, reason=reason, now=ctx.now)
    except approval.ApprovalError as exc:
        raise Refuse("illegal_stage", exc.message) from exc
    except stages.IllegalTransition as exc:
        raise Refuse("illegal_transition", exc.reason) from exc
    return ItemResult("change", undo={"stage_before": before_stage, "triage_before": before_triage,
                                      "after": "skipped"})


async def _move_stage(ctx: Ctx, subject: Job | Application) -> ItemResult:
    assert isinstance(subject, Application)
    if not ctx.params.stage or ctx.params.stage not in {s.value for s in Stage}:
        raise BulkError("choose a stage", 422, "bad_params")
    target = Stage(ctx.params.stage)
    if subject.stage == target:
        raise Unchanged(f"already in {target.value}")
    try:
        await stages.transition(ctx.session, subject, target, actor=ctx.actor, via="owner",
                                why=(ctx.params.note or "").strip() or f"Owner moved it to {target.value} (bulk)")
    except stages.IllegalTransition as exc:
        raise Refuse("illegal_transition", exc.reason) from exc
    await publish(ctx.session, "application.updated", {"application_id": str(subject.id)})
    return ItemResult("change")


async def _assign_campaign(ctx: Ctx, subject: Job | Application) -> ItemResult:
    campaign_id = ctx.params.campaign_id
    if campaign_id is None:
        raise BulkError("choose a campaign", 422, "bad_params")
    app = await _application_of(ctx, subject)
    if app is None:
        assert isinstance(subject, Job)
        app = await create_application(ctx.session, subject, campaign_id, actor=ctx.actor)
        return ItemResult("change")
    if app.campaign_id == campaign_id:
        raise Unchanged("already in that campaign")
    if app.stage not in (Stage.shortlisted, Stage.tailoring, Stage.ready) or app.approved_packet_id is not None:
        raise Refuse("illegal_stage", "its campaign cannot change once it is approved or sent")
    before = app.campaign_id
    app.campaign_id = campaign_id
    await stages.add_event(ctx.session, app.id, "edit", ctx.actor, {"changes": {"campaign_id": {
        "before": str(before) if before else None, "after": str(campaign_id)}}})
    await publish(ctx.session, "application.updated", {"application_id": str(app.id)})
    return ItemResult("change")


def _check_work_allowed(job: Job) -> None:
    if job.conflict_state == ConflictState.held:
        raise Refuse("held", job.conflict_note or "held: outranked in its employer group")
    if job.merged_into_id is not None:
        raise Refuse("merged", "this job was merged into another; use that one")


async def _check_policy(ctx: Ctx, job: Job, app: Application | None) -> None:
    """Employer policy and accepted feedback, checked now (a role's assessment may predate them):
    never apply, the employer cooldown, and an exclusion the owner accepted from feedback."""
    from app.pipeline import preferences

    never = await employers.never_apply_reason(ctx.session, job)
    if never is not None:
        raise Refuse("never_apply", never)
    left = (await conflicts.employer_counters(ctx.session, job))["employer_cooldown_days_left"]
    if left > 0:
        raise Refuse("cooldown", f"the employer is cooling down for {left} more day(s)")
    if app is not None and app.campaign_id is not None:
        campaign_ids: list[uuid.UUID] = [app.campaign_id]
    else:
        campaign_ids = list((await ctx.session.scalars(
            select(Assessment.campaign_id).where(Assessment.job_id == job.id))).all())
    excluded = await preferences.accepted_exclusion(ctx.session, job.id, campaign_ids)
    if excluded is not None:
        raise Refuse("feedback_excluded", excluded)


async def _queue_tailoring(ctx: Ctx, subject: Job | Application) -> ItemResult:
    from app.pipeline.tailoring import service as tailoring_service

    job = await _job_of(ctx, subject)
    _check_work_allowed(job)
    app = await _application_of(ctx, subject)
    await _check_policy(ctx, job, app)
    if app is None:
        assert isinstance(subject, Job)
        app = await create_application(ctx.session, subject, None, actor=ctx.actor)
    try:
        req, needs_queue = await tailoring_service.request(ctx.session, app, actor=ctx.actor)
    except tailoring_service.TailoringError as exc:
        code = "never_apply" if str(exc).startswith("you never apply") else "tailoring"
        raise Refuse(code, str(exc)) from exc
    if not needs_queue:
        raise Unchanged("tailoring is already requested for its current draft")
    await publish(ctx.session, "application.updated", {"application_id": str(app.id)})
    deps = ctx.deps

    async def queue() -> None:
        await deps.enqueue_tailoring(req)

    return ItemResult("change", after_commit=[queue])


async def _send_precheck(ctx: Ctx, app: Application, job: Job) -> None:
    """The cheap, deterministic reasons nothing can be built, in the order the owner would meet them."""
    _check_work_allowed(job)
    await _check_policy(ctx, job, app)
    if app.stage not in approval.APPROVABLE_STAGES:
        raise Refuse("illegal_stage", f"an application in {app.stage.value} cannot be sent for approval")
    version, check = await apply_prepare.spec_state(ctx.session, app)
    if check[0] != "pass" or version is None:
        raise Refuse("spec_not_ready", check[1])
    waiting = [a.question for a in version.answers if a.outcome == "ask_owner"]
    if waiting:
        raise Refuse("answers_waiting", f"waiting for your answer to: {', '.join(waiting)}")


async def _send_for_approval(ctx: Ctx, subject: Job | Application) -> ItemResult:
    job = await _job_of(ctx, subject)
    app = await _application_of(ctx, subject)
    if app is None:
        raise Refuse("no_application", "it has no application to send")
    await _send_precheck(ctx, app, job)
    if ctx.dry:
        return ItemResult("change")  # packets render files: a preview stops at the checks above
    prepared = await apply_prepare.prepare_packet(ctx.session, ctx.deps.store(), app, actor=ctx.actor)
    if not prepared.built:
        raise Refuse(prepared.code or "no_destination", prepared.reason)
    return ItemResult("change", reason=getattr(prepared.approval, "reason", None))


async def _approve_reviewed(ctx: Ctx, subject: Job | Application) -> ItemResult:
    assert isinstance(subject, Application)
    if not ctx.settings["bulk.allow_approve_reviewed"]:
        raise BulkError("'approve all reviewed' is switched off in settings", 403, "disabled")
    job = await _job_of(ctx, subject)
    _check_work_allowed(job)
    if subject.stage not in approval.APPROVABLE_STAGES:
        raise Refuse("illegal_stage", f"an application in {subject.stage.value} cannot be approved")
    packet = await packets.current(ctx.session, subject.id)
    if packet is None:
        raise Refuse("no_packet", "no packet has been built for this application")
    if packet.approved_at is not None and subject.approved_packet_id == packet.id:
        raise Unchanged("this packet is already approved")
    channel = packet.contents.channel or (subject.channel.value if subject.channel else "manual")
    strict = await gates.evaluate(ctx.session, subject, packet, channel=channel, approval="auto",
                                  packet_hash=packet.content_hash, for_approval=True, now=ctx.now)
    if strict.status != "granted":  # an owner's yes may settle unknowns; here every gate must pass outright
        raise Refuse("gates", strict.reason or "a gate does not pass")
    try:
        await approval.approve(ctx.session, subject, packet_version=packet.version, packet_hash=packet.content_hash,
                               channel=channel, actor=ctx.actor, now=ctx.now)
    except approval.ApprovalError as exc:
        raise Refuse("approval", exc.message) from exc
    return ItemResult("change")


async def _recheck(ctx: Ctx, subject: Job | Application) -> ItemResult:
    job = await _job_of(ctx, subject)
    if job.merged_into_id is not None:
        raise Refuse("merged", "this job was merged into another; use that one")
    if ctx.dry:
        return ItemResult("change")
    summary = await ctx.deps.recheck(ctx.session, job, ctx.actor)
    note = f"{summary['availability']}" + (", content changed" if summary.get("content_changed") else "")
    return ItemResult("change", reason=note)


async def _export(ctx: Ctx, subject: Job | Application) -> ItemResult:
    return ItemResult("change", reason="included in the export")


HANDLERS: dict[str, Callable[[Ctx, Any], Awaitable[ItemResult]]] = {
    "tag": _tag, "untag": _untag, "archive": _archive, "snooze": _snooze, "skip": _skip,
    "move_stage": _move_stage, "assign_campaign": _assign_campaign, "queue_tailoring": _queue_tailoring,
    "send_for_approval": _send_for_approval, "approve_reviewed": _approve_reviewed, "recheck": _recheck,
    "export_csv": _export,
}


class _Rollback(Exception):
    def __init__(self, result: ItemResult) -> None:
        super().__init__("rollback")
        self.result = result


async def try_item(ctx: Ctx, action: str, subject: Job | Application) -> ItemResult:
    """Try one item through its single-item service inside a savepoint: kept on a run, rolled back on a
    preview, a refusal or an unchanged item. Parameter mistakes (``BulkError``) propagate."""
    handler = HANDLERS[action]
    try:
        async with ctx.session.begin_nested():
            try:
                result = await handler(ctx, subject)
            except Unchanged as exc:
                raise _Rollback(ItemResult("unchanged", "unchanged", exc.reason)) from exc
            except Refuse as exc:
                raise _Rollback(ItemResult("refused", exc.code, exc.reason)) from exc
            if ctx.dry:
                raise _Rollback(result)
            return result
    except _Rollback as rolled:
        return rolled.result


# ----- selection, preview ------------------------------------------------------------------------------


def parse_params(raw: dict[str, Any] | None) -> Params:
    raw = raw or {}
    until = raw.get("until")
    if isinstance(until, str):
        until = datetime.fromisoformat(until.replace("Z", "+00:00"))
    campaign = raw.get("campaign_id")
    return Params(tag=raw.get("tag"), until=until, reason=raw.get("reason"), stage=raw.get("stage"),
                  campaign_id=uuid.UUID(str(campaign)) if campaign else None, note=raw.get("note"))


def validate_action(subject: str, action: str, params: Params) -> None:
    if action not in ACTIONS:
        raise BulkError(f"unknown action '{action}'", 422, "bad_action")
    if subject == "jobs" and action in APPLICATION_ONLY:
        raise BulkError(f"'{action}' applies to applications, not to roles in Matches", 422, "bad_action")
    if action in ("tag", "untag") and not (params.tag or "").strip():
        raise BulkError("give a tag", 422, "bad_params")
    if action == "skip" and not (params.reason or "").strip():
        raise BulkError("say why you are skipping them", 422, "reason_required")
    if action == "snooze" and params.until is None:
        raise BulkError("give a snooze time", 422, "bad_params")
    if action == "move_stage" and params.stage not in {s.value for s in Stage}:
        raise BulkError("choose a stage", 422, "bad_params")
    if action == "assign_campaign" and params.campaign_id is None:
        raise BulkError("choose a campaign", 422, "bad_params")


async def _load_subject(session: AsyncSession, subject: str, subject_id: uuid.UUID) -> Job | Application | None:
    if subject == "jobs":
        return await session.get(Job, subject_id)
    return await session.get(Application, subject_id, with_for_update=True)


async def _label(session: AsyncSession, obj: Job | Application) -> str:
    if isinstance(obj, Job):
        return label_of(obj)
    job = await session.get(Job, obj.job_id)
    return label_of(job) if job else str(obj.id)


async def _settings(session: AsyncSession) -> dict[str, Any]:
    return dict(await settings_service.values(session))


async def create_preview(session: AsyncSession, *, subject: BulkSubject, action: str, ids: Sequence[uuid.UUID],
                         params: Params, selection: dict[str, Any], actor: str, deps: Deps | None = None,
                         now: datetime | None = None) -> BulkOperation:
    """Resolve the plan for every id (nothing changes), store it, and return the operation (``previewed``)."""
    now = now or utcnow()
    settings = await _settings(session)
    validate_action(subject, action, params)
    unique = list(dict.fromkeys(ids))
    cap = int(settings["bulk.max_selection"])
    if not unique:
        raise BulkError("nothing is selected", 422, "empty_selection")
    if len(unique) > cap:
        raise BulkError(f"{len(unique)} selected; the limit is {cap}. Narrow the selection or raise "
                        "'Largest bulk selection' in settings.", 422, "selection_too_large")
    if action == "approve_reviewed" and not settings["bulk.allow_approve_reviewed"]:
        raise BulkError("'approve all reviewed' is switched off in settings", 403, "disabled")
    if action == "assign_campaign" and await session.get(Campaign, params.campaign_id) is None:
        raise BulkError("campaign not found", 404, "not_found")
    op = BulkOperation(subject=subject, action=action, params=params.dump(), selection=selection, status="previewed",
                       selected=len(unique), created_by=actor)
    session.add(op)
    await session.flush()
    ctx = Ctx(session, actor, params, settings, now, deps or default_deps(), dry=True)
    for subject_id in unique:
        obj = await _load_subject(session, subject, subject_id)
        if obj is None:
            session.add(BulkItem(operation_id=op.id, subject_id=subject_id, label=str(subject_id), planned="refused",
                                 planned_code="not_found", planned_reason="it no longer exists"))
            continue
        label = await _label(session, obj)
        try:
            res = await try_item(ctx, action, obj)
        except BulkError:
            raise
        except Exception as exc:  # a preview must never fail the whole selection
            log.exception("bulk preview of %s failed", subject_id)
            res = ItemResult("refused", "error", f"{type(exc).__name__}: {exc}"[:300])
        session.add(BulkItem(operation_id=op.id, subject_id=subject_id, label=label, planned=res.verdict,
                             planned_code=res.code, planned_reason=res.reason))
    await session.flush()
    return op


@dataclass
class ReasonGroup:
    code: str
    title: str
    count: int
    samples: list[tuple[uuid.UUID, str, str]]


@dataclass
class PreviewSummary:
    selected: int
    will_change: int
    unchanged: ReasonGroup | None
    refused: list[ReasonGroup]


async def summarise(session: AsyncSession, op: BulkOperation) -> PreviewSummary:
    sample_size = int((await _settings(session))["bulk.preview_sample_size"])
    items = list((await session.scalars(select(BulkItem).where(BulkItem.operation_id == op.id)
                                        .order_by(BulkItem.created_at, BulkItem.label))).all())
    change = sum(1 for i in items if i.planned == "change")
    groups: dict[str, ReasonGroup] = {}
    unchanged: ReasonGroup | None = None
    for item in items:
        if item.planned == "change":
            continue
        code = item.planned_code or "error"
        if item.planned == "unchanged":
            unchanged = unchanged or ReasonGroup("unchanged", "nothing to change (already as asked)", 0, [])
            group = unchanged
        else:
            group = groups.setdefault(code, ReasonGroup(code, CODE_TITLES.get(code, code), 0, []))
        group.count += 1
        if len(group.samples) < sample_size:
            group.samples.append((item.subject_id, item.label, item.planned_reason or ""))
    return PreviewSummary(op.selected, change, unchanged, sorted(groups.values(), key=lambda g: (-g.count, g.code)))


# ----- run --------------------------------------------------------------------------------------------


async def confirm(session: AsyncSession, op_id: uuid.UUID, *, confirm_count: int | None, actor: str) -> BulkOperation:
    """Confirm the previewed count and queue the run (or retry a failed or partial one)."""
    op = await session.get(BulkOperation, op_id, with_for_update=True)
    if op is None:
        raise BulkError("operation not found", 404, "not_found")
    if op.status in ("queued", "running", "done", "undone"):
        raise BulkError(f"this operation is already {op.status}", 409, "already_run")
    if op.status == "previewed" and confirm_count != op.selected:
        raise BulkError(f"confirm the count: {op.selected} are selected", 409, "count_mismatch")
    op.status = "queued"
    await audit.record(session, actor=actor, action="bulk.confirmed", subject_type="bulk_operation",
                       subject_id=op.id, detail={"action": op.action, "subject": op.subject,
                                                 "selected": op.selected, "params": op.params})
    await session.flush()
    return op


async def _counts(session: AsyncSession, op_id: uuid.UUID) -> dict[str, int]:
    rows = (await session.execute(select(BulkItem.outcome, func.count()).where(BulkItem.operation_id == op_id)
                                  .group_by(BulkItem.outcome))).all()
    return {outcome: int(n) for outcome, n in rows}


async def execute(session: AsyncSession, op_id: uuid.UUID, deps: Deps | None = None,
                  now: datetime | None = None) -> BulkOperation:
    """Run a queued operation item by item, committing after each so progress is visible and one failure
    never undoes the others. Safe to call again: finished items are left alone, failed ones are retried."""
    deps = deps or default_deps()
    op = await session.get(BulkOperation, op_id, with_for_update=True)
    if op is None:
        raise BulkError("operation not found", 404, "not_found")
    if op.status not in ("queued", "running"):
        return op
    settings = await _settings(session)
    params = parse_params(op.params)
    kind, action, actor = op.subject, op.action, op.created_by  # plain values: ``op`` expires on every commit
    op.status, op.started_at = "running", op.started_at or utcnow()
    op_id = op.id
    await session.execute(BulkItem.__table__.update().where(
        BulkItem.operation_id == op.id, BulkItem.outcome == "failed").values(outcome="pending"))
    await session.commit()
    pending = list((await session.scalars(select(BulkItem).where(
        BulkItem.operation_id == op.id, BulkItem.outcome == "pending").order_by(BulkItem.created_at, BulkItem.label))
    ).all())
    ids = [(i.id, i.subject_id) for i in pending]
    for done, (item_id, subject_id) in enumerate(ids, start=1):
        ctx = Ctx(session, actor, params, settings, now or utcnow(), deps)
        after: list[Callable[[], Awaitable[None]]] = []
        item = await session.get(BulkItem, item_id)
        assert item is not None
        try:
            obj = await _load_subject(session, kind, subject_id)
            if obj is None:
                item.outcome, item.code, item.reason = "refused", "not_found", "it no longer exists"
            else:
                res = await try_item(ctx, action, obj)
                item.outcome = {"change": "changed", "unchanged": "unchanged", "refused": "refused"}[res.verdict]
                item.code, item.reason, item.undo = res.code, res.reason, res.undo
                after = res.after_commit
        except BulkError as exc:
            await session.rollback()
            item = await session.get(BulkItem, item_id)
            assert item is not None
            item.outcome, item.code, item.reason = "failed", exc.code, str(exc)
        except Exception as exc:
            await session.rollback()
            log.exception("bulk item %s failed", subject_id)
            item = await session.get(BulkItem, item_id)
            assert item is not None
            item.outcome, item.code, item.reason = "failed", "error", f"{type(exc).__name__}: {exc}"[:500]
        await publish(session, "bulk.progress", {"operation_id": str(op_id), "done": done, "total": len(ids)})
        await session.commit()
        for callback in after:  # after the item is durable: queueing must never fail or roll back the change
            try:
                await callback()
            except Exception:
                log.exception("bulk after-commit step failed for %s", subject_id)
    return await _finish(session, op_id, settings)


async def _finish(session: AsyncSession, op_id: uuid.UUID, settings: dict[str, Any]) -> BulkOperation:
    op = await session.get(BulkOperation, op_id, with_for_update=True)
    assert op is not None
    counts = await _counts(session, op_id)
    failed, changed = counts.get("failed", 0), counts.get("changed", 0)
    op.status = "failed" if failed and not changed and not counts.get("unchanged") else "partial" if failed else "done"
    op.finished_at = utcnow()
    window = int(settings["bulk.undo_window_minutes"])
    if op.action in REVERSIBLE and changed and window > 0:
        op.undo_until = op.finished_at + timedelta(minutes=window)
    await audit.record(session, actor=op.created_by, action="bulk.finished", subject_type="bulk_operation",
                       subject_id=op.id, detail={"action": op.action, "subject": op.subject, "counts": counts})
    await publish(session, "bulk.finished", {"operation_id": str(op.id), "status": op.status})
    await session.commit()
    return op


# ----- undo -------------------------------------------------------------------------------------------


async def undo(session: AsyncSession, op_id: uuid.UUID, *, actor: str, now: datetime | None = None
               ) -> BulkOperation:
    """Reverse the changed items of a reversible action inside the undo window. An item that has changed
    since is left alone and reported."""
    now = now or utcnow()
    op = await session.get(BulkOperation, op_id, with_for_update=True)
    if op is None:
        raise BulkError("operation not found", 404, "not_found")
    if op.action not in REVERSIBLE:
        raise BulkError("this action cannot be undone", 409, "not_reversible")
    if op.status not in ("done", "partial") or op.undone_at is not None:
        raise BulkError(f"nothing to undo: the operation is {op.status}", 409, "not_undoable")
    if op.undo_until is None or now > op.undo_until:
        raise BulkError("the undo window has passed", 409, "undo_expired")
    items = list((await session.scalars(select(BulkItem).where(
        BulkItem.operation_id == op.id, BulkItem.outcome == "changed"))).all())
    for item in items:
        subject = await _load_subject(session, op.subject, item.subject_id)
        try:
            async with session.begin_nested():
                if subject is None:
                    raise Refuse("not_found", "it no longer exists")
                await _undo_one(session, op, subject, item.undo or {}, actor)
            item.outcome = "undone"
        except Refuse as exc:
            item.outcome, item.code, item.reason = "undo_skipped", exc.code, exc.reason
    op.status, op.undone_at = "undone", now
    await audit.record(session, actor=actor, action="bulk.undone", subject_type="bulk_operation", subject_id=op.id,
                       detail={"action": op.action, "items": len(items)})
    await publish(session, "bulk.finished", {"operation_id": str(op.id), "status": "undone"})
    await session.flush()
    return op


async def _undo_one(session: AsyncSession, op: BulkOperation, subject: Job | Application, data: dict[str, Any],
                    actor: str) -> None:
    job = subject if isinstance(subject, Job) else await session.get(Job, subject.job_id)
    assert job is not None
    if op.action in ("tag", "untag"):
        if list(job.tags) != data["after"]:
            raise Refuse("changed_since", "its tags changed since")
        await patch_job_fields(session, job, {"tags": data["before"]}, actor=actor)
    elif op.action == "archive":
        if job.triage != "archived":
            raise Refuse("changed_since", "it is no longer archived")
        await patch_job_fields(session, job, {"triage": data["before"]}, actor=actor)
    elif op.action == "snooze":
        current = subject.snoozed_until.isoformat() if subject.snoozed_until else None
        if current != data["after"]:
            raise Refuse("changed_since", "its snooze changed since")
        before = datetime.fromisoformat(data["before"]) if data["before"] else None
        if isinstance(subject, Application):
            subject.snoozed_until = before
            await stages.add_event(session, subject.id, "edit", actor, {"changes": {"snoozed_until": {
                "before": data["after"], "after": data["before"]}}})
        else:
            await patch_job_fields(session, subject, {"snoozed_until": before}, actor=actor)
    elif op.action == "skip":
        if isinstance(subject, Job):
            if subject.triage != "skipped":
                raise Refuse("changed_since", "it is no longer skipped")
            await patch_job_fields(session, subject, {"triage": data["before"]}, actor=actor)
        else:
            if subject.stage != Stage.skipped:
                raise Refuse("changed_since", f"it is {subject.stage.value} now")
            try:  # a skipped application can only come back as shortlisted
                await stages.transition(session, subject, Stage.shortlisted, actor=actor, via="owner",
                                        why="Skip undone (bulk)")
            except stages.IllegalTransition as exc:
                raise Refuse("illegal_transition", exc.reason) from exc
            await patch_job_fields(session, job, {"triage": data["triage_before"]}, actor=actor)


# ----- export -----------------------------------------------------------------------------------------

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA) else text  # posting text is untrusted: no spreadsheet formulas


async def export_csv(session: AsyncSession, op: BulkOperation) -> str:
    """The CSV of the operation's selection (the export action; read only)."""
    ids = [i.subject_id for i in (await session.scalars(select(BulkItem).where(BulkItem.operation_id == op.id)
                                                        .order_by(BulkItem.label))).all()]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    if op.subject == "jobs":
        writer.writerow(["id", "title", "employer", "location", "triage", "best_score", "tags", "conflict",
                         "deadline", "apply_url"])
        scores = dict((await session.execute(select(Assessment.job_id, func.max(Assessment.score)).where(
            Assessment.job_id.in_(ids)).group_by(Assessment.job_id))).all())
        for job in (await session.scalars(select(Job).where(Job.id.in_(ids)).order_by(Job.title))).all():
            loc = job.location
            place = ", ".join(p for p in (getattr(loc, "city", None), getattr(loc, "country", None)) if p)
            writer.writerow([_cell(v) for v in (
                job.id, job.title, job.employer, place, job.triage, scores.get(job.id), "; ".join(job.tags),
                job.conflict_state.value, job.deadline, job.apply_url)])
    else:
        writer.writerow(["id", "title", "employer", "stage", "channel", "best_score", "applied_at", "next_step",
                         "next_due"])
        for app in (await session.scalars(select(Application).where(Application.id.in_(ids)))).all():
            job = await session.get(Job, app.job_id)
            score = await session.scalar(select(func.max(Assessment.score)).where(Assessment.job_id == app.job_id))
            writer.writerow([_cell(v) for v in (
                app.id, job.title if job else "", job.employer if job else "", app.stage.value,
                app.channel.value if app.channel else "", score, app.applied_at, app.next_step, app.next_due)])
    return out.getvalue()
