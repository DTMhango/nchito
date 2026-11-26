"""Portal accounts and the sign-in handoff (DESIGN.md 8.4, 6.1, 14).

Agents never create accounts or type passwords: the owner does, and the system makes it quick and picks up
where it stopped. Nothing here stores a password or any secret; ``PortalAccount`` is a registry of *where*
the owner has an account and on which runner the session lives.

For the gateway (the apply runner stream) the entry points are:

- ``needs_account(session, job)`` -> ``AccountNeed`` (``yes`` / ``no`` / ``unknown``; unknown is never "no") and
  ``preferred_runner_kind(session, job)`` (``"pc"`` or ``"server"``, ``None`` when no account is needed).
- ``register_blocker(session, *, kind, job, task_id, runner_id, detail)``: call it from ``raise_blocker``.
  ``kind`` is one of ``BLOCKER_KINDS``; it creates (or joins) the pending action and the notification. The
  action's ``detail`` carries ``kind``, ``portal_key``, ``task_id``, ``runner_id`` (also ``tasks`` and
  ``applications`` lists when several are waiting on one tenant).

One pending action exists per portal tenant for ``sign_in`` and ``create_account`` (every application waiting on
it is listed, new roles join it). Per-task blockers (CAPTCHA, verification code, assessment, declaration,
unsupported form) get one action per task.

"I've signed in, continue" (``continue_blocker``) marks the account signed in on that runner, re-checks the
posting and duplicates for each waiting application, and requeues each task for the same runner with its
checkpoint. A submit permit is still required afterwards. "I can't / skip" is ``give_up``.
"""

from __future__ import annotations

import enum
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.models.applications import (
    AgentTask,
    AgentTaskStatus,
    Application,
    Channel,
    PendingAction,
    PendingActionType,
    PendingStatus,
    PortalAccount,
    PortalAccountStatus,
    Stage,
)
from app.models.platform import Notification
from app.models.search import Assessment, Availability, Job
from app.ops import notifications

log = logging.getLogger(__name__)

TENANT_KINDS = ("sign_in", "create_account")
SUSPICIOUS_KINDS = ("redirect_off_domain", "page_instruction")
TASK_KINDS = ("verification_code", "captcha", "assessment", "declaration", "unsupported_form", *SUSPICIOUS_KINDS)
BLOCKER_KINDS = TENANT_KINDS + TASK_KINDS
# The pending action type each blocker kind is raised as (the type enum is shared; ``detail.kind`` is exact).
TYPE_FOR_KIND: dict[str, PendingActionType] = {
    "sign_in": PendingActionType.sign_in, "create_account": PendingActionType.create_account,
    "verification_code": PendingActionType.sign_in, "captcha": PendingActionType.captcha,
    "assessment": PendingActionType.assessment, "declaration": PendingActionType.declaration,
    "unsupported_form": PendingActionType.unsupported_form,
    "redirect_off_domain": PendingActionType.redirect_off_domain,
    "page_instruction": PendingActionType.page_instruction,
}
ACCOUNT_TYPES = tuple(dict.fromkeys(TYPE_FOR_KIND.values()))
# What the owner may do with each blocker (invariant, not a setting). ``continue``: "I've done my part, continue"
# (the task goes back to the same runner). ``continue_acknowledged``: a suspicious page (a redirect off the
# destination, or a page asking for something outside the application) may be continued only with an explicit
# acknowledgement, which is audited. ``manual_handoff`` / ``skipped``: ``give_up``.
CHOICES: dict[str, tuple[str, ...]] = {
    **{k: ("continue", "manual_handoff", "skipped") for k in (
        "sign_in", "create_account", "verification_code", "captcha", "assessment", "declaration")},
    "unsupported_form": ("manual_handoff", "skipped"),
    **{k: ("manual_handoff", "skipped", "continue_acknowledged") for k in SUSPICIOUS_KINDS},
}
_LEGACY_CONTINUABLE = (PendingActionType.sign_in, PendingActionType.create_account, PendingActionType.captcha)
ACTIVE_STAGES = stages.PRE_SUBMIT
MAX_LISTED = 3

# Host suffix -> portal, for postings whose apply method does not name the system.
_HOST_PORTALS = (("myworkdayjobs.com", "workday"), ("icims.com", "icims"), ("taleo.net", "taleo"),
                 ("successfactors.com", "successfactors"), ("successfactors.eu", "successfactors"))
_LOCALE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2})?$")
_NO_METHOD = ("", "unknown", "other")


