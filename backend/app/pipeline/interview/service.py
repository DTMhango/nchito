"""Interview pack generation: request (idempotent), process section by section, pause and resume, owner edits.

A request bumps the pack's ``generation`` and lists the sections to build. Each section becomes one
``InterviewSectionVersion`` keyed ``gen<n>`` (unique per pack and section), so a retried, resumed or
duplicated task can never write a section twice. Each model call is estimated and reserved on its own
(the ledger, through ``LLMClient``); a ``BudgetExhausted`` parks the pack ``paused`` with the sections
still to do, and :func:`resume_paused` re-queues it once a cap is set and the cap or the month changed.

Truth rules: a generated section goes through :mod:`app.pipeline.interview.truth`; one that still blocks
after ``interview.regenerate_attempts`` retries is stored ``flagged`` and is never shown as fine.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply.stages import counts_as_application
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.core.settings import service as settings_service
from app.kit.work_rights import to_record
from app.llm.client import BudgetExhausted, LLMClient, LLMError
from app.llm.ledger import month_bounds
from app.llm.money import effective_cap_micros
from app.llm.prompts import active_prompt
from app.models.applications import (
    Application,
    Contact,
    InterviewPack,
    InterviewPackStatus,
    InterviewSectionVersion,
    MailThread,
)
from app.models.kit import Answer
from app.models.search import Campaign, Job
from app.pipeline.checks import claim_check
from app.pipeline.checks import kit as kit_view
from app.pipeline.checks import service as checks
from app.pipeline.checks.findings import Finding, summarise, worst
from app.pipeline.checks.items import cited_codes
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.interview import basis as basis_mod
from app.pipeline.interview import crib, paysheet, truth
from app.pipeline.interview import shapes as sh
from app.pipeline.interview.prompt import PackContext, build_messages
from app.pipeline.tailoring.answers import context_for
from app.pipeline.tailoring.prompt import select_facts
from app.schemas.json_types import ApplicationSpec

log = logging.getLogger(__name__)

STAGE = "interview"
OPEN = (InterviewPackStatus.queued, InterviewPackStatus.running)


class InterviewError(ValueError):
    def __init__(self, message: str, status_code: int = 409, code: str = "refused") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


# ----- loading -------------------------------------------------------------------------------------


async def application_for_job(session: AsyncSession, job_id: uuid.UUID) -> Application | None:
    """The application the pack is for: the newest that counts as one, else the newest."""
    rows = list((await session.scalars(select(Application).where(Application.job_id == job_id)
                                       .order_by(Application.created_at.desc()))).all())
    return next((a for a in rows if counts_as_application(a)), rows[0] if rows else None)


async def pack_for_job(session: AsyncSession, job_id: uuid.UUID, *, lock: bool = False) -> InterviewPack | None:
    q = select(InterviewPack).where(InterviewPack.job_id == job_id)
    return await session.scalar(q.with_for_update() if lock else q)


async def get_or_create(session: AsyncSession, job: Job) -> InterviewPack:
    pack = await pack_for_job(session, job.id, lock=True)
    if pack is not None:
        return pack
    app = await application_for_job(session, job.id)
    row = InterviewPack(job_id=job.id, application_id=app.id if app else None, sections={})
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError:  # a concurrent request created it
        pack = await pack_for_job(session, job.id, lock=True)
        assert pack is not None
        return pack
    return row


async def load_kit(session: AsyncSession, app: Application | None) -> KitView:
    campaign = await session.get(Campaign, app.campaign_id) if app and app.campaign_id else None
    return await kit_view.load(session, track_id=campaign.track_id if campaign else None)


def configured_sections(values: Mapping[str, Any]) -> list[str]:
    return list(values["interview.sections"])


def model_for(section: str, values: Mapping[str, Any]) -> str:
    return str(values[f"interview.model_{section}"])


async def current_versions(session: AsyncSession, pack_id: uuid.UUID) -> dict[str, InterviewSectionVersion]:
    rows = (await session.scalars(select(InterviewSectionVersion).where(
        InterviewSectionVersion.pack_id == pack_id).order_by(InterviewSectionVersion.version))).all()
    return {r.section: r for r in rows}  # the highest version of each section wins


async def versions_of(session: AsyncSession, pack_id: uuid.UUID, section: str) -> list[InterviewSectionVersion]:
    return list((await session.scalars(select(InterviewSectionVersion).where(
        InterviewSectionVersion.pack_id == pack_id, InterviewSectionVersion.section == section)
        .order_by(InterviewSectionVersion.version.desc()))).all())


def _facts(kit: KitView, job: Job, spec: ApplicationSpec | None, limit: int) -> list[FactView]:
    """Facts cited in what was sent first (so the pack covers what the employer has), then the selection."""
    sent = sorted(cited_codes(spec)) if spec is not None else []
    first = [kit.facts[c] for c in sent if c in kit.facts and kit.facts[c].usable]
    rest = select_facts(kit, job, limit=limit)
    seen: set[str] = set()
    out: list[FactView] = []
    for f in [*first, *rest]:
        if f.code not in seen:
            seen.add(f.code)
            out.append(f)
    return out[:max(limit, len(first))]


async def build_context(session: AsyncSession, job: Job, app: Application | None, kit: KitView,
                        values: Mapping[str, Any]) -> tuple[PackContext, basis_mod.Resolved]:
    resolved = await basis_mod.resolve(session, app, job, kit)
    facts = _facts(kit, job, resolved.spec, int(values["tailoring.max_facts"]))
    mail: list[str] = []
    notes: list[str] = []
    if app is not None:
        threads = (await session.scalars(select(MailThread).where(MailThread.application_id == app.id)
                                         .order_by(MailThread.created_at))).all()
        mail = [f"{t.classification.value}: {t.subject or '(no subject)'}"
                f"{f' (from {t.sender})' if t.sender else ''}" for t in threads]
        if app.notes:
            notes.append(f"Application notes:\n{app.notes}")
    if job.notes:
        notes.append(f"Job notes:\n{job.notes}")
    contacts = (await session.scalars(select(Contact).where(Contact.job_id == job.id))).all()
    notes += [f"Contact: {c.name}{f', {c.role}' if c.role else ''}{f': {c.notes}' if c.notes else ''}"
              for c in contacts]
    return PackContext(job=job, kit=kit, facts=facts, basis=resolved.basis, spec=resolved.spec,
                       answers=resolved.answers, mail=mail, notes=notes), resolved


# ----- estimate and request ------------------------------------------------------------------------


async def estimate(session: AsyncSession, client: LLMClient, job: Job,
                   sections: Sequence[str] | None = None) -> dict[str, int]:
    """Upper-bound cost in micros of each model-built section (one attempt each; retries cost more)."""
    values = await settings_service.values(session)
    app = await application_for_job(session, job.id)
    kit = await load_kit(session, app)
    ctx, _ = await build_context(session, job, app, kit, values)
    prompt = await active_prompt(session, STAGE)
    out: dict[str, int] = {}
    for section in sections or configured_sections(values):
        if section not in sh.LLM_SECTIONS:
            continue
        messages = build_messages(prompt.text if prompt else "", section, ctx, values)
        out[section] = await client.estimate_cost_micros(STAGE, messages, model=model_for(section, values),
                                                         schema=sh.REPLIES[section])
    return out


async def request(session: AsyncSession, job: Job, *, actor: str, sections: Sequence[str] | None = None,
                  estimate_micros: int | None = None) -> tuple[InterviewPack, bool]:
    """Ask for (part of) the pack. ``True`` when it needs queueing; an open request is returned as is."""
    values = await settings_service.values(session)
    allowed = configured_sections(values)
    wanted = list(sections) if sections else allowed
    unknown = [s for s in wanted if s not in allowed]
    if unknown:
        raise InterviewError(f"not a section of this pack: {', '.join(unknown)}", 422, "unknown_section")
    pack = await get_or_create(session, job)
    if pack.status in OPEN:
        return pack, False
    if pack.application_id is None:
        app = await application_for_job(session, job.id)
        pack.application_id = app.id if app else None
    if "crib_sheet" in allowed and "crib_sheet" not in wanted:
        wanted.append("crib_sheet")  # the crib sheet follows every change
    pack.generation += 1
    pack.pending_sections = [s for s in allowed if s in wanted]
    pack.status, pack.error, pack.paused_mark = InterviewPackStatus.queued, None, None
    pack.requested_by = actor
    if estimate_micros is not None:
        pack.estimate_micros = estimate_micros
    await session.flush()
    await audit.record(session, actor=actor, action="interview.requested", subject_type="interview_pack",
                       subject_id=pack.id, detail={"job_id": str(job.id), "generation": pack.generation,
                                                   "sections": pack.pending_sections,
                                                   "estimate_micros": estimate_micros})
    return pack, True


# ----- storing versions ----------------------------------------------------------------------------


async def _next_version(session: AsyncSession, pack_id: uuid.UUID, section: str) -> int:
    top = await session.scalar(select(func.max(InterviewSectionVersion.version)).where(
        InterviewSectionVersion.pack_id == pack_id, InterviewSectionVersion.section == section))
    return int(top or 0) + 1


async def store(session: AsyncSession, pack: InterviewPack, section: str, content: sh.Shape,
                findings: Sequence[Finding], checks_run: Sequence[str], *, origin: str, actor: str,
                request_key: str | None = None, model: str | None = None, cost: int = 0) -> InterviewSectionVersion:
    results = summarise(findings, checks_run)
    status = worst(results)
    row = InterviewSectionVersion(
        pack_id=pack.id, section=section, version=await _next_version(session, pack.id, section), origin=origin,
        request_key=request_key, content=content.model_dump(mode="json"), fact_ids=truth.fact_ids(content, section),
        check_results=results, status=status, flagged=status == "block", model=model, cost_micros=cost,
        created_by=actor)
    session.add(row)
    await session.flush()
    return row


async def mirror(session: AsyncSession, pack: InterviewPack) -> None:
    """``InterviewPack.sections``: the current version of each section, as the API shows it."""
    current = await current_versions(session, pack.id)
    pack.sections = {k: {"version": v.version, "origin": v.origin, "status": v.status, "flagged": v.flagged,
                         "fact_ids": v.fact_ids, "content": v.content,
                         "check_results": [r.model_dump(mode="json") for r in v.check_results],
                         "model": v.model, "created_at": v.created_at.isoformat() if v.created_at else None}
                     for k, v in current.items()}


def _parsed(current: Mapping[str, InterviewSectionVersion]) -> dict[str, sh.Shape]:
    return {k: sh.validate(k, v.content) for k, v in current.items()}


# ----- building sections ---------------------------------------------------------------------------


def _carry_favourites(new: sh.Stories, old: sh.Stories | None) -> sh.Stories:
    if old is None:
        return new
    keep = {(frozenset(s.fact_ids), s.title.casefold()) for s in old.items if s.favourite}
    codes = {frozenset(s.fact_ids) for s in old.items if s.favourite}
    items = [s.model_copy(update={"favourite": (frozenset(s.fact_ids), s.title.casefold()) in keep
                                  or frozenset(s.fact_ids) in codes}) for s in new.items]
    return sh.Stories(items=items)


def _content(section: str, reply: sh.Shape, values: Mapping[str, Any], basis: basis_mod.Basis,
             previous: sh.Shape | None) -> sh.Shape:
    if section == "role_brief":
        return sh.RoleBrief(**reply.model_dump(), research_note=str(values["interview.research_note"]),
                            posting_changed=basis.posting_changed)
    if section == "stories":
        stories = sh.Stories(items=[sh.Story(**s.model_dump()) for s in reply.items])  # type: ignore[attr-defined]
        return _carry_favourites(stories, previous if isinstance(previous, sh.Stories) else None)
    return sh.SHAPES[section].model_validate(reply.model_dump())


async def _generate(session: AsyncSession, client: LLMClient, pack: InterviewPack, section: str,
                    ctx: PackContext, values: Mapping[str, Any], cfg: checks.CheckSettings, prompt: str,
                    job_terms: Sequence[str], previous: sh.Shape | None, request_key: str
                    ) -> InterviewSectionVersion:
    """One model-built section, regenerated while it fails the truth checks. Raises ``BudgetExhausted``."""
    attempts = 1 + int(values["interview.regenerate_attempts"])
    model = model_for(section, values)
    problems: list[str] = []
    cost, used = 0, model
    for attempt in range(attempts):
        messages = build_messages(prompt, section, ctx, values, retry_problems=problems)
        limit = await client.estimate_cost_micros(STAGE, messages, model=model, schema=sh.REPLIES[section])
        reply, usage = await client.complete(STAGE, messages, sh.REPLIES[section], max_cost_micros=limit, model=model)
        cost += usage.cost_micros
        used = usage.model
        content = _content(section, reply, values, ctx.basis, previous)
        result = truth.check(section, content, ctx.kit, cfg, job_terms=job_terms)
        findings = list(result.findings)
        run = list(truth.CHECKS_RUN)
        # The model pass only adds findings, so it runs only on text the code checks passed: a blocked
        # draft is regenerated or flagged anyway, and text echoing a keep-out fact never goes back out.
        if cfg.claim_check_enabled and result.items and not truth.blocking(findings):
            extra, extra_cost = await claim_check.run(session, client, result.items, result.cited,
                                                      severity=cfg.claim_check_severity,
                                                      model=values["ai.model_claim_check"])
            findings += extra
            cost += extra_cost
            run.append(claim_check.CHECK)
        blocks = truth.blocking(findings)
        if not blocks or attempt == attempts - 1:
            return await store(session, pack, section, content, findings, run, origin="generated", actor="system",
                               request_key=request_key, model=used, cost=cost)
        problems = truth.retry_notes(blocks, ctx.kit)
    raise AssertionError("unreachable")  # pragma: no cover


async def _pay_sheet(session: AsyncSession, job: Job, app: Application | None, ctx: PackContext,
                     values: Mapping[str, Any], now: datetime) -> sh.PaySheet:
    rows = (await session.scalars(select(Answer))).all()
    context = context_for(app, job) if app is not None else {"employer": job.canonical_employer}
    return paysheet.build(job, [to_record(a) for a in rows], ctx.answers, topic_lines=values["interview.pay_topics"],
                          threshold=float(values["answers.match_similarity"]), context=context, today=now.date(),
                          decide=str(values["interview.decide_wording"]))


async def _code_section(session: AsyncSession, pack: InterviewPack, section: str, job: Job,
                        app: Application | None, ctx: PackContext, values: Mapping[str, Any],
                        cfg: checks.CheckSettings, job_terms: Sequence[str], now: datetime, request_key: str | None,
                        actor: str = "system") -> InterviewSectionVersion:
    if section == "pay_sheet":
        content: sh.Shape = await _pay_sheet(session, job, app, ctx, values, now)
    else:
        current = await current_versions(session, pack.id)
        flagged = {k for k, v in current.items() if v.flagged}
        content = crib.build(_parsed({k: v for k, v in current.items() if k != "crib_sheet"}), flagged)
    result = truth.check(section, content, ctx.kit, cfg, job_terms=job_terms)
    return await store(session, pack, section, content, result.findings, truth.CHECKS_RUN, origin="code",
                       actor=actor, request_key=request_key)


# ----- processing ----------------------------------------------------------------------------------


async def _pause_mark(session: AsyncSession, exc: BudgetExhausted, now: datetime) -> dict[str, object]:
    values = await settings_service.values(session)
    return {"scope": exc.scope, "cap_micros": effective_cap_micros(values, "monthly"),
            "per_run_cap_micros": effective_cap_micros(values, "per_run"),
            "month": month_bounds(now, values["general.timezone"])[2]}


async def process(session: AsyncSession, client: LLMClient, pack_id: uuid.UUID, *,
                  now: datetime | None = None) -> InterviewPackStatus:
    """Build the pending sections of one request. Safe to call again: sections already written for this
    generation are skipped, and a pack that is not queued or running is left alone."""
    now = now or utcnow()
    pack = await session.get(InterviewPack, pack_id, with_for_update=True)
    if pack is None:
        raise InterviewError("interview pack not found", 404, "not_found")
    if pack.status not in OPEN:
        return pack.status
    pack.status = InterviewPackStatus.running
    job = await session.get(Job, pack.job_id)
    assert job is not None
    app = await session.get(Application, pack.application_id) if pack.application_id else None
    values = await settings_service.values(session)
    cfg = await checks.check_settings(session, values)
    kit = await load_kit(session, app)
    ctx, resolved = await build_context(session, job, app, kit, values)
    pack.basis = resolved.basis.model_dump(mode="json")
    prompt_row = await active_prompt(session, STAGE)
    prompt = prompt_row.text if prompt_row else ""
    terms = checks.job_terms(job)
    key = f"gen{pack.generation}"
    for section in list(pack.pending_sections):
        done = await session.scalar(select(InterviewSectionVersion.id).where(
            InterviewSectionVersion.pack_id == pack.id, InterviewSectionVersion.section == section,
            InterviewSectionVersion.request_key == key))
        if done is None:
            try:
                if section in sh.LLM_SECTIONS:
                    current = await current_versions(session, pack.id)
                    previous = sh.validate(section, current[section].content) if section in current else None
                    row = await _generate(session, client, pack, section, ctx, values, cfg, prompt, terms,
                                          previous, key)
                    pack.model = row.model
                else:
                    row = await _code_section(session, pack, section, job, app, ctx, values, cfg, terms, now, key)
                pack.cost_micros += row.cost_micros
            except BudgetExhausted as exc:
                pack.status = InterviewPackStatus.paused
                pack.paused_mark = await _pause_mark(session, exc, now)
                pack.error = str(exc)[:2000]
                await mirror(session, pack)
                await audit.record(session, actor="system", action="interview.paused", subject_type="interview_pack",
                                   subject_id=pack.id, detail={"scope": exc.scope, "section": section,
                                                               "remaining": pack.pending_sections})
                return pack.status
            except LLMError as exc:
                pack.status, pack.error = InterviewPackStatus.failed, str(exc)[:2000]
                await mirror(session, pack)
                await audit.record(session, actor="system", action="interview.failed", subject_type="interview_pack",
                                   subject_id=pack.id, detail={"section": section, "error": pack.error[:300]})
                return pack.status
        pack.pending_sections = [s for s in pack.pending_sections if s != section]
        await session.flush()
    pack.status, pack.error, pack.paused_mark = InterviewPackStatus.done, None, None
    pack.generated_at = now
    await mirror(session, pack)
    current = await current_versions(session, pack.id)
    await audit.record(session, actor="system", action="interview.generated", subject_type="interview_pack",
                       subject_id=pack.id, detail={
                           "generation": pack.generation, "basis": resolved.basis.source,
                           "spec_version": resolved.basis.spec_version, "facts_sent": [f.code for f in ctx.facts],
                           "flagged": sorted(k for k, v in current.items() if v.flagged),
                           "cost_micros": pack.cost_micros})
    await publish(session, "interview.updated", {"job_id": str(pack.job_id), "pack_id": str(pack.id)})
    return pack.status


async def resume_paused(session: AsyncSession, enqueue: Callable[[InterviewPack], Awaitable[None]], *,
                        now: datetime | None = None) -> list[InterviewPack]:
    """Re-queue packs paused for budget once the budget allows. Commits before enqueueing."""
    paused = list((await session.scalars(select(InterviewPack).where(
        InterviewPack.status == InterviewPackStatus.paused).order_by(InterviewPack.updated_at))).all())
    if not paused:
        return []
    values = await settings_service.values(session)
    cap = effective_cap_micros(values, "monthly")
    if cap is None:
        return []
    month = month_bounds(now or utcnow(), values["general.timezone"])[2]
    resumed: list[InterviewPack] = []
    for pack in paused:
        mark = pack.paused_mark or {}
        if (mark.get("cap_micros") == cap and mark.get("per_run_cap_micros") == effective_cap_micros(values, "per_run")
                and mark.get("month") == month):
            continue
        pack.status = InterviewPackStatus.queued
        await audit.record(session, actor="system", action="interview.resumed", subject_type="interview_pack",
                           subject_id=pack.id, detail={"after": mark.get("scope"),
                                                       "remaining": pack.pending_sections})
        resumed.append(pack)
    await session.commit()
    for pack in resumed:
        await enqueue(pack)
    return resumed


# ----- owner actions -------------------------------------------------------------------------------


async def _refresh_crib(session: AsyncSession, pack: InterviewPack, job: Job, app: Application | None,
                        kit: KitView, values: Mapping[str, Any], cfg: checks.CheckSettings, actor: str) -> None:
    if "crib_sheet" not in configured_sections(values):
        return
    ctx = PackContext(job=job, kit=kit, facts=[], basis=basis_mod.Basis(source="none"))
    await _code_section(session, pack, "crib_sheet", job, app, ctx, values, cfg, checks.job_terms(job), utcnow(),
                        None, actor)


async def edit(session: AsyncSession, pack: InterviewPack, section: str, content: object, *,
               actor: str) -> InterviewSectionVersion:
    """An owner edit: a new version, checked like a generated one (an invented figure still blocks)."""
    if pack.status in OPEN:
        raise InterviewError("the pack is being generated; edit it when it is done", 409, "still_queued")
    if section not in sh.SHAPES:
        raise InterviewError(f"unknown section {section!r}", 404, "unknown_section")
    try:
        parsed = sh.validate(section, content)
    except ValidationError as exc:
        raise InterviewError(f"not a valid {section} section: {exc.errors()[0]['msg']}", 422,
                             "invalid_section") from exc
    job = await session.get(Job, pack.job_id)
    assert job is not None
    app = await session.get(Application, pack.application_id) if pack.application_id else None
    values = await settings_service.values(session)
    cfg = await checks.check_settings(session, values)
    kit = await load_kit(session, app)
    result = truth.check(section, parsed, kit, cfg, job_terms=checks.job_terms(job))
    row = await store(session, pack, section, parsed, result.findings, truth.CHECKS_RUN, origin="owner", actor=actor)
    if section != "crib_sheet":
        await _refresh_crib(session, pack, job, app, kit, values, cfg, actor)
    await mirror(session, pack)
    await audit.record(session, actor=actor, action="interview.section_edited", subject_type="interview_pack",
                       subject_id=pack.id, detail={"section": section, "version": row.version, "status": row.status})
    return row


async def set_favourite(session: AsyncSession, pack: InterviewPack, story_id: str, favourite: bool, *,
                        actor: str) -> InterviewSectionVersion:
    current = await current_versions(session, pack.id)
    if "stories" not in current:
        raise InterviewError("the pack has no story bank yet", 404, "not_found")
    stories = sh.Stories.model_validate(current["stories"].content)
    if not any(s.id == story_id for s in stories.items):
        raise InterviewError(f"no story {story_id!r}", 404, "not_found")
    updated = sh.Stories(items=[s.model_copy(update={"favourite": favourite}) if s.id == story_id else s
                                for s in stories.items])
    return await edit(session, pack, "stories", updated.model_dump(mode="json"), actor=actor)


async def set_note(session: AsyncSession, pack: InterviewPack, section: str, note: str | None, *, actor: str) -> None:
    if section not in sh.SHAPES:
        raise InterviewError(f"unknown section {section!r}", 404, "unknown_section")
    notes = dict(pack.notes or {})
    if note and note.strip():
        notes[section] = note
    else:
        notes.pop(section, None)
    pack.notes = notes
    await audit.record(session, actor=actor, action="interview.note_set", subject_type="interview_pack",
                       subject_id=pack.id, detail={"section": section, "cleared": section not in notes})
