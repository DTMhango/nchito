"""Manual handoff (DESIGN.md 8.2, 18.1, 18.2): the owner submits; the system records it.

- The kit is built from the **current packet** only: the posting link, the final files, the answers as a
  copyable sheet, and the remaining steps. Reading it changes nothing.
- **Mark submitted** closes the open attempt (manual hand-off, or any uncertain send the owner has checked)
  as ``sent`` with the owner's evidence (the reference number, or the owner's mark). Without an open
  attempt it goes through the same permit and attempt as an automatic send (the packet must be the
  approved, current one), so duplicate protection, the employer limit and the audit apply exactly as for
  an automatic send. A role with no approved packet uses "I applied myself" instead.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import dispatch, outcomes, packets
from app.core.clock import utcnow
from app.models.applications import Application, DispatchAttempt, DispatchStatus
from app.models.search import Job
from app.schemas.json_types import PacketContents, PacketFile


class HandoffError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class HandoffKit:
    posting_url: str | None
    files: list[str] = field(default_factory=list)
    answers: list[dict[str, str]] = field(default_factory=list)
    remaining_steps: list[str] = field(default_factory=list)


def _file_url(app: Application, f: PacketFile) -> str | None:
    """Where the owner downloads a packet file (behind the owner's session)."""
    if f.share_link:
        return f.share_link
    if f.kind == "vault" and f.document_id:
        return f"/api/kit/vault/{f.document_id}/download"
    if f.kind in ("cv", "letter") and f.document_id:  # the exact rendered file the packet's hash names
        return f"/api/applications/{app.id}/document-files/{f.document_id}"
    if f.kind in ("cv", "letter"):
        return f"/api/applications/{app.id}/documents/{f.kind}?fmt=pdf"
    return None


def _steps(contents: PacketContents, posting_url: str | None, files: list[str]) -> list[str]:
    steps = []
    if contents.email is not None:
        to = ", ".join(contents.email.to)
        steps.append(f"Email {to} from {contents.sending_identity} with the subject \"{contents.email.subject}\"")
        steps.append("Paste the letter as the message body")
        if files:
            steps.append(f"Attach {len(files)} file(s)")
    else:
        steps.append(f"Open {posting_url or contents.destination.url} and sign in if it asks")
        if contents.answers:
            steps.append(f"Fill in {len(contents.answers)} answer(s) from the sheet")
        if files:
            steps.append(f"Upload {len(files)} file(s)")
        steps.append("Submit the form")
    steps.append("Come back and mark it submitted, with the reference number if you were given one")
    return steps


async def kit(session: AsyncSession, app: Application) -> HandoffKit:
    packet = await packets.current(session, app.id)
    if packet is None:
        raise HandoffError("no packet has been built", 404)
    contents = packet.contents
    job = await session.get(Job, app.job_id)
    posting_url = contents.destination.url if not contents.destination.url.startswith("mailto:") else (
        job.apply_url if job else None)
    files = [u for u in (_file_url(app, f) for f in contents.files) if u]
    answers = [{"question": a.question, "value": a.value} for a in contents.answers]
    return HandoffKit(posting_url=posting_url, files=files, answers=answers,
                      remaining_steps=_steps(contents, posting_url, files))


def answers_sheet(contents: PacketContents) -> str:
    """The packet's answers as a plain copyable sheet (the ``kind=answers`` document)."""
    if not contents.answers:
        return "This application has no form answers.\n"
    return "\n".join(f"{a.question}\n{a.value or ''}\n" for a in contents.answers)


async def _open_attempt(session: AsyncSession, app_id: uuid.UUID) -> DispatchAttempt | None:
    return await session.scalar(select(DispatchAttempt).where(
        DispatchAttempt.application_id == app_id, DispatchAttempt.status.in_(outcomes.OPEN_STATUSES))
        .order_by(DispatchAttempt.created_at.desc()).limit(1).with_for_update())


async def mark_submitted(session: AsyncSession, app: Application, *, reference: str | None, note: str | None,
                         actor: str, now: datetime | None = None) -> DispatchAttempt:
    now = now or utcnow()
    await outcomes.lock_application(session, app.id)
    attempt = await _open_attempt(session, app.id)
    if attempt is None:
        packet = await packets.current(session, app.id)
        if packet is None or app.approved_packet_id != packet.id:
            raise HandoffError("nothing approved is waiting to be submitted: use 'I applied myself' instead")
        if packet.contents.channel != "manual":
            raise HandoffError(f"this packet is for the {packet.contents.channel} channel; it is sent by the system")
        queued = await dispatch.queue(session, app.id, actor=actor, now=now)
        if not queued.queued or queued.attempt is None:
            raise HandoffError(f"not allowed now: {queued.reason}")
        attempt = queued.attempt
    elif attempt.status == DispatchStatus.reserved and attempt.started_at is None \
            and attempt.channel.value != "manual":
        raise HandoffError("this send is still queued for the system; cancel it first if you sent it yourself")
    await outcomes.settle_sent_by_owner(session, attempt, reference=reference, note=note, actor=actor, now=now)
    return attempt
