"""``get_packet``: what a runner is given for one form (DESIGN.md 8.3, 18.1, 18.2). Invariants:

- **Destination first.** Released only when the packet's destination is the posting's own domain and is on
  the trusted list, or the owner approved this packet himself (an untrusted site is "ask me first").
- **Least data.** Only the approved current packet: its answers, the sending identity, the owner's
  ``forms_only`` / ``show_on_cv`` details, and its files under their attach rule. A vault file kept for
  after an offer is never released before one; ``hidden`` details never.
- **Record of release.** Every release is appended to ``AgentTask.released`` and audited, so the owner can
  see what already left (18.6 gate 5).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import packets
from app.core import audit
from app.gateway import files
from app.gateway.common import (
    GatewayError,
    approved_packet,
    own_task,
    require_active,
    require_scope,
    same_site,
    setting,
    task_application,
)
from app.gateway.tools import (
    EvidenceUploadIn,
    EvidenceUploadOut,
    GetPacketIn,
    GetPacketOut,
    PacketField,
    PacketFileOut,
)
from app.models.applications import AgentTask, AgentTaskType, Application, Stage
from app.models.kit import Person, Sensitivity, VaultDocument
from app.models.platform import ApiToken
from app.models.search import Job, JobSighting

AFTER_OFFER = frozenset({Stage.offer, Stage.accepted})


async def posting_domains(session: AsyncSession, job: Job) -> set[str]:
    urls = [job.apply_url, *(await session.scalars(select(JobSighting.url).where(JobSighting.job_id == job.id)))]
    return {d for d in (packets.domain_of(u) for u in urls) if d}


async def check_destination(session: AsyncSession, job: Job, packet_url: str, approved_by: str | None) -> str:
    """The destination domain, or a refusal (destination first, 18.1)."""
    domain = packets.domain_of(packet_url)
    known = await posting_domains(session, job)
    if not domain or not any(same_site(domain, d) or same_site(d, domain) for d in known):
        raise GatewayError("destination_unverified", f"{domain or 'the destination'} is not the posting's own site")
    trusted = await packets.trusted_site(session, domain) is not None
    if not trusted and (approved_by or "").startswith("system"):
        raise GatewayError("untrusted_site", f"{domain} is not on the trusted list: the owner must approve first")
    return domain


def _person_fields(person: Person | None) -> list[PacketField]:
    if person is None:
        return []
    out: list[PacketField] = []
    named = [("full_name", "Full name", person.full_name), ("preferred_name", "Preferred name", person.preferred_name),
             ("email", "Email", person.email), ("phone", "Phone", person.phone),
             ("location", "Location", person.location)]
    named += [(f"link.{k}", k, v) for k, v in (person.links or {}).items()]
    named += [(f"extra.{k}", k, v) for k, v in (person.extra_fields or {}).items()]
    for key, label, value in named:
        if value is not None and value.visibility != "hidden" and value.value:
            out.append(PacketField(key=key, label=label, value=value.value))
    return out


async def _attach_rule(session: AsyncSession, app: Application, kind: str, document_id: str | None) -> str | None:
    """``always`` / ``when_asked``, or None when the file must not be released now."""
    if kind != "vault":
        return "always"
    doc = await session.get(VaultDocument, uuid.UUID(document_id)) if document_id else None
    if doc is None:
        return None
    if doc.sensitivity == Sensitivity.after_offer_only:
        return "when_asked" if app.stage in AFTER_OFFER else None
    return "when_asked" if doc.sensitivity == Sensitivity.on_request else "always"


async def get_packet(session: AsyncSession, token: ApiToken, body: GetPacketIn, *, at: datetime) -> GetPacketOut:
    require_active(token)
    require_scope(token, "gateway:packets")
    task = await own_task(session, token, body.task_id, at=at, types=(AgentTaskType.apply,))
    app, job = await task_application(session, task)
    packet = await approved_packet(session, app)
    if packet is None:
        raise GatewayError("not_approved", "this application has no approved browser packet")
    contents = packet.contents
    domain = await check_destination(session, job, contents.destination.url, packet.approved_by)
    person = await session.scalar(select(Person).limit(1))
    fields = [PacketField(key="sending_identity", label="Email to apply with", value=contents.sending_identity)]
    if contents.requisition:
        fields.append(PacketField(key="requisition", label="Requisition", value=contents.requisition))
    fields += [f for f in _person_fields(person) if f.key != "email"]
    answers = [PacketField(key=f"answer.{i}", label=a.question, value=a.value) for i, a in enumerate(contents.answers)]
    expires = await files.lifetime(session, at)
    released_files: list[PacketFileOut] = []
    withheld: list[str] = []
    for f in contents.files:
        rule = await _attach_rule(session, app, f.kind, f.document_id)
        if rule is None:
            withheld.append(f.name)
            continue
        signed = files.sign("file", {"t": str(task.id), "f": f.sha256}, expires=expires)
        released_files.append(PacketFileOut(name=f.name, kind=f.kind, sha256=f.sha256,
                                            download_url=files.absolute(files.download_path(signed)),
                                            attach_rule=rule))  # type: ignore[arg-type]
    record = {"at": at.isoformat(), "runner": token.name, "packet_version": packet.version,
              "packet_hash": packet.content_hash, "destination": domain, "fields": [f.key for f in fields],
              "answers": [{"question": a.label, "value": a.value} for a in answers],
              "files": [{"name": f.name, "sha256": f.sha256, "attach_rule": f.attach_rule} for f in released_files],
              "withheld_files": withheld, "dry_run": bool(task.payload.get("dry_run"))}
    task.released = {**task.released, "given": [*(task.released.get("given") or []), record]}
    await audit.record(session, actor=f"runner:{token.name}", action="gateway.packet_released",
                       subject_type="agent_task", subject_id=task.id,
                       detail={**record, "application_id": str(app.id)})
    return GetPacketOut(packet_version=packet.version, packet_hash=packet.content_hash, destination_domain=domain,
                        fields=fields, answers=answers, files=released_files)


async def evidence_upload_url(session: AsyncSession, token: ApiToken, body: EvidenceUploadIn, *,
                              at: datetime) -> EvidenceUploadOut:
    task: AgentTask = await own_task(session, token, body.task_id, at=at)
    ref = f"ev_{secrets.token_urlsafe(9)}"
    expires = await files.lifetime(session, at)
    signed = files.sign("upload", {"t": str(task.id), "r": ref, "ct": body.content_type}, expires=expires)
    max_bytes = int(await setting(session, "runners.evidence_max_kb")) * 1024
    return EvidenceUploadOut(upload_url=files.absolute(files.upload_path(signed)), ref=f"evidence:{task.id}/{ref}",
                             max_bytes=max_bytes, expires_at=expires.isoformat())
