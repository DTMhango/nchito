"""Run every check over one spec version and store the result against its exact content.

Order: the deterministic checks (fact tracing, claim drift, keep-out, guardrails, limits, skills,
requirement match, answers) decide; then, if enabled and a client is given, the model claim check
adds findings. Results are stored on the version with the content hash and the hash of every fact
the spec cites, so :func:`state` can tell when the check has gone stale.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.kit import waivers
from app.kit.guardrails import Attachment, Document
from app.llm.client import LLMClient
from app.models.applications import Application, ApplicationSpecVersion
from app.models.kit import Template
from app.models.search import Campaign, Job
from app.pipeline.checks import claim_check, guard, tracing
from app.pipeline.checks import kit as kit_view
from app.pipeline.checks.drift import DriftTerms, drift, staleness
from app.pipeline.checks.findings import Finding, Status, summarise, worst
from app.pipeline.checks.items import Item, cited_codes, content_hash, documents
from app.pipeline.checks.items import items as spec_items
from app.pipeline.checks.kit import FactView, KitView
from app.pipeline.checks.tools import ToolTerms
from app.pipeline.checks.tools import posting_terms as _posting_terms
from app.schemas.json_types import ApplicationSpec, CheckResult, DraftAnswer

ANSWERS = "answers"
DETERMINISTIC = (tracing.TRACE, tracing.DRIFT, guard.KEEP_OUT, guard.GUARDRAILS, guard.LIMITS, guard.SKILLS,
                 guard.MATCH, ANSWERS)


@dataclass(frozen=True)
class CheckSettings:
    qualification_terms: tuple[str, ...]
    drift_terms: DriftTerms
    letter_paragraphs: int
    bullets_per_role: int | None = None
    claim_check_enabled: bool = False
    claim_check_severity: Status = "warn"
    tools: ToolTerms = field(default_factory=ToolTerms)


async def check_settings(session: AsyncSession, values: Mapping[str, Any] | None = None) -> CheckSettings:
    v = values if values is not None else await settings_service.values(session)
    template = await session.scalar(select(Template).where(Template.key == v["documents.cv_template"]))
    return CheckSettings(
        qualification_terms=tuple(v["tailoring.qualification_terms"]),
        drift_terms=DriftTerms(weak=tuple(v["tailoring.ownership_weak_terms"]),
                               strong=tuple(v["tailoring.ownership_strong_terms"]),
                               scope=tuple(v["tailoring.scope_terms"]), period=tuple(v["tailoring.period_terms"])),
        letter_paragraphs=int(v["documents.letter_paragraphs"]),
        bullets_per_role=template.limits.bullets_per_role if template is not None else None,
        claim_check_enabled=bool(v["tailoring.claim_check_enabled"]),
        claim_check_severity=v["tailoring.claim_check_severity"],
        tools=ToolTerms(terms=tuple(v["tailoring.tool_terms"]), ignore=tuple(v["tailoring.tool_ignore_terms"]),
                        role_phrases=tuple(v["tailoring.tool_role_phrases"]),
                        token_detection=bool(v["tailoring.tool_token_detection"])),
    )


@dataclass
class Outcome:
    findings: list[Finding]
    items: list[Item]
    cited: Mapping[str, list[FactView]]
    checks_run: list[str] = field(default_factory=lambda: list(DETERMINISTIC))


def answer_findings(answers: Sequence[DraftAnswer]) -> list[Finding]:
    out: list[Finding] = []
    for i, a in enumerate(answers):
        if a.outcome == "ask_owner":
            out.append(Finding(ANSWERS, "warn", f"'{a.question[:120]}' needs your answer: {a.reason}",
                               f"answers[{i}]"))
    return out


def deterministic(spec: ApplicationSpec, kit: KitView, cfg: CheckSettings, *, answers: Sequence[DraftAnswer] = (),
                  waived: Iterable[str] = (), job_terms: Iterable[str] = (), extra_documents: Sequence[Document] = (),
                  file_names: Sequence[str] = (), attachments: Sequence[Attachment] = (),
                  released: Iterable[str] = (), posting_terms: Sequence[str] = ()) -> Outcome:
    """Every code check. Pure: the same spec, Kit and settings always give the same findings.

    ``extra_documents``, ``file_names``, ``attachments`` and ``released`` let the packet check run the
    guardrails over the whole outgoing packet (email body, file names, attachments)."""
    located = spec_items(spec)
    docs = documents(spec, answers, extra_documents)
    findings, cited = tracing.trace(spec, located, kit, qualification_terms=cfg.qualification_terms,
                                    job_terms=job_terms, tools=cfg.tools, posting_terms=posting_terms)
    findings += drift(located, cited, cfg.drift_terms)
    findings += guard.keep_out_findings(located, docs, kit)
    findings += guard.guardrail_findings(kit, docs, waived=waived, file_names=file_names, attachments=attachments,
                                         released=released)
    findings += guard.limit_findings(spec, letter_paragraphs=cfg.letter_paragraphs,
                                     bullets_per_role=cfg.bullets_per_role)
    findings += guard.skill_findings(spec, kit)
    findings += guard.match_findings(spec, kit)
    findings += answer_findings(answers)
    return Outcome(findings=findings, items=located, cited={k: list(v) for k, v in cited.items()})


async def context(session: AsyncSession, app: Application) -> tuple[Job, KitView]:
    job = await session.get(Job, app.job_id)
    assert job is not None
    campaign = await session.get(Campaign, app.campaign_id) if app.campaign_id else None
    kit = await kit_view.load(session, track_id=campaign.track_id if campaign else None)
    return job, kit


def job_terms(job: Job) -> list[str]:
    return [t for t in (job.employer, job.canonical_employer, job.recruiter, job.title) if t]


def posting_terms(job: Job) -> list[str]:
    """The posting's requirement terms (skills it asks for), for tool tracing."""
    facets = job.facets
    return _posting_terms(facets.required_skills if facets else (), facets.preferred_skills if facets else (),
                          (r.skill for r in (job.requirements or [])))


