"""Winding down after accepting an offer (DESIGN.md 18.4).

- **Pause first.** :func:`start` turns the master pause on (with the reason) before anything is listed: every
  outstanding permit is revoked and every queued send not yet handed over is cancelled, so nothing goes out
  while the owner decides. It sends nothing by itself.
- **The view** lists what is still in motion: queued sends (as the pause left them), approved packets and
  messages not yet sent, live applications by stage, interview rounds still ahead, open pending actions and
  campaigns with their schedules. Each item has keep / pause / withdraw choices.
- **Choices.** *Keep* changes nothing. *Pause* withdraws an approval, pauses a campaign and its schedules, or
  snoozes a pending action, recording what to restore. *Withdraw* skips an application that never went out;
  for one that did, it drafts a withdrawal (or offer decline) email for the owner's approval, never sent
  automatically; for a portal application it gives the manual steps.
- **Reopen** ("reopen my search") ends the wind-down and restores everything **paused, never deleted**:
  snoozed actions come back, schedules are re-enabled while their campaigns stay paused, approvals stay
  withdrawn and the master pause stays on until the owner resumes it.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import autopilot, permits, stages
from app.core import audit
from app.core.clock import utcnow
from app.llm.client import LLMClient
from app.models.applications import (
    LIVE_STAGES,
    Application,
    ApplicationPacket,
    InterviewPack,
    InterviewRound,
    PendingAction,
    PendingStatus,
    Stage,
)
from app.models.followups import OutboundMessage, WindDown
from app.models.search import Campaign, CampaignStatus, Job, Schedule
from app.schemas.json_types import WindDownChoice

PRE_SUBMIT = (Stage.shortlisted, Stage.tailoring, Stage.ready)
SNOOZE_YEARS = 10  # "paused" pending actions sleep until the search is reopened


class WindDownError(Exception):
    def __init__(self, message: str, code: str = "refused", status: int = 409) -> None:
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


@dataclass
class Item:
    key: str
    kind: str  # queued_send | approved | message | application | interview | pending_action | campaign
    label: str
    detail: str
    choices: list[WindDownChoice]
    group: str | None = None
    choice: str | None = None
    effect: str | None = None
    application_id: uuid.UUID | None = None


@dataclass
class View:
    wind_down: WindDown
    queued_sends: list[Item] = field(default_factory=list)
    approved_unsent: list[Item] = field(default_factory=list)
    live_applications: dict[str, list[Item]] = field(default_factory=dict)
    interviews: list[Item] = field(default_factory=list)
    pending_actions: list[Item] = field(default_factory=list)
    campaigns: list[Item] = field(default_factory=list)

    def all(self) -> list[Item]:
        return [*self.queued_sends, *self.approved_unsent, *(i for v in self.live_applications.values() for i in v),
                *self.interviews, *self.pending_actions, *self.campaigns]


async def active(session: AsyncSession) -> WindDown | None:
    return await session.scalar(select(WindDown).where(WindDown.status == "active")
                                .order_by(WindDown.created_at.desc()).limit(1))


async def latest(session: AsyncSession) -> WindDown | None:
    return await session.scalar(select(WindDown).order_by(WindDown.created_at.desc()).limit(1))


async def start(session: AsyncSession, *, actor: str, reason: str | None = None,
                accepted_application_id: uuid.UUID | None = None) -> WindDown:
    """Pause everything automatic at once (master pause with the reason), then record the wind-down."""
    existing = await active(session)
    if existing is not None:
        return existing
    was_paused = await _paused(session)
    why = "Accepted an offer: wind-down" + (f" ({reason.strip()})" if reason and reason.strip() else "")
    state = await autopilot.set_paused(session, True, actor=actor, reason=why)
    wd = WindDown(status="active", reason=why, started_by=actor, accepted_application_id=accepted_application_id,
                  was_paused=was_paused, pause_summary=state.summary.model_dump(mode="json"), choices={})
    session.add(wd)
    await session.flush()
    await audit.record(session, actor=actor, action="winddown.started", subject_type="wind_down", subject_id=wd.id,
                       detail={"reason": why, "cancelled": len(state.summary.cancelled),
                               "already_out": len(state.summary.already_out),
                               "accepted_application_id": str(accepted_application_id)
                               if accepted_application_id else None})
    return wd


async def _paused(session: AsyncSession) -> bool:
    from app.apply import dispatch

    return await dispatch.is_paused(session)


def _label(job: Job | None) -> str:
    return f"{job.title} at {job.employer}" if job else "an application"


async def view(session: AsyncSession, wd: WindDown, *, now: datetime | None = None) -> View:
    now = now or utcnow()
    out = View(wind_down=wd)
    chosen = wd.choices or {}

    def item(key: str, kind: str, label: str, detail: str, choices: list[WindDownChoice], **kw: Any) -> Item:
        c = chosen.get(key, {})
        return Item(key, kind, label, detail, choices, choice=c.get("choice"), effect=c.get("effect"), **kw)

    summary = wd.pause_summary or {}
    for row in summary.get("cancelled", []):
        out.queued_sends.append(item(f"send:{row['id']}", "queued_send", row["label"],
                                     f"{row['detail']} when the wind-down started", ["keep"]))
    for row in summary.get("already_out", []):
        out.queued_sends.append(item(f"send:{row['id']}", "queued_send", row["label"],
                                     f"already handed over ({row['detail']}): cannot be recalled", ["keep"]))
    apps = (await session.execute(select(Application, Job).join(Job, Job.id == Application.job_id).where(
        Application.stage.in_((*PRE_SUBMIT, Stage.applying, *LIVE_STAGES))).order_by(Application.created_at))).all()
    groups: dict[str, list[Item]] = defaultdict(list)
    for app, job in apps:
        if app.id == wd.accepted_application_id:
            continue
        if app.approved_packet_id is not None and app.stage in (Stage.ready, Stage.applying):
            packet = await session.get(ApplicationPacket, app.approved_packet_id)
            out.approved_unsent.append(item(
                f"approved:{app.id}", "approved", _label(job),
                f"approved {packet.contents.channel if packet else ''} packet, not sent", ["keep", "pause", "withdraw"],
                application_id=app.id))
            continue
        choices: list[WindDownChoice] = ["keep", "pause", "withdraw"]
        detail = {Stage.offer: "an offer you have not answered"}.get(app.stage, f"stage {app.stage.value}")
        groups[app.stage.value].append(item(f"application:{app.id}", "application", _label(job), detail, choices,
                                            group=app.stage.value, application_id=app.id))
    out.live_applications = dict(groups)
    messages = (await session.scalars(select(OutboundMessage).where(OutboundMessage.status == "approved"))).all()
    from app.pipeline.followups import sending

    for msg in messages:
        if await sending.locked(session, msg):
            continue
        app = await session.get(Application, msg.application_id)
        job = await session.get(Job, app.job_id) if app else None
        out.approved_unsent.append(item(f"message:{msg.id}", "message", _label(job),
                                        f"approved {msg.kind.replace('_', ' ')} email, not sent",
                                        ["keep", "pause", "withdraw"], application_id=msg.application_id))
    rounds = (await session.execute(
        select(InterviewRound, InterviewPack, Job).join(InterviewPack, InterviewPack.id == InterviewRound.pack_id)
        .join(Job, Job.id == InterviewPack.job_id)
        .where(InterviewRound.scheduled_at.is_not(None), InterviewRound.scheduled_at >= now)
        .order_by(InterviewRound.scheduled_at))).all()
    for rnd, pack, job in rounds:
        if pack.application_id is not None and pack.application_id == wd.accepted_application_id:
            continue
        out.interviews.append(item(f"interview:{rnd.id}", "interview", _label(job),
                                   f"round {rnd.round_number} on {rnd.scheduled_at:%Y-%m-%d %H:%M} UTC",
                                   ["keep", "withdraw"], application_id=pack.application_id))
    actions = (await session.scalars(select(PendingAction).where(PendingAction.status == PendingStatus.open)
                                     .order_by(PendingAction.created_at))).all()
    for action in actions:
        out.pending_actions.append(item(f"action:{action.id}", "pending_action", action.title,
                                        action.type.value.replace("_", " "), ["keep", "pause", "withdraw"],
                                        application_id=action.application_id))
    campaigns = (await session.scalars(select(Campaign).where(Campaign.status != CampaignStatus.archived)
                                       .order_by(Campaign.name))).all()
    for c in campaigns:
        schedules = (await session.scalars(select(Schedule).where(Schedule.campaign_id == c.id))).all()
        on = sum(1 for s in schedules if s.enabled)
        out.campaigns.append(item(f"campaign:{c.id}", "campaign", c.name,
                                  f"{c.status.value}; {on} of {len(schedules)} schedule(s) on", ["keep", "pause"]))
    return out


async def choose(session: AsyncSession, wd: WindDown, key: str, choice: WindDownChoice, *, actor: str,
                 client: LLMClient | None = None, now: datetime | None = None) -> Item:
    """Apply one choice. Nothing is sent: a withdrawal is a draft for the owner's approval."""
    now = now or utcnow()
    if wd.status != "active":
        raise WindDownError("this wind-down was reopened", "no_winddown")
    current = {i.key: i for i in (await view(session, wd, now=now)).all()}
    target = current.get(key)
    if target is None:
        raise WindDownError(f"{key} is not in the wind-down view", "not_found", 404)
    if choice not in target.choices:
        raise WindDownError(f"{choice} is not a choice for {target.kind}", "refused", 422)
    kind, _, raw = key.partition(":")
    effect, restore = "nothing changes", {}
    if choice != "keep":
        effect, restore = await _apply(session, kind, uuid.UUID(raw), choice, target, actor=actor, client=client,
                                       now=now)
    wd.choices = {**(wd.choices or {}), key: {"choice": choice, "at": now.isoformat(), "by": actor, "effect": effect,
                                              "restore": restore, "label": target.label, "kind": target.kind}}
    await session.flush()
    await audit.record(session, actor=actor, action="winddown.choice", subject_type="wind_down", subject_id=wd.id,
                       detail={"item": key, "choice": choice, "effect": effect})
    target.choice, target.effect = choice, effect
    return target


