"""What the Studio endpoints do: read the spec state, save an owner edit, re-run the checks.

An owner edit always becomes a new spec version (unless the content is unchanged) and is checked at
once by the code checks; the model claim check runs only on request (``POST /check``) or after a
tailored draft. Editing the spec changes the documents, so an approved packet is invalidated.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import stages
from app.core import audit
from app.core.clock import utcnow
from app.llm.client import LLMClient
from app.models.applications import (
    Application,
    ApplicationPacket,
    ApplicationSpecVersion,
    Stage,
    TailoringRequest,
)
from app.pipeline.checks import service as checks
from app.pipeline.checks.items import content_hash
from app.pipeline.tailoring.service import TailoringError
from app.schemas.json_types import ApplicationSpec, CheckResult

EDITABLE = frozenset({Stage.shortlisted, Stage.tailoring, Stage.ready})


@dataclass
class SpecState:
    version: ApplicationSpecVersion | None
    state: checks.CheckState | None
    versions: list[ApplicationSpecVersion]
    request: TailoringRequest | None


async def spec_state(session: AsyncSession, app: Application, version: int | None = None) -> SpecState:
    rows = list((await session.scalars(select(ApplicationSpecVersion).where(
        ApplicationSpecVersion.application_id == app.id).order_by(ApplicationSpecVersion.version.desc()))).all())
    chosen = next((r for r in rows if r.version == version), None) if version is not None else (rows[0] if rows
                                                                                                 else None)
    if version is not None and chosen is None:
        raise TailoringError(f"version {version} not found", 404)
    req = await session.scalar(select(TailoringRequest).where(TailoringRequest.application_id == app.id)
                               .order_by(TailoringRequest.created_at.desc()).limit(1))
    state = await checks.state(session, chosen) if chosen is not None else None
    return SpecState(version=chosen, state=state, versions=rows, request=req)


async def _invalidate_packet(session: AsyncSession, app: Application, reason: str, actor: str) -> None:
    if app.approved_packet_id is None:
        return
    packet = await session.get(ApplicationPacket, app.approved_packet_id, with_for_update=True)
    if packet is not None and packet.invalidated_at is None:
        packet.invalidated_at = utcnow()
        packet.invalidated_reason = reason
        await audit.record(session, actor=actor, action="packet.invalidated", subject_type="application_packet",
                           subject_id=packet.id, detail={"application_id": str(app.id), "reason": reason})
    app.approved_packet_id = None


async def owner_edit(session: AsyncSession, app: Application, spec: ApplicationSpec, *,
                     actor: str) -> ApplicationSpecVersion:
    """Save the owner's spec as a new version and run the code checks on it."""
    if app.stage not in EDITABLE:
        raise TailoringError(f"the documents of an application in {app.stage.value} can no longer be edited")
    latest = await checks.latest_version(session, app.id)
    digest = content_hash(spec)
    if latest is not None and latest.content_hash == digest:
        await checks.check_version(session, latest, actor=actor)
        return latest
    version = ApplicationSpecVersion(
        application_id=app.id, version=await checks.next_version_number(session, app.id), origin="owner",
        parent_version=latest.version if latest else None, spec=spec, content_hash=digest,
        answers=list(latest.answers) if latest else [], created_by=actor)
    session.add(version)
    app.spec = spec
    await session.flush()
    await checks.check_version(session, version, actor=actor)
    await _invalidate_packet(session, app, f"documents edited (spec version {version.version})", actor)
    await stages.add_event(session, app.id, "spec_version", actor, {
        "version": version.version, "origin": "owner", "content_hash": digest,
        "status": checks.worst(version.check_results)})
    await audit.record(session, actor=actor, action="application.spec_edited", subject_type="application",
                       subject_id=app.id, detail={"version": version.version, "content_hash": digest,
                                                  "parent_version": version.parent_version})
    return version


async def recheck(session: AsyncSession, app: Application, client: LLMClient | None, *,
                  actor: str) -> list[CheckResult]:
    latest = await checks.latest_version(session, app.id)
    if latest is None:
        raise TailoringError("there is no draft to check yet: tailor it or save a spec first")
    results, _ = await checks.check_version(session, latest, client=client, actor=actor)
    return results
