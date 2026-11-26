"""``raise_blocker``: hand a step to the owner and free the runner (DESIGN.md 8.3, 8.4, 18.1, 18.6 gate 5).

Invariants, never settings:

- Every blocker is a pending action carrying the checkpoint and **what the runner was already given**, so
  the owner sees what left before the stop.
- A redirect off the destination, a page asking for something outside the application, or a declaration
  revokes any unused permit for that application at once. A permit already given and not reported is
  settled as not sent: the runner stopped before submitting.
- Sign-in and account blockers go to ``accounts.register_blocker``: grouped by portal tenant, so one sign-in
  unlocks every task waiting on it; per-task kinds (CAPTCHA, verification code, ...) are one action each. The
  owner's "continue" sends the task back to the same runner (``accounts.continue_blocker``).
- The runner's ``detail`` is page-derived text: stored as data, bounded, never followed.
- Whether the runner moves on or waits is ``automation.blocker_handling``.
"""

from __future__ import annotations

import contextlib
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import accounts, packets, permits
from app.apply.channels import browser
from app.core import audit
from app.gateway.common import clip, own_task, setting
from app.gateway.tasks import give_back, is_dry_run, open_attempt
from app.gateway.tools import RaiseBlockerIn, RaiseBlockerOut
from app.models.applications import AgentTask, AgentTaskStatus, Application, PendingAction, PendingActionType
from app.models.platform import ApiToken
from app.models.search import Job

TYPES = {
    "sign_in": PendingActionType.sign_in, "verification_code": PendingActionType.sign_in,
    "create_account": PendingActionType.create_account,
    "captcha": PendingActionType.captcha, "assessment": PendingActionType.assessment,
    "declaration": PendingActionType.declaration, "unsupported_form": PendingActionType.unsupported_form,
    "redirect_off_domain": PendingActionType.redirect_off_domain,
    "unknown_question": PendingActionType.unknown_question, "page_instruction": PendingActionType.page_instruction,
}
TITLES = {
    "sign_in": "Sign in at {domain}", "verification_code": "A verification code is needed at {domain}",
    "create_account": "Create an account at {domain}",
    "captcha": "Solve a CAPTCHA at {domain}", "assessment": "An assessment is asked for at {domain}",
    "declaration": "A declaration needs you at {domain}", "unsupported_form": "The form at {domain} needs you",
    "redirect_off_domain": "The form left {domain}", "unknown_question": "A question at {domain} needs you",
    "page_instruction": "The page at {domain} asked for something outside the application",
}
STOP_TYPES = frozenset({"redirect_off_domain", "page_instruction", "declaration"})
PORTAL_TYPES = frozenset({"sign_in", "create_account", "verification_code"})


async def _stop_outward(session: AsyncSession, task: AgentTask, app: Application, why: str, actor: str,
                        at: datetime) -> None:
    await permits.revoke(session, application_id=app.id, reason=why, actor=actor, now=at)
    attempt = await open_attempt(session, app.id)
    if attempt is not None and str(attempt.id) == task.payload.get("attempt_id"):
        # Cleared but stopped before Submit: the runner's word that nothing went out (settled as not sent).
        with contextlib.suppress(browser.UnpermittedReport):
            await browser.record_result(session, attempt, "failed", None, task_id=task.id,
                                        detail=f"runner stopped before submitting: {why}", actor=actor, now=at)


async def raise_blocker(session: AsyncSession, token: ApiToken, body: RaiseBlockerIn, *,
                        at: datetime) -> RaiseBlockerOut:
    task = await own_task(session, token, body.task_id, at=at)
    actor = f"runner:{token.name}"
    domain = str(task.payload.get("domain") or "the site")
    app = await session.get(Application, task.application_id) if task.application_id else None
    job = await session.get(Job, app.job_id) if app else None
    url = clip(body.url, 2000)
    detail = {"kind": body.type, "blocker": body.type, "detail": clip(body.detail), "url": url,
              "url_domain": packets.domain_of(url) if url else None, "runner": token.name,
              "runner_kind": token.runner_kind, "task_type": task.type.value,
              "released": task.released.get("given") or [], "dry_run": is_dry_run(task)}
    action_id = None
    if body.type in accounts.BLOCKER_KINDS and job is not None:
        registered = await accounts.register_blocker(session, kind=body.type, job=job, task_id=task.id,
                                                     runner_id=token.id, detail=detail)
        action_id = registered.id
    if action_id is None:
        group = f"portal:{domain}" if body.type in PORTAL_TYPES else None
        action = PendingAction(type=TYPES[body.type], application_id=task.application_id, agent_task_id=task.id,
                               group_key=group, title=TITLES[body.type].format(domain=domain)[:300], detail=detail,
                               checkpoint=task.checkpoint, deadline=_deadline(job))
        session.add(action)
        await session.flush()
        action_id = action.id
    if app is not None and body.type in STOP_TYPES and not is_dry_run(task):
        await _stop_outward(session, task, app, f"{body.type.replace('_', ' ')} at {domain}", actor, at)
    handling = str(await setting(session, "automation.blocker_handling"))
    if is_dry_run(task):
        await give_back(session, task, reason=f"dry run blocked: {body.type}", actor=actor, at=at)
    else:
        task.status = AgentTaskStatus.blocked
        task.result = {"outcome": "blocked", "blocker": body.type}
    await session.flush()
    await audit.record(session, actor=actor, action="gateway.blocker_raised", subject_type="agent_task",
                       subject_id=task.id, detail={**detail, "pending_action_id": str(action_id)})
    return RaiseBlockerOut(pending_action_id=str(action_id),
                           next="wait" if handling == "handoff_stop_runner" else "move_on")


def _deadline(job: Job | None) -> datetime | None:
    if job is None or job.deadline is None:
        return None
    from app.apply import stages

    return stages._as_datetime(job.deadline)
