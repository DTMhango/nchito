"""From a checked spec to a packet (DESIGN.md 8, 9, 18.2): the seam between tailoring, render and apply.

- **Checked spec only.** A packet that carries generated documents (CV, letter) is built and approved only
  from the application's latest spec version while its check is current (``checked``) and not blocking.
  ``spec_gate`` is the one check: packets refuse to build without it, and it runs as the permit gate
  ``spec_checked`` at approval, at the permit and again at dispatch.
- **Documents by content hash.** Each generated file in a packet names the ``application_document`` row it
  came from (``document_id``) and its sha256; the row must belong to the application and be rendered from
  the checked spec version. The email channel attaches exactly those bytes.
- **Policy decides what happens next.** :func:`prepare_packet` renders, builds and then hands the packet to
  ``approval.after_packet_built`` (automatic approval, an approval request, or nothing in ``prepare``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import mail_connections
from app.connect.filestore import FileStore
from app.core import audit
from app.core.settings import service as settings_service
from app.models.applications import Application, ApplicationSpecVersion
from app.models.documents import ApplicationDocument
from app.models.search import Job
from app.schemas.json_types import PacketEmail, PacketFile

GENERATED = frozenset({"cv", "letter"})
Check = tuple[str, str]


@dataclass
class Prepared:
    built: bool
    reason: str
    packet_id: uuid.UUID | None = None
    approval_status: str | None = None


async def latest_spec(session: AsyncSession, app_id: uuid.UUID) -> ApplicationSpecVersion | None:
    return await session.scalar(select(ApplicationSpecVersion).where(
        ApplicationSpecVersion.application_id == app_id).order_by(ApplicationSpecVersion.version.desc()).limit(1))


async def spec_state(session: AsyncSession, app: Application) -> tuple[ApplicationSpecVersion | None, Check]:
    """The latest spec version and whether a packet may be built from it."""
    from app.pipeline.checks import service as checks

    version = await latest_spec(session, app.id)
    if version is None:
        return None, ("fail", "no tailored spec")
    state = await checks.state(session, version)
    if not state.checked:
        return version, ("fail", f"the check of spec v{version.version} is stale: {'; '.join(state.stale_reasons)}")
    if state.status == "block":
        return version, ("fail", f"the check of spec v{version.version} blocks")
    return version, ("pass", f"spec v{version.version} checked ({state.status})")


async def spec_gate(session: AsyncSession, app: Application, files: list[PacketFile]) -> Check:
    """Generated files must come from the checked spec; a packet without generated files passes."""
    generated = [f for f in files if f.kind in GENERATED]
    if not generated:
        return "pass", "no generated documents in this packet"
    version, check = await spec_state(session, app)
    if check[0] != "pass" or version is None:
        return check
    for f in generated:
        try:
            doc = await session.get(ApplicationDocument, uuid.UUID(f.document_id)) if f.document_id else None
        except ValueError:
            doc = None
        if (doc is None or doc.application_id != app.id or doc.content_hash != f.sha256 or doc.kind != f.kind
                or doc.spec_hash != version.content_hash):
            return "fail", f"{f.name} is not a document rendered from the checked spec v{version.version}"
    return check


async def sending_identity(session: AsyncSession) -> str | None:
    """The address the connected mailbox sends as (the first enabled mail connection)."""
    for conn in await mail_connections.mail_connections(session):
        address = str(conn.config.get("from_address") or "").strip()
        if address:
            return address
    return None


async def _owner_email(session: AsyncSession) -> str | None:
    from app.kit import service as kit_service

    person = await kit_service.get_person(session)
    return person.email.value if person is not None and person.email is not None else None


async def _render(session: AsyncSession, store: FileStore, app: Application, kind: str, actor: str
                  ) -> tuple[PacketFile, str]:
    from app.docs import service as docs

    prepared = await docs.prepare(session, app, kind)  # type: ignore[arg-type]
    pdf = (await docs.render(session, store, app, prepared, "pdf", actor=actor)).document
    txt = (await docs.render(session, store, app, prepared, "txt", actor=actor)).document
    text = (await store.get(txt.file_key)).decode("utf-8")
    name = docs.download_name(prepared.model.name, kind, "pdf")
    return PacketFile(name=name, kind=kind, sha256=pdf.content_hash, document_id=str(pdf.id)), text  # type: ignore[arg-type]


async def prepare_packet(session: AsyncSession, store: FileStore, app: Application, *, actor: str = "system",
                         now: datetime | None = None) -> Prepared:
    """Render the checked spec's CV and letter, build the packet, then let the policy act on it.
    The caller commits. Nothing is built (and the reason is audited) when the spec is not checked, when an
    answer still waits for the owner, or when the posting gives no address to apply to."""
    from app.apply import approval, packets

    version, check = await spec_state(session, app)
    if check[0] != "pass" or version is None:
        return await _waiting(session, app, check[1], actor)
    waiting = [a.question for a in version.answers if a.outcome == "ask_owner"]
    if waiting:
        return await _waiting(session, app, f"waiting for your answer to: {', '.join(waiting)}", actor)
    job = await session.get(Job, app.job_id)
    assert job is not None
    identity = await sending_identity(session)
    if job.apply_email and identity:
        channel = "email"
    elif job.apply_url:
        channel = "manual"
    else:
        return await _waiting(session, app, "the posting gives no email address or link to apply through"
                              if not job.apply_email else "no mailbox is connected to send from", actor)
    cv, _ = await _render(session, store, app, "cv", actor)
    letter, letter_text = await _render(session, store, app, "letter", actor)
    email = None
    if channel == "email":
        subject = str(await settings_service.get_value(session, "automation.email_subject_template")).format(
            role=job.title, employer=job.employer, requisition=job.requisition_id or "")
        email = PacketEmail(to=[str(job.apply_email)], subject=subject.strip(), body=letter_text.strip())
    answers = [packets.DraftAnswer(question=a.question, answer_id=uuid.UUID(a.answer_id)) if a.answer_id
               else packets.DraftAnswer(question=a.question, value=a.value)
               for a in version.answers if a.outcome == "value"]
    identity = identity if channel == "email" else (identity or await _owner_email(session))
    if not identity:
        return await _waiting(session, app, "no sending identity: connect a mailbox or add your email to the Kit",
                              actor)
    draft = packets.PacketDraft(channel=channel, destination_url=job.apply_url or "",  # type: ignore[arg-type]
                                sending_identity=identity, answers=answers, email=email, files=[cv, letter],
                                requisition=job.requisition_id)
    try:
        built = await packets.build(session, app, draft, actor=actor, now=now)
    except packets.PacketError as exc:
        return await _waiting(session, app, exc.message, actor)
    outcome = await approval.after_packet_built(session, app, built.packet, now=now) if built.created else None
    return Prepared(True, "packet built", built.packet.id, outcome.status if outcome else None)


async def _waiting(session: AsyncSession, app: Application, reason: str, actor: str) -> Prepared:
    await audit.record(session, actor=actor, action="packet.not_built", subject_type="application",
                       subject_id=app.id, detail={"reason": reason})
    return Prepared(False, reason)