class AccountError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class AccountNeed(enum.StrEnum):
    yes = "yes"
    no = "no"
    unknown = "unknown"


@dataclass(frozen=True)
class PortalRef:
    portal: str
    tenant: str
    url: str

    @property
    def key(self) -> str:
        return f"{self.portal}:{self.tenant}"

    @property
    def group_key(self) -> str:
        return f"portal:{self.key}"


# ----- identifying the portal tenant ----------------------------------------------------------


def portal_ref(job: Job) -> PortalRef | None:
    """The portal tenant a role is applied for in: ATS type plus tenant host (a Workday site adds its site
    name, a SuccessFactors company its id). ``None`` when the posting names no usable apply link."""
    parts = urlsplit((job.apply_url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return None
    method = (job.apply_method or "").lower()
    portal = method if method not in _NO_METHOD and method != "email" else None
    if portal is None:
        portal = next((name for suffix, name in _HOST_PORTALS if host == suffix or host.endswith("." + suffix)), None)
    if portal is None:
        return None
    tenant, url = host, f"{parts.scheme}://{host}"
    if portal == "workday":
        site = next((p for p in parts.path.split("/") if p and not _LOCALE.match(p)), None)
        if site and site not in ("job", "wday"):
            tenant, url = f"{host}/{site}", f"{parts.scheme}://{host}/{site}"
    elif portal == "successfactors":
        company = (parse_qs(parts.query).get("company") or [None])[0]
        if company:
            tenant = f"{host}/{company.lower()}"
    return PortalRef(portal[:60].lower(), tenant[:200].lower(), url)


def blocker_ref(job: Job) -> PortalRef | None:
    """The tenant a runner's sign-in blocker is grouped by: ``portal_ref``, else the apply link's site (an
    applicant-tracking host adds its first path segment, the employer's board). Every application waiting on one
    site's sign-in then shares one action, so its count is the number actually waiting."""
    ref = portal_ref(job)
    if ref is not None:
        return ref
    parts = urlsplit((job.apply_url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return None
    portal = _portal_from_url(job.apply_url) or "site"
    segment = next((p for p in parts.path.split("/") if p), None)
    tenant = f"{host}/{segment.lower()}" if portal != "site" and segment else host
    url = f"{parts.scheme}://{host}/{segment}" if portal != "site" and segment else f"{parts.scheme}://{host}"
    return PortalRef(portal[:60].lower(), tenant[:200], url)


def _portal_from_url(url: str | None) -> str | None:
    from app.pipeline import normalise

    host = (urlsplit((url or "").strip()).hostname or "").lower()
    by_host = next((name for suffix, name in _HOST_PORTALS if host == suffix or host.endswith("." + suffix)), None)
    return by_host or normalise.ats_from_url(url)


def assess_need(job: Job, *, required: list[str], account_free: list[str]) -> AccountNeed:
    """Pure: does applying for this role need an account? An unstated or unrecognised case is ``unknown``."""
    method = (job.apply_method or "").lower()
    if method in _NO_METHOD:  # the posting names no system: use the one recognised from the apply link
        method = _portal_from_url(job.apply_url) or method
    facet = job.facets.needs_account.value if job.facets is not None else "not_stated"
    if facet == "yes" or method in required:
        return AccountNeed.yes
    if facet == "no" or method in account_free:
        return AccountNeed.no
    return AccountNeed.unknown


async def needs_account(session: AsyncSession, job: Job) -> AccountNeed:
    values = await settings_service.values(session)
    return assess_need(job, required=list(values["accounts.portals_requiring_account"]),
                       account_free=list(values["accounts.account_free_methods"]))


async def preferred_runner_kind(session: AsyncSession, job: Job) -> str | None:
    """Where to send a role: the runner that holds its portal session, else (for roles that need or may need
    an account) the configured runner, local by default. ``None``: no preference (an account-free form)."""
    need = await needs_account(session, job)
    if need == AccountNeed.no:
        return None
    ref = portal_ref(job)
    account = await get_account(session, ref) if ref else None
    if account is not None and account.status == PortalAccountStatus.signed_in and account.signed_in_runner in (
            "pc", "server"):
        return account.signed_in_runner
    return str(await settings_service.get_value(session, "accounts.runner_for_account_roles"))


# ----- the registry ---------------------------------------------------------------------------


async def get_account(session: AsyncSession, ref: PortalRef) -> PortalAccount | None:
    return await session.scalar(select(PortalAccount).where(
        PortalAccount.portal == ref.portal, PortalAccount.tenant == ref.tenant))


async def _mark_signed_in(session: AsyncSession, ref: PortalRef, runner: str, actor: str, now: datetime) -> None:
    account = await get_account(session, ref)
    if account is None:
        account = PortalAccount(portal=ref.portal, tenant=ref.tenant, url=ref.url)
        session.add(account)
    account.status = PortalAccountStatus.signed_in
    account.signed_in_runner = runner[:120]
    account.last_sign_in_at = now
    await session.flush()
    await audit.record(session, actor=actor, action="portal_account.signed_in", subject_type="portal_account",
                       subject_id=account.id, detail={"key": ref.key, "runner": runner})


# ----- pending actions --------------------------------------------------------------------------


def _entry(app_id: uuid.UUID, job: Job) -> dict[str, Any]:
    return {"application_id": str(app_id), "job_id": str(job.id), "title": job.title, "employer": job.employer,
            "deadline": job.deadline.isoformat() if job.deadline else None}


def _deadline_of(raw: str | None) -> datetime | None:
    return stages._as_datetime(date.fromisoformat(raw)) if raw else None


def _nearest(entries: list[dict[str, Any]]) -> datetime | None:
    found = [d for d in (_deadline_of(e.get("deadline")) for e in entries) if d is not None]
    return min(found) if found else None


def _waiting_phrase(count: int) -> str:
    return f"{count} application is waiting" if count == 1 else f"{count} applications are waiting"


async def _title(session: AsyncSession, kind: str, entries: list[dict[str, Any]]) -> str:
    key = "accounts.create_title" if kind == "create_account" else "accounts.sign_in_title"
    template = str(await settings_service.get_value(session, key))
    employer = entries[0]["employer"] if entries else "the employer"
    count = len(entries)
    if kind in TENANT_KINDS:
        return template.format(employer=employer, count=count, waiting=_waiting_phrase(count))[:300]
    label = {"verification_code": "Enter the verification code", "captcha": "Solve the CAPTCHA",
             "assessment": "Complete the assessment", "declaration": "Make the declaration",
             "unsupported_form": "Fill in the form by hand",
             "redirect_off_domain": "Check where the form went",
             "page_instruction": "Check what the page asked"}[kind]
    return f"{label} for {entries[0]['title']} at {employer}"[:300] if entries else label


def _is_account_action(action: PendingAction) -> bool:
    return (action.detail or {}).get("kind") in BLOCKER_KINDS


def choices_for(action: PendingAction) -> list[str]:
    """The owner's choices on an open blocker action (empty for anything else)."""
    if action.status != PendingStatus.open:
        return []
    kind = (action.detail or {}).get("kind")
    if kind in CHOICES:
        return list(CHOICES[kind])
    return ["continue"] if action.type in _LEGACY_CONTINUABLE and kind is None else []


def continue_choice(action: PendingAction) -> str | None:
    """``continue``, ``continue_acknowledged`` (needs the owner's explicit acknowledgement) or ``None``."""
    return next((c for c in choices_for(action) if c.startswith("continue")), None)


async def _open_for_group(session: AsyncSession, group_key: str) -> PendingAction | None:
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.group_key == group_key, PendingAction.status == PendingStatus.open,
        PendingAction.type.in_((PendingActionType.sign_in, PendingActionType.create_account)))
        .order_by(PendingAction.created_at))
    return next((a for a in rows if (a.detail or {}).get("kind") in TENANT_KINDS), None)


def _runner_phrase(runner_kind: str | None) -> str:
    return "server runner's" if runner_kind == "server" else "PC runner's"


def _body(action: PendingAction, now: datetime, *, reminder: bool) -> str:
    d = action.detail
    entries = d.get("applications", [])
    names = [f"{e['title']} at {e['employer']}" for e in entries[:MAX_LISTED]]
    if len(entries) > MAX_LISTED:
        names.append(f"{len(entries) - MAX_LISTED} more")
    parts = [f"Open {d.get('portal_url') or 'the portal'} in the {_runner_phrase(d.get('runner_kind'))} browser "
             f"profile."]
    if names:
        parts.append("Waiting: " + "; ".join(names) + ".")
    if action.deadline is not None:
        left = action.deadline - now
        parts.append(f"Nearest deadline {action.deadline.date().isoformat()}"
                     + (f" ({max(int(left.total_seconds() // 3600), 0)} h left)." if reminder else "."))
    return " ".join(parts)


async def _notify(session: AsyncSession, action: PendingAction, now: datetime, *, key: str,
                  reminder: bool = False) -> bool:
    """One notification through the existing notifier. Honours the channel and event settings; quiet hours are
    applied at delivery. The first message uses the key ``collect`` would use, so it is never sent twice."""
    values = await settings_service.values(session)
    if not values["notifications.channels"] or "pending_action" not in values["notifications.events"]:
        return False
    title = ("Reminder: " if reminder else "") + action.title
    made = await notifications.notify(
        session, kind="pending_action", key=key, title=title, body=_body(action, now, reminder=reminder),
        link=f"/today?action={action.id}",
        payload={"pending_action_id": str(action.id), "action_type": action.type.value,
                 "account_kind": action.detail.get("kind")})
    return made is not None


async def _crossed_offset(session: AsyncSession, deadline: datetime | None, now: datetime) -> int | None:
    """The tightest reminder offset (hours) already crossed for ``deadline``."""
    if deadline is None or deadline <= now:
        return None
    offsets = [int(h) for h in await settings_service.get_value(session, "accounts.reminder_offsets_hours")]
    crossed = [h for h in offsets if now >= deadline - timedelta(hours=h)]
    return min(crossed) if crossed else None


async def _refresh(session: AsyncSession, action: PendingAction) -> None:
    entries = action.detail.get("applications", [])
    action.deadline = _nearest(entries)
    action.title = await _title(session, action.detail["kind"], entries)
    await session.flush()
    await _sync_notice(session, action)


async def _sync_notice(session: AsyncSession, action: PendingAction) -> None:
    """Keep the action's first message in step with who is waiting: a role that joins (or leaves) after the
    announcement updates the in-app notification, and the outbound one too while it is still undelivered."""
    notice = await session.scalar(select(Notification).where(Notification.dedupe_key == f"pending:{action.id}"))
    if notice is None:
        return
    notice.title = action.title[:notifications.MAX_TITLE]
    notice.body = _body(action, utcnow(), reminder=False)
    await session.flush()


async def _announce(session: AsyncSession, action: PendingAction, now: datetime) -> None:
    action.detail = {**action.detail, "announced": True,
                     "reminded_offset": await _crossed_offset(session, action.deadline, now)}
    await _notify(session, action, now, key=f"pending:{action.id}")
    await publish(session, "pending_action.created", {"pending_action_id": str(action.id)})


async def _runner_kind(session: AsyncSession, explicit: str | None, task: AgentTask | None) -> str:
    return explicit or (task.preferred_runner if task and task.preferred_runner else None) or str(
        await settings_service.get_value(session, "accounts.runner_for_account_roles"))


async def ensure_for_application(session: AsyncSession, app: Application, job: Job, *,
                                 now: datetime | None = None, announce: bool = True) -> PendingAction | None:
    """Known early (8.4): a role that needs an account raises (or joins) the one action for its tenant.
    Only a definite ``yes`` raises it; an unknown need waits for the runner to report a blocker."""
    now = now or utcnow()
    if await needs_account(session, job) != AccountNeed.yes or app.stage not in ACTIVE_STAGES:
        return None
    ref = portal_ref(job)
    if ref is None:
        return None
    account = await get_account(session, ref)
    if account is not None and account.status == PortalAccountStatus.signed_in:
        return None
    kind = "create_account" if account is None or account.status == PortalAccountStatus.none else "sign_in"
    existing = await _open_for_group(session, ref.group_key)
    if existing is not None:
        entries = list(existing.detail.get("applications", []))
        if any(e["application_id"] == str(app.id) for e in entries):
            return existing
        existing.detail = {**existing.detail, "applications": [*entries, _entry(app.id, job)]}
        await _refresh(session, existing)
        await audit.record(session, actor="system", action="portal_account.application_joined",
                           subject_type="pending_action", subject_id=existing.id,
                           detail={"application_id": str(app.id), "key": ref.key})
        return existing
    runner_kind = await _runner_kind(session, None, None)
    action = PendingAction(
        type=TYPE_FOR_KIND[kind], group_key=ref.group_key, title="", status=PendingStatus.open,
        detail={"kind": kind, "portal_key": ref.key, "portal_url": ref.url, "task_id": None, "runner_id": None,
                "runner_kind": runner_kind, "origin": "known_early", "applications": [_entry(app.id, job)],
                "tasks": []})
    session.add(action)
    await session.flush()
    await _refresh(session, action)
    if announce:
        await _announce(session, action, now)
    await audit.record(session, actor="system", action="portal_account.action_raised", subject_type="pending_action",
                       subject_id=action.id, detail={"key": ref.key, "kind": kind, "origin": "known_early"})
    return action


async def register_blocker(session: AsyncSession, *, kind: str, job: Job, task_id: uuid.UUID | str,
                           runner_id: uuid.UUID | str | None, detail: dict[str, Any] | None = None
                           ) -> PendingAction:
    """The gateway's ``raise_blocker`` calls this. Sign-in and create-account join the tenant's open action;
    the other kinds get one action per task. The caller commits."""
    if kind not in BLOCKER_KINDS:
        raise ValueError(f"unknown blocker kind {kind!r}; expected one of {BLOCKER_KINDS}")
    now = utcnow()
    detail = dict(detail or {})
    task = await session.get(AgentTask, uuid.UUID(str(task_id)))
    if task is None:
        raise AccountError("task not found", 404)
    ref = blocker_ref(job) if kind in TENANT_KINDS else portal_ref(job)
    app_id = task.application_id
    entry = _entry(app_id, job) if app_id else None
    task_entry = {"task_id": str(task.id), "runner_id": str(runner_id) if runner_id else None,
                  "application_id": str(app_id) if app_id else None}
    runner_kind = await _runner_kind(session, detail.get("runner_kind"), task)
    tenant_level = kind in TENANT_KINDS and ref is not None
    existing: PendingAction | None = None
    if tenant_level:
        assert ref is not None
        existing = await _open_for_group(session, ref.group_key)
    else:
        existing = await session.scalar(select(PendingAction).where(
            PendingAction.agent_task_id == task.id, PendingAction.status == PendingStatus.open,
            PendingAction.type == TYPE_FOR_KIND[kind]).order_by(PendingAction.created_at))
        if existing is not None and existing.detail.get("kind") != kind:
            existing = None
    if existing is not None:
        d = dict(existing.detail)
        tasks = [t for t in d.get("tasks", []) if t["task_id"] != str(task.id)] + [task_entry]
        entries = list(d.get("applications", []))
        if entry and not any(e["application_id"] == entry["application_id"] for e in entries):
            entries.append(entry)
        d.update(tasks=tasks, applications=entries, task_id=str(task.id), kind=kind,
                 runner_id=task_entry["runner_id"], runner_kind=runner_kind)
        existing.detail = d
        existing.type = TYPE_FOR_KIND[kind]
        existing.agent_task_id = existing.agent_task_id or task.id
        existing.checkpoint = existing.checkpoint or task.checkpoint
        await _refresh(session, existing)
        return existing
    d = {"kind": kind, "portal_key": ref.key if ref else None, "portal_url": ref.url if ref else job.apply_url,
         "task_id": str(task.id), "runner_id": task_entry["runner_id"], "runner_kind": runner_kind,
         "origin": "runner", "applications": [entry] if entry else [], "tasks": [task_entry],
         "note": detail.get("note") or detail.get("detail")}
    # What the gateway knows (the page URL, what the runner was already given) stays on the action, as data.
    d = {**{k: v for k, v in detail.items() if k not in d}, **d}
    action = PendingAction(
        type=TYPE_FOR_KIND[kind], title="", status=PendingStatus.open, agent_task_id=task.id,
        application_id=None if tenant_level else app_id, checkpoint=task.checkpoint, detail=d,
        group_key=ref.group_key if tenant_level and ref else task_group_key(task.id, kind))
    session.add(action)
    await session.flush()
    await _refresh(session, action)
    await _announce(session, action, now)
    await audit.record(session, actor="system", action="portal_account.blocker_raised",
                       subject_type="pending_action", subject_id=action.id,
                       detail={"kind": kind, "task_id": str(task.id), "key": ref.key if ref else None})
    return action


def task_group_key(task_id: uuid.UUID | str, kind: str) -> str:
    """Per-task blockers are one action per task *and kind*: a CAPTCHA and a verification code on one task are
    two actions, and continuing one never closes the other."""
    return f"task:{task_id}:{kind}"


# ----- continue ----------------------------------------------------------------------------------


async def _recheck(session: AsyncSession, app: Application, job: Job, now: datetime) -> str | None:
    """Why an application must not resume, or ``None``: posting expiry, duplicates, state."""
    from app.apply import dispatch

    if app.stage not in ACTIVE_STAGES:
        return f"the application is {app.stage.value}"
    if app.applied_at is not None:
        return "it has already been sent"
    other = await stages.blocking_application(session, job.id)
    if other is not None and other.id != app.id and other.applied_at is not None:
        return "another application for this role has already been sent"
    if job.conflict_state.value == "held":
        return "it is held behind a better role at the same employer"
    try:
        async with session.begin_nested():
            await dispatch._open_checker(session, job)
        await session.refresh(job)
    except Exception:  # an unreachable posting stays unknown; the permit gates decide later
        log.warning("open check failed while continuing application %s", app.id, exc_info=True)
    if job.availability == Availability.closed:
        return "the posting has closed"
    if job.deadline is not None and job.deadline < now.date():
        return "the deadline has passed"
    return None


def _task_entries(action: PendingAction) -> list[dict[str, Any]]:
    tasks = list(action.detail.get("tasks", []))
    if action.agent_task_id and not any(t["task_id"] == str(action.agent_task_id) for t in tasks):
        tasks.append({"task_id": str(action.agent_task_id), "runner_id": action.detail.get("runner_id"),
                      "application_id": str(action.application_id) if action.application_id else None})
    return tasks


async def continue_blocker(session: AsyncSession, action: PendingAction, *, actor: str, note: str | None = None,
                           now: datetime | None = None, acknowledged: bool = False) -> list[PendingAction]:
    """'I've signed in (or done my part), continue'. Returns the actions that closed. A suspicious-page blocker
    (``SUSPICIOUS_KINDS``) continues only with ``acknowledged``; the acknowledgement is audited."""
    from app.apply.owner_actions import CONTINUABLE, ResolveError, _close

    choice = continue_choice(action)
    if choice is None:
        raise ResolveError(f"a {(action.detail or {}).get('kind') or action.type.value} blocker cannot be continued; "
                           "apply yourself or skip", 422, code="not_continuable")
    if choice == "continue_acknowledged":
        if not acknowledged:
            raise ResolveError("confirm you checked the page and it is safe to continue", 422,
                               code="acknowledgement_required")
        await audit.record(session, actor=actor, action="pending_action.suspicious_page_acknowledged",
                           subject_type="pending_action", subject_id=action.id,
                           detail={"kind": action.detail.get("kind"), "url": action.detail.get("url"),
                                   "acknowledged": True, "note": note})
    now = now or utcnow()
    closed = [action]
    if action.group_key:
        closed += list((await session.scalars(select(PendingAction).where(
            PendingAction.group_key == action.group_key, PendingAction.status == PendingStatus.open,
            PendingAction.type.in_(CONTINUABLE), PendingAction.id != action.id))).all())
    verdicts: dict[str, str | None] = {}
    for a in closed:
        d = a.detail or {}
        runner = str(d.get("runner_kind") or await _runner_kind(session, None, None))
        ref = _ref_from(d)
        if d.get("kind") in TENANT_KINDS and ref is not None:
            await _mark_signed_in(session, ref, runner, actor, now)
        waiting = {e["application_id"] for e in d.get("applications", [])}
        if a.application_id:
            waiting.add(str(a.application_id))
        for raw in waiting:
            if raw not in verdicts:
                app = await session.get(Application, uuid.UUID(raw))
                job = await session.get(Job, app.job_id) if app else None
                verdicts[raw] = "the application no longer exists" if app is None or job is None else await _recheck(
                    session, app, job, now)
        resumed: list[str] = []
        for t in _task_entries(a):
            task = await session.get(AgentTask, uuid.UUID(t["task_id"]))
            if task is None or task.status not in (AgentTaskStatus.blocked, AgentTaskStatus.claimed):
                continue
            reason = verdicts.get(t.get("application_id") or "")
            if reason:
                task.status = AgentTaskStatus.cancelled
                task.result = {"cancelled": reason, "by": "portal_continue"}
                continue
            if await _other_open_blocker(session, task.id, closing={c.id for c in closed}):
                continue  # another blocker on this task still needs the owner: it stays blocked
            # Back to the same runner, from its checkpoint; the submit permit is still required.
            token = t.get("runner_id") or (str(task.claimed_by_token_id) if task.claimed_by_token_id else None)
            task.status = AgentTaskStatus.queued
            task.checkpoint = a.checkpoint or task.checkpoint
            task.payload = {**task.payload, "resume": True, "resume_runner_token_id": token,
                            "resume_runner_kind": runner}
            resumed.append(str(task.id))
        not_resumed = [{"application_id": k, "reason": v} for k, v in verdicts.items() if v and k in waiting]
        for item in not_resumed:
            await stages.add_event(session, uuid.UUID(item["application_id"]), "portal_continue_refused", actor,
                                   {"reason": item["reason"], "pending_action_id": str(a.id)})
        via = None if a is action else str(action.id)
        await _close(session, a, {"resolution": "continue", "note": note, "via": via, "runner": runner,
                                  "resumed_tasks": resumed, "not_resumed": not_resumed,
                                  **({"acknowledged": True} if choice == "continue_acknowledged" else {})},
                     actor, now)
    return closed


async def _other_open_blocker(session: AsyncSession, task_id: uuid.UUID, *, closing: set[uuid.UUID]) -> bool:
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.status == PendingStatus.open, PendingAction.id.not_in(closing)))
    tid = str(task_id)
    return any(a.agent_task_id == task_id or any(t.get("task_id") == tid for t in (a.detail or {}).get("tasks", []))
               for a in rows if _is_account_action(a))