async def _apply(session: AsyncSession, kind: str, ident: uuid.UUID, choice: str, target: Item, *, actor: str,
                 client: LLMClient | None, now: datetime) -> tuple[str, dict[str, Any]]:
    from app.pipeline.followups import sending

    if kind == "approved":
        app = await session.get(Application, ident, with_for_update=True)
        assert app is not None
        if choice == "pause":
            packet_id = app.approved_packet_id
            app.approved_packet_id = None
            await permits.revoke(session, application_id=app.id, reason="wind-down: paused", actor=actor, now=now)
            await stages.add_event(session, app.id, "approval_paused", actor, {"packet_id": str(packet_id)})
            return "approval withdrawn: approve it again to send", {"approved_packet_id": str(packet_id)}
        return await _withdraw_application(session, app, actor=actor, client=client, now=now)
    if kind == "message":
        msg = await session.get(OutboundMessage, ident)
        assert msg is not None
        await sending.withdraw_approval(session, msg, actor=actor, reason="wind-down", now=now)
        if choice == "withdraw":
            msg.status = "discarded"
            return "message discarded", {}
        return "approval withdrawn: the message is a draft again", {}
    if kind == "application":
        app = await session.get(Application, ident, with_for_update=True)
        assert app is not None
        if choice == "pause":
            return "follow-ups for it stop until the search is reopened", {}
        return await _withdraw_application(session, app, actor=actor, client=client, now=now)
    if kind == "interview":
        if target.application_id is None:
            return "no application is linked: tell the employer yourself", {}
        app = await session.get(Application, target.application_id)
        assert app is not None
        return await _withdraw_application(session, app, actor=actor, client=client, now=now)
    if kind == "action":
        action = await session.get(PendingAction, ident)
        assert action is not None
        if choice == "pause":
            before = action.snoozed_until.isoformat() if action.snoozed_until else None
            action.snoozed_until = now + timedelta(days=365 * SNOOZE_YEARS)
            return "snoozed until the search is reopened", {"snoozed_until": before}
        action.status, action.resolved_at = PendingStatus.dismissed, now
        action.resolution = {"resolution": "dismissed", "by": actor, "via": "wind-down"}
        return "dismissed", {}
    if kind == "campaign":
        campaign = await session.get(Campaign, ident, with_for_update=True)
        assert campaign is not None
        before = {"status": campaign.status.value, "paused_until": str(campaign.paused_until)
                  if campaign.paused_until else None}
        campaign.status, campaign.paused_until = CampaignStatus.paused, None
        schedules = (await session.scalars(select(Schedule).where(Schedule.campaign_id == campaign.id,
                                                                  Schedule.enabled.is_(True)))).all()
        for s in schedules:
            s.enabled = False
        await audit.record(session, actor=actor, action="campaign.status", subject_type="campaign",
                           subject_id=campaign.id, detail={"status": "paused", "via": "wind-down"})
        return (f"campaign paused, {len(schedules)} schedule(s) stopped",
                {**before, "schedules": [str(s.id) for s in schedules]})
    raise WindDownError(f"unknown item kind {kind}", "refused", 422)


