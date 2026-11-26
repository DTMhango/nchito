"""What the pack is built from: the packet actually submitted, so the owner prepares on exactly what the
employer has (DESIGN.md 10.3a).

Order: the submitted packet (``Application.submitted_snapshot.packet_hash``, else the approved packet once
the application has gone out); its CV and letter files name rendered documents, whose ``spec_hash`` names
the spec version that was sent; its answers are the answers given. With no packet (applied by hand), the
latest spec version whose check still holds. With neither, the pack rests on the Kit and the posting
only, and says so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply.stages import POST_SUBMIT
from app.models.applications import Application, ApplicationPacket, ApplicationSpecVersion
from app.models.documents import ApplicationDocument
from app.models.search import Job
from app.pipeline.checks import service as checks
from app.pipeline.checks.kit import KitView
from app.schemas.json_types import ApplicationSpec, PacketAnswer

Source = Literal["submitted_packet", "latest_checked_spec", "none"]


class Basis(BaseModel):
    """Stored on the pack (``InterviewPack.basis``) and shown with it."""

    source: Source
    packet_id: str | None = None
    packet_hash: str | None = None
    spec_version: int | None = None
    spec_hash: str | None = None
    job_hash_applied: str | None = Field(default=None, description="The posting's content hash when packed")
    job_hash_now: str | None = None
    posting_changed: bool = False
    answers: list[PacketAnswer] = Field(default_factory=list, description="Answers given on the form")


@dataclass
class Resolved:
    basis: Basis
    spec: ApplicationSpec | None = None
    answers: list[PacketAnswer] = field(default_factory=list)


async def submitted_packet(session: AsyncSession, app: Application) -> ApplicationPacket | None:
    if app.submitted_snapshot is not None:
        packet = await session.scalar(select(ApplicationPacket).where(
            ApplicationPacket.application_id == app.id,
            ApplicationPacket.content_hash == app.submitted_snapshot.packet_hash))
        if packet is not None:
            return packet
    if app.approved_packet_id is not None and app.stage in POST_SUBMIT:
        return await session.get(ApplicationPacket, app.approved_packet_id)
    return None


async def _spec_of_packet(session: AsyncSession, packet: ApplicationPacket) -> ApplicationSpecVersion | None:
    doc_ids = [uuid.UUID(f.document_id) for f in packet.contents.files
               if f.kind in ("cv", "letter") and f.document_id]
    if not doc_ids:
        return None
    hashes = set((await session.scalars(select(ApplicationDocument.spec_hash).where(
        ApplicationDocument.id.in_(doc_ids)))).all())
    if len(hashes) != 1:
        return None  # files from different specs (or none found): do not guess which was "the" spec
    return await session.scalar(select(ApplicationSpecVersion).where(
        ApplicationSpecVersion.application_id == packet.application_id,
        ApplicationSpecVersion.content_hash == hashes.pop()).order_by(ApplicationSpecVersion.version.desc()).limit(1))


async def latest_checked(session: AsyncSession, app: Application, kit: KitView) -> ApplicationSpecVersion | None:
    rows = (await session.scalars(select(ApplicationSpecVersion).where(
        ApplicationSpecVersion.application_id == app.id).order_by(ApplicationSpecVersion.version.desc()))).all()
    for v in rows:
        if (await checks.state(session, v, kit)).checked:
            return v
    return None


async def resolve(session: AsyncSession, app: Application | None, job: Job, kit: KitView) -> Resolved:
    if app is None:
        return Resolved(Basis(source="none", job_hash_now=job.content_hash))
    packet = await submitted_packet(session, app)
    if packet is not None:
        version = await _spec_of_packet(session, packet)
        answers = list(packet.contents.answers)
        applied = packet.contents.job_version
        return Resolved(Basis(
            source="submitted_packet", packet_id=str(packet.id), packet_hash=packet.content_hash,
            spec_version=version.version if version else None, spec_hash=version.content_hash if version else None,
            job_hash_applied=applied, job_hash_now=job.content_hash,
            posting_changed=bool(applied and applied != job.content_hash), answers=answers),
            spec=version.spec if version else None, answers=answers)
    version = await latest_checked(session, app, kit)
    if version is not None:
        answers = [PacketAnswer(question=a.question, value=a.value, answer_id=a.answer_id, material=a.material)
                   for a in version.answers if a.outcome == "value" and a.value]
        return Resolved(Basis(source="latest_checked_spec", spec_version=version.version,
                              spec_hash=version.content_hash, job_hash_now=job.content_hash, answers=answers),
                        spec=version.spec, answers=answers)
    return Resolved(Basis(source="none", job_hash_now=job.content_hash))