def _ref_from(detail: dict[str, Any]) -> PortalRef | None:
    key = detail.get("portal_key")
    if not key or ":" not in key:
        return None
    portal, tenant = key.split(":", 1)
    return PortalRef(portal, tenant, detail.get("portal_url") or f"https://{tenant}")


# ----- "I can't / skip" ---------------------------------------------------------------------------


@dataclass
class GiveUpResult:
    outcome: str
    handled: list[str] = field(default_factory=list)
    remaining: int = 0
    closed: bool = False


async def give_up(session: AsyncSession, action: PendingAction, *, outcome: str,
                  application_ids: list[uuid.UUID] | None, actor: str, note: str | None = None,
                  now: datetime | None = None) -> GiveUpResult:
    """The owner cannot (or will not) get past the blocker: move the chosen waiting applications (default all)
    to manual handoff (the owner applies by hand) or skip them."""
    from app.apply.owner_actions import ResolveError, _close

    if outcome not in ("manual_handoff", "skipped"):
        raise ResolveError("outcome must be manual_handoff or skipped", 422)
    if action.status != PendingStatus.open or not _is_account_action(action):
        raise ResolveError("this is not an open sign-in request", 409)
    now = now or utcnow()
    d = dict(action.detail)
    entries = list(d.get("applications", []))
    if action.application_id and not any(e["application_id"] == str(action.application_id) for e in entries):
        entries.append({"application_id": str(action.application_id)})
    wanted = {str(i) for i in application_ids} if application_ids else {e["application_id"] for e in entries}
    unknown = wanted - {e["application_id"] for e in entries}
    if unknown:
        raise ResolveError("an application is not waiting on this action", 422)
    result = GiveUpResult(outcome)
    for raw in sorted(wanted):
        app = await session.get(Application, uuid.UUID(raw))
        if app is None:
            continue
        if outcome == "skipped":
            try:
                await stages.transition(session, app, Stage.skipped, actor=actor, via="owner",
                                        why=note or "skipped: could not get past the portal sign-in", now=now)
            except stages.IllegalTransition as exc:
                raise ResolveError(exc.reason, 409) from exc
        else:
            app.channel = Channel.manual
            await stages.add_event(session, app.id, "portal_manual_handoff", actor,
                                   {"pending_action_id": str(action.id), "note": note})
        for t in _task_entries(action):
            if t.get("application_id") == raw:
                task = await session.get(AgentTask, uuid.UUID(t["task_id"]))
                if task is not None and task.status in (AgentTaskStatus.blocked, AgentTaskStatus.claimed,
                                                        AgentTaskStatus.queued):
                    task.status = AgentTaskStatus.cancelled
                    task.result = {"cancelled": outcome, "by": "portal_give_up"}
        result.handled.append(raw)
    d["applications"] = [e for e in entries if e["application_id"] not in wanted]
    d["tasks"] = [t for t in _task_entries(action) if t.get("application_id") not in wanted]
    action.detail = d
    result.remaining = len(d["applications"])
    await audit.record(session, actor=actor, action=f"portal_account.{outcome}", subject_type="pending_action",
                       subject_id=action.id, detail={"applications": result.handled, "note": note})
    if result.remaining == 0:
        await _close(session, action, {"resolution": outcome, "note": note, "applications": result.handled},
                     actor, now)
        result.closed = True
    else:
        await _refresh(session, action)
    return result