async def _withdraw_application(session: AsyncSession, app: Application, *, actor: str, client: LLMClient | None,
                                now: datetime) -> tuple[str, dict[str, Any]]:
    from app.pipeline.followups import context as ctx_mod
    from app.pipeline.followups import drafting

    if app.stage in PRE_SUBMIT:
        if app.approved_packet_id is not None:
            app.approved_packet_id = None
            await permits.revoke(session, application_id=app.id, reason="wind-down: withdrawn", actor=actor, now=now)
        await stages.transition(session, app, Stage.skipped, actor=actor, via="owner", now=now,
                                why="wind-down: accepted another offer")
        return "never sent: skipped", {"stage": app.stage.value}
    ctx = await ctx_mod.load(session, app)
    if not ctx.known or not ctx.sending_identity:
        job = ctx.job
        where = job.apply_url or "the employer's portal"
        return (f"applied through a portal: withdraw it yourself at {where}, then mark it withdrawn",
                {"manual": True})
    if client is None:
        raise WindDownError("drafting a withdrawal needs the AI service", "refused", 503)
    kind = "offer_decline" if app.stage == Stage.offer else "withdraw"
    msg = await drafting.create(session, client, app, kind, actor=actor, now=now)  # type: ignore[arg-type]
    return (f"{kind.replace('_', ' ')} email drafted for your approval (never sent automatically)",
            {"message_id": str(msg.id)})