async def latest_version(session: AsyncSession, application_id: uuid.UUID) -> ApplicationSpecVersion | None:
    return await session.scalar(select(ApplicationSpecVersion).where(
        ApplicationSpecVersion.application_id == application_id).order_by(ApplicationSpecVersion.version.desc())
        .limit(1))


async def next_version_number(session: AsyncSession, application_id: uuid.UUID) -> int:
    top = await session.scalar(select(func.max(ApplicationSpecVersion.version)).where(
        ApplicationSpecVersion.application_id == application_id))
    return int(top or 0) + 1


async def check_version(session: AsyncSession, version: ApplicationSpecVersion, *, client: LLMClient | None = None,
                        actor: str = "system") -> tuple[list[CheckResult], int]:
    """Run the checks on ``version``, store them on it (and on the application if it is current) and
    return the results with the model pass's cost in micros."""
    app = await session.get(Application, version.application_id, with_for_update=True)
    assert app is not None
    job, kit = await context(session, app)
    cfg = await check_settings(session)
    outcome = deterministic(version.spec, kit, cfg, answers=version.answers,
                            waived=await waivers.waived_ids(session, app.id), job_terms=job_terms(job),
                            posting_terms=posting_terms(job))
    cost = 0
    if client is not None and cfg.claim_check_enabled:
        values = await settings_service.values(session)
        extra, cost = await claim_check.run(session, client, outcome.items, outcome.cited,
                                            severity=cfg.claim_check_severity, model=values["ai.model_claim_check"])
        outcome.findings += extra
        outcome.checks_run.append(claim_check.CHECK)
    results = summarise(outcome.findings, outcome.checks_run)
    version.check_results = results
    version.checked_hash = content_hash(version.spec)
    version.checked_facts = kit.fact_hashes(cited_codes(version.spec))
    version.checked_at = utcnow()
    latest = await latest_version(session, app.id)
    if latest is None or latest.id == version.id:
        app.check_results = results
    await session.flush()
    await audit.record(session, actor=actor, action="application.spec_checked", subject_type="application",
                       subject_id=app.id, detail={"version": version.version, "content_hash": version.checked_hash,
                                                  "status": worst(results),
                                                  "blocks": sum(r.status == "block" and not r.waived for r in results),
                                                  "model_check": claim_check.CHECK in outcome.checks_run})
    return results, cost


@dataclass(frozen=True)
class CheckState:
    checked: bool  # the stored check ran on exactly this content and these facts
    status: Status
    stale_reasons: list[str]


async def state(session: AsyncSession, version: ApplicationSpecVersion, kit: KitView | None = None) -> CheckState:
    if kit is None:
        app = await session.get(Application, version.application_id)
        assert app is not None
        _, kit = await context(session, app)
    reasons = staleness(content_hash=version.content_hash, checked_hash=version.checked_hash,
                        checked_facts=version.checked_facts,
                        current_facts=kit.fact_hashes(version.checked_facts.keys()))
    if version.checked_hash is not None and version.checked_hash == version.content_hash:
        # Facts cited now but not at check time (cannot happen for an unchanged spec, kept for safety).
        missing = cited_codes(version.spec) - set(version.checked_facts)
        reasons += [f"{c} was not part of the check" for c in sorted(missing)]
    return CheckState(checked=not reasons, status=worst(version.check_results), stale_reasons=reasons)