# ----- the periodic tick ---------------------------------------------------------------------------


@dataclass
class TickResult:
    raised: int = 0
    joined: int = 0
    closed: int = 0
    reminded: int = 0


async def reconcile_actions(session: AsyncSession, now: datetime, *, group_key: str | None = None) -> int:
    """Drop applications that no longer wait (sent, skipped, closed posting) from each open account action;
    close an action with nothing left, and a known-early one whose account is now signed in."""
    stmt = select(PendingAction).where(PendingAction.status == PendingStatus.open)
    if group_key:
        stmt = stmt.where(PendingAction.group_key == group_key)
    closed = 0
    for action in (await session.scalars(stmt)).all():
        if not _is_account_action(action):
            continue
        d = dict(action.detail)
        keep: list[dict[str, Any]] = []
        for e in d.get("applications", []):
            app = await session.get(Application, uuid.UUID(e["application_id"]))
            job = await session.get(Job, app.job_id) if app else None
            if app and job and app.stage in ACTIVE_STAGES and job.availability != Availability.closed:
                keep.append(e)
        gone = len(keep) != len(d.get("applications", []))
        d["applications"] = keep
        d["tasks"] = [t for t in d.get("tasks", []) if t.get("application_id") in {e["application_id"] for e in keep}]
        action.detail = d
        reason = None
        if not keep and (gone or not d.get("tasks")):
            reason = "nothing_waiting"
        elif d.get("origin") == "known_early" and not d.get("tasks") and (ref := _ref_from(d)) is not None:
            account = await get_account(session, ref)
            if account is not None and account.status == PortalAccountStatus.signed_in:
                reason = "account_ready"
        if reason:
            action.status, action.resolved_at = PendingStatus.expired, now
            action.resolution = {"resolution": reason}
            closed += 1
            await audit.record(session, actor="system", action="portal_account.action_expired",
                               subject_type="pending_action", subject_id=action.id, detail={"reason": reason})
        elif gone:
            await _refresh(session, action)
    await session.flush()
    return closed


