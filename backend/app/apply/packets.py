"""The application packet (DESIGN.md 18.1, 18.2).

A packet is an immutable, hashed snapshot of exactly what would be sent: requisition, verified
destination, sending identity, answers, email, files by sha256, link permissions, channel and the
job version. Approvals and permits bind to one packet hash.

- **Immutable.** A packet row is never edited. Building different contents makes a new version and
  invalidates the previous one (``invalidated_at`` with what changed); building identical contents
  returns the current packet unchanged.
- **Approval does not carry over.** A new version clears the application's approval and revokes any
  outstanding permit of the old one.
- **Destination first.** The server sets ``destination.domain``, ``verified`` (the domain is the
  posting's own) and ``trusted`` (the domain is on the trusted list); a draft cannot claim them.
- **Answers come from the answer bank** when an ``answer_id`` is given (value and ``material`` read
  from the bank, never from the caller).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import errors
from app.apply.stages import add_event
from app.core import audit
from app.core.clock import utcnow
from app.models.applications import Application, ApplicationPacket, Channel
from app.models.kit import Answer, VaultDocument
from app.models.search import Job, JobSighting, TrustedSite
from app.schemas.json_types import (
    ChannelName,
    PacketAnswer,
    PacketContents,
    PacketDestination,
    PacketEmail,
    PacketFile,
)

# Paths whose change the receipt marks as material (18.2: answer, file, recipient, body). Every change,
# material or not, makes a new packet.
NON_MATERIAL = frozenset({"job_version", "requisition"})


def is_application_packet() -> Any:
    """SQL clause: the application's own packets, not message packets (wave 4 follow-ups, whose contents carry
    ``message_kind``). Every query for "the application's packet" uses it."""
    return ~type_coerce(ApplicationPacket.contents, JSONB).has_key("message_kind")


def is_message(packet: ApplicationPacket | None) -> bool:
    return packet is not None and packet.contents.message_kind is not None


class PacketError(Exception):
    def __init__(self, message: str, status: int = 422, code: str = "invalid_packet") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code  # app.apply.errors.CODES


@dataclass
class DraftAnswer:
    question: str
    value: str | None = None
    answer_id: uuid.UUID | None = None


@dataclass
class PacketDraft:
    """What the caller (Studio, dispatch, a runner meeting a new question) proposes to send."""

    channel: ChannelName
    destination_url: str
    sending_identity: str
    answers: list[DraftAnswer] = field(default_factory=list)
    email: PacketEmail | None = None
    files: list[PacketFile] = field(default_factory=list)
    link_permissions: list[str] = field(default_factory=list)
    requisition: str | None = None


def canonical_json(contents: PacketContents) -> str:
    return json.dumps(contents.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(contents: PacketContents) -> str:
    return hashlib.sha256(canonical_json(contents).encode()).hexdigest()


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    if "@" in url and "://" not in url:
        return url.rsplit("@", 1)[1].strip().lower() or None
    host = urlsplit(url if "://" in url else f"https://{url}").hostname
    return host.lower().removeprefix("www.") if host else None


def _same_site(a: str, b: str) -> bool:
    return a == b or a.endswith(f".{b}") or b.endswith(f".{a}")


async def trusted_site(session: AsyncSession, domain: str | None) -> TrustedSite | None:
    """The trusted-list entry covering ``domain`` (suffix match), if any."""
    if not domain:
        return None
    for site in (await session.scalars(select(TrustedSite))).all():
        if domain == site.domain or domain.endswith(f".{site.domain}"):
            return site
    return None


async def _posting_domains(session: AsyncSession, job: Job) -> set[str]:
    urls = [job.apply_url, *(await session.scalars(select(JobSighting.url).where(JobSighting.job_id == job.id)))]
    return {d for d in (domain_of(u) for u in urls) if d}


async def _destination(session: AsyncSession, job: Job, draft: PacketDraft) -> PacketDestination:
    if draft.channel == "email":
        if draft.email is None or not draft.email.to:
            raise PacketError("an email packet needs a recipient")
        domain = domain_of(draft.email.to[0])
        url = f"mailto:{draft.email.to[0]}"
        # Verified when the recipient's domain appears in the posting (its text or its links).
        known = await _posting_domains(session, job)
        text = (job.raw_text or "").lower()
        verified = bool(domain) and (any(_same_site(domain, d) for d in known)
                                     or draft.email.to[0].lower() in text)
    else:
        url = draft.destination_url
        domain = domain_of(url)
        if not domain:
            raise PacketError("the destination is not a URL")
        verified = any(_same_site(domain, d) for d in await _posting_domains(session, job))
    trusted = await trusted_site(session, domain) is not None
    return PacketDestination(url=url, domain=domain or "", verified=verified, trusted=trusted)


async def _answers(session: AsyncSession, drafts: list[DraftAnswer]) -> list[PacketAnswer]:
    out: list[PacketAnswer] = []
    for d in drafts:
        if d.answer_id is not None:
            answer = await session.get(Answer, d.answer_id)
            if answer is None:
                raise PacketError(f"answer {d.answer_id} not found")
            value = answer.forced_choice if answer.answer_class.value == "never" else answer.value
            if value is None:
                raise PacketError(f"answer {d.answer_id} has no value")
            out.append(PacketAnswer(question=d.question, value=value, answer_id=str(answer.id),
                                    material=answer.material))
        elif d.value is not None:
            # Typed for this packet only: material until the owner saves it to the bank.
            out.append(PacketAnswer(question=d.question, value=d.value, material=True))
        else:
            raise PacketError(f"question {d.question!r} has no answer")
    return out


async def _files(session: AsyncSession, files: list[PacketFile]) -> list[PacketFile]:
    for f in files:
        if f.kind == "vault":
            doc = await session.get(VaultDocument, uuid.UUID(f.document_id)) if f.document_id else None
            if doc is None or doc.sha256 != f.sha256:
                raise PacketError(f"vault file {f.name!r} does not match a stored document")
    return list(files)


async def _capture_posting(session: AsyncSession, app: Application, now: datetime) -> None:
    """Remember the posting as this packet saw it, so a later change is judged against it (18.4)."""
    from app.pipeline import changes

    job = await session.get(Job, app.job_id)
    if job is not None:
        await changes.capture_version(session, job, now=now)


async def assemble(session: AsyncSession, app: Application, draft: PacketDraft) -> PacketContents:
    job = await session.get(Job, app.job_id)
    assert job is not None
    return PacketContents(
        requisition=draft.requisition or job.requisition_id,
        destination=await _destination(session, job, draft),
        sending_identity=draft.sending_identity,
        answers=await _answers(session, draft.answers),
        email=draft.email,
        files=await _files(session, draft.files),
        link_permissions=list(draft.link_permissions),
        channel=draft.channel,
        job_version=job.content_hash,
    )


async def current(session: AsyncSession, application_id: uuid.UUID) -> ApplicationPacket | None:
    """The newest packet that has not been invalidated."""
    return await session.scalar(
        select(ApplicationPacket).where(ApplicationPacket.application_id == application_id,
                                        ApplicationPacket.invalidated_at.is_(None), is_application_packet())
        .order_by(ApplicationPacket.version.desc()).limit(1))


async def history(session: AsyncSession, application_id: uuid.UUID) -> list[ApplicationPacket]:
    return list((await session.scalars(select(ApplicationPacket).where(
        ApplicationPacket.application_id == application_id, is_application_packet())
        .order_by(ApplicationPacket.version.desc()))).all())


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
        return out
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        out = {}
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{prefix}[{i}]"))
        return out
    return {prefix: value}


def diff(before: PacketContents | None, after: PacketContents) -> list[dict[str, Any]]:
    """Field-level changes between two packets, each marked material or not (18.2)."""
    old = _flatten(before.model_dump(mode="json")) if before else {}
    new = _flatten(after.model_dump(mode="json"))
    changes = []
    for path in sorted(set(old) | set(new)):
        if old.get(path) != new.get(path):
            root = path.split(".", 1)[0].split("[", 1)[0]
            changes.append({"path": path, "before": old.get(path), "after": new.get(path),
                            "material": root not in NON_MATERIAL})
    return changes


async def invalidate(session: AsyncSession, app: Application, packet: ApplicationPacket, reason: str, *,
                     actor: str, now: datetime | None = None) -> None:
    """Retire a packet: its approval goes, its outstanding permits are revoked."""
    from app.apply import permits  # permits imports this module

    now = now or utcnow()
    packet.invalidated_at, packet.invalidated_reason = now, reason
    if app.approved_packet_id == packet.id:
        app.approved_packet_id = None
    await permits.revoke(session, application_id=app.id, reason=f"packet v{packet.version} invalidated: {reason}",
                         actor=actor, now=now)
    await session.flush()


@dataclass
class BuildResult:
    packet: ApplicationPacket
    created: bool
    changes: list[dict[str, Any]]
    previous: ApplicationPacket | None


async def build(session: AsyncSession, app: Application, draft: PacketDraft, *, actor: str,
                now: datetime | None = None) -> BuildResult:
    """Snapshot ``draft`` as the application's packet. Same contents: the current packet is returned.
    Different contents: a new version, the old one invalidated with what changed, approval cleared."""
    now = now or utcnow()
    await session.execute(select(Application.id).where(Application.id == app.id).with_for_update())
    contents = await assemble(session, app, draft)
    from app.apply import prepare  # the spec gate reads the tailoring checks; imported late

    outcome, reason = await prepare.spec_gate(session, app, list(contents.files))
    if outcome != "pass":
        raise PacketError(f"cannot build a packet: {reason}", 409, errors.for_spec(reason))
    digest = content_hash(contents)
    latest = await current(session, app.id)
    if latest is not None and latest.content_hash == digest:
        return BuildResult(latest, False, [], None)
    changes = diff(latest.contents if latest else None, contents)
    if latest is not None:
        material = [c["path"] for c in changes if c["material"]]
        why = f"changed: {', '.join(material) if material else ', '.join(c['path'] for c in changes)}"
        await invalidate(session, app, latest, why, actor=actor, now=now)
    version = int(await session.scalar(select(func.coalesce(func.max(ApplicationPacket.version), 0)).where(
        ApplicationPacket.application_id == app.id)) or 0) + 1
    packet = ApplicationPacket(application_id=app.id, version=version, content_hash=digest, contents=contents)
    session.add(packet)
    app.channel = Channel(draft.channel)
    await session.flush()
    await _capture_posting(session, app, now)
    await add_event(session, app.id, "packet_built", actor, {
        "version": version, "packet_hash": digest, "channel": draft.channel,
        "changes": [c["path"] for c in changes] if latest else [], "previous_hash": latest.content_hash if latest
        else None})
    await audit.record(session, actor=actor, action="packet.built", subject_type="application", subject_id=app.id,
                       detail={"packet_id": str(packet.id), "version": version, "packet_hash": digest,
                               "channel": draft.channel, "destination": contents.destination.domain,
                               "verified": contents.destination.verified, "trusted": contents.destination.trusted,
                               "files": [f.sha256 for f in contents.files],
                               "changes": changes if latest else []})
    return BuildResult(packet, True, changes, latest)


# ----- message packets (wave 4 follow-ups) -----------------------------------------------------------


async def next_version(session: AsyncSession, application_id: uuid.UUID) -> int:
    return int(await session.scalar(select(func.coalesce(func.max(ApplicationPacket.version), 0)).where(
        ApplicationPacket.application_id == application_id)) or 0) + 1


async def build_message(session: AsyncSession, app: Application, contents: PacketContents,
                        previous: ApplicationPacket | None, *, actor: str,
                        now: datetime | None = None) -> BuildResult:
    """Snapshot a message about ``app`` as an immutable, hashed packet (``contents.message_kind`` set). Same
    contents as ``previous``: it is returned. Different: a new version, ``previous`` invalidated (its approval
    and permits go). The application's own packet and approval are never touched."""
    from app.apply import permits

    if contents.message_kind is None:
        raise PacketError("a message packet needs its message kind")
    now = now or utcnow()
    await session.execute(select(Application.id).where(Application.id == app.id).with_for_update())
    digest = content_hash(contents)
    if previous is not None and previous.invalidated_at is None and previous.content_hash == digest:
        return BuildResult(previous, False, [], None)
    changes = diff(previous.contents if previous else None, contents)
    if previous is not None and previous.invalidated_at is None:
        material = [c["path"] for c in changes if c["material"]]
        previous.invalidated_at, previous.invalidated_reason = now, f"changed: {', '.join(material) or 'contents'}"
        await permits.revoke(session, packet_id=previous.id, reason=f"message packet v{previous.version} replaced",
                             actor=actor, now=now)
    packet = ApplicationPacket(application_id=app.id, version=await next_version(session, app.id),
                               content_hash=digest, contents=contents)
    session.add(packet)
    await session.flush()
    await add_event(session, app.id, "message_packet_built", actor, {
        "version": packet.version, "packet_hash": digest, "message_kind": contents.message_kind,
        "previous_hash": previous.content_hash if previous else None})
    await audit.record(session, actor=actor, action="packet.built", subject_type="application", subject_id=app.id,
                       detail={"packet_id": str(packet.id), "version": packet.version, "packet_hash": digest,
                               "channel": contents.channel, "message_kind": contents.message_kind,
                               "recipients": list(contents.email.to) if contents.email else [],
                               "changes": changes if previous else []})
    return BuildResult(packet, True, changes, previous)