def kept_applications(wd: WindDown) -> set[uuid.UUID]:
    """During an active wind-down only applications the owner chose to keep get follow-ups."""
    return {uuid.UUID(k.partition(":")[2]) for k, v in (wd.choices or {}).items()
            if k.startswith("application:") and v.get("choice") == "keep"}


async def reopen(session: AsyncSession, wd: WindDown, *, actor: str, now: datetime | None = None) -> WindDown:
    """End the wind-down. Restored paused, never deleted: snoozed actions return, schedules come back on while
    their campaigns stay paused, the master pause stays on until the owner resumes it."""
    now = now or utcnow()
    if wd.status != "active":
        raise WindDownError("this wind-down is not active", "no_winddown")
    restored: list[str] = []
    for key, c in (wd.choices or {}).items():
        kind, _, raw = key.partition(":")
        restore = c.get("restore") or {}
        if kind == "action" and c.get("choice") == "pause":
            action = await session.get(PendingAction, uuid.UUID(raw))
            if action is not None and action.status == PendingStatus.open:
                prior = restore.get("snoozed_until")
                action.snoozed_until = datetime.fromisoformat(prior) if prior else None
                restored.append(key)
        if kind == "campaign" and c.get("choice") == "pause":
            for sid in restore.get("schedules", []):
                schedule = await session.get(Schedule, uuid.UUID(sid))
                if schedule is not None:
                    schedule.enabled = True
            restored.append(key)
    wd.status, wd.reopened_at, wd.reopened_by = "reopened", now, actor
    await session.flush()
    await audit.record(session, actor=actor, action="winddown.reopened", subject_type="wind_down", subject_id=wd.id,
                       detail={"restored": restored, "autopilot_still_paused": True})
    return wd


def summary_text(v: View, app_name: str, now: datetime) -> str:
    """The final summary export (Markdown)."""
    wd = v.wind_down
    lines = [f"# {app_name}: wind-down summary", "", f"Started {wd.created_at:%Y-%m-%d %H:%M} UTC by {wd.started_by}.",
             f"Reason: {wd.reason}", f"Status: {wd.status}" + (f" (reopened {wd.reopened_at:%Y-%m-%d})"
                                                               if wd.reopened_at else ""),
             f"Exported {now:%Y-%m-%d %H:%M} UTC.", ""]

    def section(title: str, items: list[Item]) -> None:
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["None.", ""])
            return
        for i in items:
            decided = f" -> {i.choice}: {i.effect}" if i.choice else " -> no choice made"
            lines.append(f"- {i.label} ({i.detail}){decided}")
        lines.append("")

    section("Queued sends when it started", v.queued_sends)
    section("Approved, not sent", v.approved_unsent)
    for stage, items in v.live_applications.items():
        section(f"Live applications: {stage}", items)
    section("Interviews ahead", v.interviews)
    section("Pending actions", v.pending_actions)
    section("Campaigns", v.campaigns)
    decided_elsewhere = [c for k, c in (wd.choices or {}).items() if k not in {i.key for i in v.all()}]
    if decided_elsewhere:
        lines.extend(["## Already settled", ""])
        lines.extend(f"- {c.get('label', '')}: {c['choice']} ({c.get('effect', '')})" for c in decided_elsewhere)
        lines.append("")
    return "\n".join(lines)