async def raise_known_early(session: AsyncSession, now: datetime) -> tuple[int, int]:
    """Roles that passed the tailor threshold (or were approved) and need an account. Returns (raised, joined)."""
    threshold = int(await settings_service.get_value(session, "scoring.threshold_tailor"))
    rows = await session.execute(
        select(Application, Job, Assessment.score).join(Job, Job.id == Application.job_id)
        .outerjoin(Assessment, Assessment.id == Application.assessment_id)
        .where(Application.stage.in_(tuple(ACTIVE_STAGES)), Job.availability != Availability.closed))
    raised = joined = 0
    touched: dict[uuid.UUID, PendingAction] = {}
    for app, job, score in rows.all():
        if not (app.approved_packet_id is not None or (score is not None and score >= threshold)):
            continue
        ref = portal_ref(job)
        before = await _open_for_group(session, ref.group_key) if ref else None
        already = before is not None and any(
            e["application_id"] == str(app.id) for e in before.detail.get("applications", []))
        action = await ensure_for_application(session, app, job, now=now, announce=False)
        if action is None or already:
            continue
        touched[action.id] = action
        if before is None:
            raised += 1
        else:
            joined += 1
    for action in touched.values():  # announce once every waiting role has joined, so the message lists them all
        if not action.detail.get("announced"):
            await _announce(session, action, now)
    return raised, joined


