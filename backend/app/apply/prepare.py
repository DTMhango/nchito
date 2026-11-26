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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import target
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


ChannelChoice = Literal["auto", "manual"]


@dataclass
class Prepared:
    built: bool
    reason: str
    packet_id: uuid.UUID | None = None
    approval_status: str | None = None
    code: str | None = None  # app.apply.errors.CODES, when not built
    channel: str | None = None
    created: bool = False
    approval: Any = None  # approval.ApprovalOutcome | None
    changes: list[dict[str, Any]] = field(default_factory=list)


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


async def _render(session: AsyncSession, store: FileStore, app: Application, kind: str, actor: str,
                  template_key: str | None = None) -> tuple[PacketFile, str]:
    from app.docs import service as docs

    prepared = await docs.prepare(session, app, kind, template_key)  # type: ignore[arg-type]
    pdf = (await docs.render(session, store, app, prepared, "pdf", actor=actor)).document
    txt = (await docs.render(session, store, app, prepared, "txt", actor=actor)).document
    text = (await store.get(txt.file_key)).decode("utf-8")
    name = docs.download_name(prepared.model.name, kind, "pdf")
    return PacketFile(name=name, kind=kind, sha256=pdf.content_hash, document_id=str(pdf.id)), text  # type: ignore[arg-type]


async def prepare_packet(session: AsyncSession, store: FileStore, app: Application, *, actor: str = "system",
                         now: datetime | None = None, channel: ChannelChoice = "auto",
                         templates: dict[str, str] | None = None) -> Prepared:
    """Render the checked spec's CV and letter, build the packet, then let the policy act on it.

    The one server function behind the pipeline and the Studio's "Send for approval". ``channel`` ``auto``
    picks email when the role has a usable application address (``app.apply.target``) and a mailbox is
    connected, otherwise manual; ``manual`` always hands it to the owner. ``templates`` (``{cv, letter}``
    template keys) override the track and documents settings. The caller commits. Nothing is built (and the
    reason is audited, with a code from ``app.apply.errors``) when the spec is not checked, when an answer
    still waits for the owner, or when there is nowhere to apply."""
    from app.apply import approval, errors, packets

    templates = templates or {}
    version, check = await spec_state(session, app)
    if check[0] != "pass" or version is None:
        return await _waiting(session, app, check[1], actor, errors.for_spec(check[1]))
    waiting = [a.question for a in version.answers if a.outcome == "ask_owner"]
    if waiting:
        return await _waiting(session, app, f"waiting for your answer to: {', '.join(waiting)}", actor,
                              "answers_waiting")
    job = await session.get(Job, app.job_id)
    assert job is not None
    identity = await sending_identity(session)
    address = await target.apply_email(session, job)
    if channel == "auto" and address is not None and address.usable and identity:
        chosen = "email"
        destination = ""
    elif job.apply_url or address is not None:
        chosen = "manual"  # an unconfirmed address is handed to the owner, never sent by the system
        destination = job.apply_url or f"mailto:{address.address if address else ''}"
    else:
        return await _waiting(session, app, "the posting gives no email address or link to apply through", actor,
                              "no_destination")
    from app.docs.service import TemplateNotFound

    try:
        cv, _ = await _render(session, store, app, "cv", actor, templates.get("cv"))
        letter, letter_text = await _render(session, store, app, "letter", actor, templates.get("letter"))
    except TemplateNotFound as exc:
        return await _waiting(session, app, str(exc), actor, "unknown_template")
    email = None
    if chosen == "email":
        assert address is not None
        subject = str(await settings_service.get_value(session, "automation.email_subject_template")).format(
            role=job.title, employer=job.employer, requisition=job.requisition_id or "")
        email = PacketEmail(to=[address.address], subject=subject.strip(), body=letter_text.strip())
    answers = [packets.DraftAnswer(question=a.question, answer_id=uuid.UUID(a.answer_id)) if a.answer_id
               else packets.DraftAnswer(question=a.question, value=a.value)
               for a in version.answers if a.outcome == "value"]
    identity = identity if chosen == "email" else (identity or await _owner_email(session))
    if not identity:
        return await _waiting(session, app, "no sending identity: connect a mailbox or add your email to the Kit",
                              actor, "no_identity")
    draft = packets.PacketDraft(channel=chosen, destination_url=destination,  # type: ignore[arg-type]
                                sending_identity=identity, answers=answers, email=email, files=[cv, letter],
                                requisition=job.requisition_id)
    try:
        built = await packets.build(session, app, draft, actor=actor, now=now)
    except packets.PacketError as exc:
        return await _waiting(session, app, exc.message, actor, exc.code)
    outcome = await approval.after_packet_built(session, app, built.packet, now=now) if built.created else None
    return Prepared(True, "packet built", built.packet.id, outcome.status if outcome else None, channel=chosen,
                    created=built.created, approval=outcome, changes=built.changes if built.previous else [])


async def _waiting(session: AsyncSession, app: Application, reason: str, actor: str, code: str) -> Prepared:
    await audit.record(session, actor=actor, action="packet.not_built", subject_type="application",
                       subject_id=app.id, detail={"reason": reason, "code": code})
    return Prepared(False, reason, code=code)
