"""Agent tasks: hand-out, routing, atomic claims, leases and checkpoints (DESIGN.md 8.3, 8.4, 18.1).

Invariants, never settings:

- **Atomic claim.** A task is claimed with ``SELECT ... FOR UPDATE SKIP LOCKED``: two runners never get one
  task. A runner sees only tasks it has claimed.
- **Resume, never repeat.** A task whose runner goes silent past the lease returns to the queue with its
  checkpoint. If a submit permit was already given for it (a dispatch attempt is open), it is not handed
  out again: that attempt is reconciled, so a restart cannot submit twice.
- **Routing.** A form that needs an account, or might (unknown is not yes), goes only to a PC runner,
  where the owner can sign in; server runners take only forms known to need none. A task resumed after
  the owner signed in goes back to the runner that holds the session.
- **Nothing outward while paused.** No apply task is handed out while autopilot is paused.
- Hand-out is only for an application whose current packet is approved for the browser channel. Apply tasks
  are created by the browser channel and claimed through ``browser.mark_task_claimed`` (one permit flow).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import outcomes, packets
from app.apply.channels import browser
from app.core import audit
from app.gateway.common import (
    GatewayError,
    approved_packet,
    clip,
    lease_expired,
    lease_minutes,
    own_task,
    require_active,
    require_scope,
    setting,
)
from app.gateway.tools import (
    NextTaskIn,
    NextTaskOut,
    ReleaseTaskIn,
    ReleaseTaskOut,
    ReportCheckIn,
    ReportCheckOut,
    SaveCheckpointIn,
    SaveCheckpointOut,
    TaskRules,
)
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    AgentTaskType,
    Application,
    DispatchAttempt,
    Stage,
)
from app.models.platform import ApiToken
from app.models.search import Availability, Job

OPEN_TASK = (AgentTaskStatus.queued, AgentTaskStatus.claimed, AgentTaskStatus.blocked)
SCOPE_OF = {AgentTaskType.apply: "gateway:tasks", AgentTaskType.check_posting: "gateway:tasks",
            AgentTaskType.sweep_site: "gateway:sweep"}


# ----- routing ----------------------------------------------------------------------------------
#
# Apply tasks are created by the browser channel only (``dispatch.queue`` without a runner token, or the worker's
# ``browser.queue_approved_tasks``): one hand-out path, one permit flow. Routing is ``browser.preferred_runner``.


async def route_for(session: AsyncSession, job: Job) -> str | None:
    """``pc``, ``server`` or None (any runner) for a task on this job (the browser channel's routing)."""
    return await browser.preferred_runner(session, job)


async def open_attempt(session: AsyncSession, application_id: uuid.UUID) -> DispatchAttempt | None:
    return await session.scalar(select(DispatchAttempt).where(
        DispatchAttempt.application_id == application_id, DispatchAttempt.status.in_(outcomes.OPEN_STATUSES))
        .order_by(DispatchAttempt.created_at.desc()).limit(1))


async def enqueue_sweep(session: AsyncSession, *, source_id: uuid.UUID, url: str, actor: str = "system",
                        preferred_runner: str | None = None) -> AgentTask:
    """A sweep of one site for a source (its jobs come back through ``report_jobs``)."""
    domain = packets.domain_of(url)
    if not domain:
        raise ValueError("a sweep task needs a site URL")
    task = AgentTask(type=AgentTaskType.sweep_site, preferred_runner=preferred_runner, status=AgentTaskStatus.queued,
                     payload={"source_id": str(source_id), "posting_url": url, "domain": domain})
    session.add(task)
    await session.flush()
    await audit.record(session, actor=actor, action="gateway.task_queued", subject_type="agent_task",
                       subject_id=task.id, detail={"type": "sweep_site", "source_id": str(source_id), "url": url})
    return task


# ----- leases ------------------------------------------------------------------------------------


async def expire_one(session: AsyncSession, task: AgentTask, *, at: datetime) -> str:
    """A claimed task whose runner went silent. Returns ``requeued`` or ``reconcile``."""
    attempt = await open_attempt(session, task.application_id) if task.application_id else None
    holder = task.claimed_by_token_id
    if attempt is not None:
        task.status = AgentTaskStatus.failed
        task.result = {"outcome": "uncertain", "reason": "the runner went silent after its submit permit; the "
                       "send is reconciled, never repeated", "attempt_id": str(attempt.id)}
        result = "reconcile"
    else:
        task.status = AgentTaskStatus.queued
        task.claimed_by_token_id = task.claimed_at = task.heartbeat_at = None
        task.payload = {**{k: v for k, v in task.payload.items() if k != "dry_run"}, "resume": True,
                        "resume_runner_token_id": None}
        result = "requeued"
    await session.flush()
    await audit.record(session, actor="system", action="gateway.lease_expired", subject_type="agent_task",
                       subject_id=task.id, detail={"result": result, "runner": str(holder) if holder else None,
                                                   "at": at.isoformat()})
    return result


async def expire_leases(session: AsyncSession, *, at: datetime) -> dict[uuid.UUID, str]:
    minutes = await lease_minutes(session)
    stale = (await session.scalars(select(AgentTask).where(
        AgentTask.status == AgentTaskStatus.claimed,
        or_(AgentTask.heartbeat_at.is_(None), AgentTask.heartbeat_at <= at - timedelta(minutes=minutes)))
        .with_for_update(skip_locked=True))).all()
    return {t.id: await expire_one(session, t, at=at) for t in stale if lease_expired(t, at, minutes)}


# ----- next_task ---------------------------------------------------------------------------------


async def instructions(session: AsyncSession, task: AgentTask) -> tuple[str, TaskRules]:
    template = str(await setting(session, "runners.task_instructions"))
    max_steps = int(await setting(session, "automation.agent_max_steps"))
    domain = str(task.payload.get("domain") or task.payload.get("destination_domain") or "")
    text = template.format(task_type=task.type.value.replace("_", " "), posting_url=posting_url(task),
                           domain=domain, max_steps=max_steps)
    return text, TaskRules(stay_on_domain=domain, max_steps=max_steps)


async def describe(session: AsyncSession, task: AgentTask) -> NextTaskOut:
    text, rules = await instructions(session, task)
    return NextTaskOut(task_id=str(task.id), type=task.type.value, instructions=text,
                       posting_url=posting_url(task), checkpoint=task.checkpoint, rules=rules)


def posting_url(task: AgentTask) -> str | None:
    return task.payload.get("posting_url") or task.payload.get("destination_url")


def _allowed_types(token: ApiToken, wanted: list[str] | None) -> list[AgentTaskType]:
    types = [t for t, scope in SCOPE_OF.items() if scope in (token.scopes or [])]
    if wanted is not None:
        types = [t for t in types if t.value in wanted]
    return types


async def _still_wanted(session: AsyncSession, task: AgentTask, at: datetime) -> bool:
    """An apply task whose packet is no longer the approved current one is cancelled instead of handed out
    (a newly approved packet gets its own task from the browser channel)."""
    if task.type != AgentTaskType.apply:
        return True
    app = await session.get(Application, task.application_id) if task.application_id else None
    packet = await approved_packet(session, app) if app is not None else None
    if app is not None and packet is not None and app.stage == Stage.ready \
            and task.payload.get("packet_hash") == packet.content_hash:
        return True
    task.status = AgentTaskStatus.cancelled
    task.result = {"outcome": "cancelled", "reason": "the application is no longer approved and ready for this "
                                                     "packet"}
    await audit.record(session, actor="system", action="gateway.task_cancelled", subject_type="agent_task",
                       subject_id=task.id, detail={"reason": task.result["reason"], "at": at.isoformat()})
    return False


async def _claim(session: AsyncSession, token: ApiToken, task: AgentTask, at: datetime, dry_run: bool) -> bool:
    """Claim ``task`` for ``token``. Apply tasks are claimed through the browser channel, which refuses (and
    withdraws the task) when the application has an open or sent attempt."""
    if task.type == AgentTaskType.apply:
        try:
            await browser.mark_task_claimed(session, task.id, token_id=token.id, now=at)
        except browser.BrowserError:
            return False
        if dry_run:  # a rehearsal is not an attempt
            task.attempts -= 1
    else:
        task.status = AgentTaskStatus.claimed
        task.claimed_by_token_id, task.claimed_at, task.heartbeat_at = token.id, at, at
        if not dry_run:
            task.attempts += 1
    if dry_run:
        task.payload = {**task.payload, "dry_run": True}
    await session.flush()
    return True


async def next_task(session: AsyncSession, token: ApiToken, body: NextTaskIn, *, at: datetime) -> NextTaskOut:
    require_active(token)
    types = _allowed_types(token, body.kinds)
    if not types:
        raise GatewayError("scope_missing", "this token may not take any of the task kinds asked for")
    await expire_leases(session, at=at)
    held = (await session.scalars(select(AgentTask).where(
        AgentTask.claimed_by_token_id == token.id, AgentTask.status == AgentTaskStatus.claimed)
        .order_by(AgentTask.claimed_at))).all()
    if len(held) >= int(await setting(session, "runners.max_claimed_tasks")):
        task = held[0]  # resume what this runner already holds, from its checkpoint
        task.heartbeat_at = at
        return await describe(session, task)
    hour = int(await session.scalar(select(func.count()).select_from(AgentTask).where(
        AgentTask.claimed_by_token_id == token.id, AgentTask.claimed_at > at - timedelta(hours=1))) or 0)
    if hour >= int(await setting(session, "runners.claims_per_hour")):
        raise GatewayError("rate_limited", "this runner has claimed its hourly limit of tasks")
    if token.runner_kind == "server" and not await setting(session, "runners.server_runner_enabled"):
        return NextTaskOut(task_id=None)
    if await setting(session, "automation.paused"):
        types = [t for t in types if t != AgentTaskType.apply]
        if not types:
            return NextTaskOut(task_id=None)
    for _ in range(20):
        task = await session.scalar(
            select(AgentTask).where(
                AgentTask.status == AgentTaskStatus.queued, AgentTask.type.in_(types),
                or_(AgentTask.preferred_runner.is_(None), AgentTask.preferred_runner == token.runner_kind),
                or_(AgentTask.payload["resume_runner_token_id"].astext.is_(None),
                    AgentTask.payload["resume_runner_token_id"].astext == str(token.id)))
            .order_by(AgentTask.created_at).limit(1).with_for_update(skip_locked=True))
        if task is None:
            return NextTaskOut(task_id=None)
        if not await _still_wanted(session, task, at) or not await _claim(session, token, task, at, body.dry_run):
            continue
        await audit.record(session, actor=f"runner:{token.name}", action="gateway.task_claimed",
                           subject_type="agent_task", subject_id=task.id,
                           detail={"type": task.type.value, "runner_id": str(token.id), "attempt": task.attempts,
                                   "resumed": bool(task.payload.get("resume")), "dry_run": body.dry_run})
        return await describe(session, task)
    return NextTaskOut(task_id=None)


# ----- save_checkpoint ---------------------------------------------------------------------------


async def save_checkpoint(session: AsyncSession, token: ApiToken, body: SaveCheckpointIn, *,
                          at: datetime) -> SaveCheckpointOut:
    task = await own_task(session, token, body.task_id, at=at)
    max_steps = int(await setting(session, "automation.agent_max_steps"))
    task.steps_used += 1
    state = body.state.model_copy(update={"step": _bound(body.state.step, 200), "url": _bound(body.state.url, 2000),
                                          "screenshot_ref": _bound(body.state.screenshot_ref, 500),
                                          "fields_filled": [f[:200] for f in body.state.fields_filled[:200]]})
    task.checkpoint = state
    if task.steps_used > max_steps:
        task.status = AgentTaskStatus.failed
        task.result = {"outcome": "failed", "reason": f"step limit of {max_steps} reached"}
        await audit.record(session, actor=f"runner:{token.name}", action="gateway.step_limit",
                           subject_type="agent_task", subject_id=task.id, detail={"steps": task.steps_used})
        return SaveCheckpointOut(ok=False, steps_used=task.steps_used, steps_left=0)
    return SaveCheckpointOut(ok=True, steps_used=task.steps_used, steps_left=max_steps - task.steps_used)


def is_dry_run(task: AgentTask) -> bool:
    return bool(task.payload.get("dry_run"))


async def give_back(session: AsyncSession, task: AgentTask, *, reason: str, actor: str, at: datetime,
                    same_runner: bool = False) -> None:
    """Back to the queue with its checkpoint (a dry run, a clean shutdown, a released claim)."""
    holder = task.claimed_by_token_id
    task.status = AgentTaskStatus.queued
    task.claimed_by_token_id = task.claimed_at = task.heartbeat_at = None
    task.payload = {**{k: v for k, v in task.payload.items() if k != "dry_run"}, "resume": True,
                    "resume_runner_token_id": str(holder) if same_runner and holder else None}
    await session.flush()
    await audit.record(session, actor=actor, action="gateway.task_released", subject_type="agent_task",
                       subject_id=task.id, detail={"reason": reason, "at": at.isoformat()})


async def release_task(session: AsyncSession, token: ApiToken, body: ReleaseTaskIn, *,
                       at: datetime) -> ReleaseTaskOut:
    task = await own_task(session, token, body.task_id, at=at)
    if task.type == AgentTaskType.apply and not is_dry_run(task) and task.application_id \
            and await open_attempt(session, task.application_id) is not None:
        raise GatewayError("permit_given", "a submit permit was given for this task: report the result instead")
    await give_back(session, task, reason=clip(body.reason, 500) or "released", actor=f"runner:{token.name}", at=at)
    return ReleaseTaskOut(released=True, task_status=task.status.value)


async def enqueue_check(session: AsyncSession, job: Job, *, actor: str = "system") -> AgentTask:
    """Ask a runner whether a posting is still open (its answer comes back through ``report_check``)."""
    url = job.apply_url
    domain = packets.domain_of(url)
    if not url or not domain:
        raise ValueError("the job has no posting URL to check")
    task = AgentTask(type=AgentTaskType.check_posting, status=AgentTaskStatus.queued,
                     preferred_runner=await route_for(session, job) if job.apply_url else "pc",
                     payload={"job_id": str(job.id), "posting_url": url, "domain": domain})
    session.add(task)
    await session.flush()
    await audit.record(session, actor=actor, action="gateway.task_queued", subject_type="agent_task",
                       subject_id=task.id, detail={"type": "check_posting", "job_id": str(job.id)})
    return task


async def report_check(session: AsyncSession, token: ApiToken, body: ReportCheckIn, *,
                       at: datetime) -> ReportCheckOut:
    """Unknown is not yes: only open or closed moves the job; ``closed`` needs evidence, else unknown."""
    task = await own_task(session, token, body.task_id, at=at, types=(AgentTaskType.check_posting,))
    require_scope(token, scope_for(task))
    status = body.status
    evidence = clip(body.evidence, 1000)
    if status == "closed" and not evidence:
        status = "unknown"
    detail = {"reported": body.status, "recorded": status, "evidence": evidence,
              "screenshot_ref": clip(body.screenshot_ref, 500), "runner": token.name}
    if is_dry_run(task):
        await give_back(session, task, reason="dry run finished", actor=f"runner:{token.name}", at=at)
        return ReportCheckOut(recorded=False, availability=status)
    job = await session.get(Job, uuid.UUID(task.payload["job_id"])) if task.payload.get("job_id") else None
    if job is not None:
        job.availability = Availability(status)
        if status != "unknown":
            job.last_checked_at = at
        await audit.record(session, actor=f"runner:{token.name}", action="job.availability_checked",
                           subject_type="job", subject_id=job.id, detail=detail)
    task.status, task.result = AgentTaskStatus.done, {"outcome": "checked", **detail}
    await session.flush()
    return ReportCheckOut(recorded=job is not None, availability=status)


def _bound(value: Any, limit: int) -> Any:
    return value[:limit] if isinstance(value, str) else value


def scope_for(task: AgentTask) -> str:
    return SCOPE_OF[task.type]


async def check_scope(token: ApiToken, task: AgentTask) -> None:
    require_scope(token, scope_for(task))