async def send_reminders(session: AsyncSession, now: datetime) -> int:
    """Escalating reminders as the nearest deadline approaches (offsets are a setting). One per offset per
    action; quiet hours hold delivery."""
    sent = 0
    rows = await session.scalars(select(PendingAction).where(
        PendingAction.status == PendingStatus.open, PendingAction.deadline.is_not(None),
        PendingAction.deadline > now))
    for action in rows:
        if not _is_account_action(action):
            continue
        if action.snoozed_until is not None and action.snoozed_until > now:
            continue
        offset = await _crossed_offset(session, action.deadline, now)
        done = action.detail.get("reminded_offset")
        if offset is None or (done is not None and offset >= done):
            continue
        action.detail = {**action.detail, "reminded_offset": offset}
        if await _notify(session, action, now, key=f"portal-account:{action.id}:r{offset}", reminder=True):
            sent += 1
    await session.flush()
    return sent


async def tick(session: AsyncSession, now: datetime | None = None) -> TickResult:
    now = now or utcnow()
    result = TickResult()
    result.closed = await reconcile_actions(session, now)
    result.raised, result.joined = await raise_known_early(session, now)
    result.reminded = await send_reminders(session, now)
    return result


__all__ = [
    "BLOCKER_KINDS",
    "AccountError",
    "AccountNeed",
    "PortalRef",
    "assess_need",
    "continue_blocker",
    "ensure_for_application",
    "give_up",
    "needs_account",
    "portal_ref",
    "preferred_runner_kind",
    "register_blocker",
    "tick",
]
