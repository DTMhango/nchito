"""What a message about an application starts from: who the application went to, the mail thread to reply
in, whether the employer has written back, and the interview round (all read, nothing written).

Unknown is not yes: an application whose sent address cannot be established has no "address it was sent
to", so it can never get an automatic follow-up; a linked thread with any message in it counts as a reply.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import packets, prepare
from app.connect import mail_connections
from app.models.applications import (
    Application,
    ApplicationPacket,
    DispatchAttempt,
    DispatchStatus,
    InterviewPack,
    InterviewRound,
    MailThread,
)
from app.models.search import Job

DELIVERED = (DispatchStatus.sent, DispatchStatus.acknowledged)


def norm(address: str) -> str:
    return address.strip().lower()


@dataclass
class MessageContext:
    app: Application
    job: Job
    sent_packet: ApplicationPacket | None = None  # the application packet that went out by email
    sent_attempt: DispatchAttempt | None = None
    sent_to: list[str] = field(default_factory=list)  # addresses the application itself went to
    threads: list[MailThread] = field(default_factory=list)  # linked threads, newest first
    sending_identity: str | None = None
    round: InterviewRound | None = None

    @property
    def thread(self) -> MailThread | None:
        return self.threads[0] if self.threads else None

    @property
    def employer_replied(self) -> bool:
        """Any message in any thread linked to the application (our own mail is never recorded there)."""
        return any(t.provider_message_ids for t in self.threads)

    @property
    def reply_senders(self) -> list[str]:
        return [norm(t.sender) for t in self.threads if t.sender]

    @property
    def known(self) -> list[str]:
        """Addresses a message may go to without a fresh confirmation: where the application went and who
        wrote back."""
        out: list[str] = []
        for a in [*self.sent_to, *self.reply_senders]:
            if a not in out:
                out.append(a)
        return out


async def _sent_application(session: AsyncSession, app_id: uuid.UUID
                            ) -> tuple[ApplicationPacket | None, DispatchAttempt | None]:
    rows = (await session.execute(
        select(DispatchAttempt, ApplicationPacket).join(ApplicationPacket,
                                                        ApplicationPacket.id == DispatchAttempt.packet_id)
        .where(DispatchAttempt.application_id == app_id, DispatchAttempt.status.in_(DELIVERED),
               packets.is_application_packet())
        .order_by(DispatchAttempt.created_at.desc()).limit(1))).first()
    return (rows[1], rows[0]) if rows else (None, None)


async def load(session: AsyncSession, app: Application) -> MessageContext:
    job = await session.get(Job, app.job_id)
    assert job is not None
    packet, attempt = await _sent_application(session, app.id)
    sent_to: list[str] = []
    if packet is not None and packet.contents.channel == "email" and packet.contents.email is not None:
        sent_to = [norm(a) for a in [*packet.contents.email.to, *packet.contents.email.cc]]
    threads = list((await session.scalars(select(MailThread).where(MailThread.application_id == app.id)
                                          .order_by(MailThread.last_message_at.desc().nulls_last()))).all())
    identity = packet.contents.sending_identity if packet is not None and packet.contents.channel == "email" else None
    identity = identity or await prepare.sending_identity(session)
    pack = await session.scalar(select(InterviewPack).where(InterviewPack.job_id == job.id))
    round_ = None
    if pack is not None:
        round_ = await session.scalar(select(InterviewRound).where(InterviewRound.pack_id == pack.id)
                                      .order_by(InterviewRound.round_number.desc()).limit(1))
    return MessageContext(app=app, job=job, sent_packet=packet, sent_attempt=attempt, sent_to=sent_to,
                          threads=threads, sending_identity=identity, round=round_)


async def thread_ref(session: AsyncSession, ctx: MessageContext) -> tuple[uuid.UUID | None, str | None]:
    """The thread a message replies in: the newest linked thread; else, for an IMAP/SMTP mailbox, the
    application's own sent Message-ID (In-Reply-To). Gmail needs its own thread id, so without a linked thread
    the message starts a new one (its subject still says "Re:")."""
    if ctx.thread is not None:
        return ctx.thread.id, ctx.thread.provider_thread_id
    if ctx.sent_attempt is not None and ctx.sent_attempt.provider_message_id and ctx.sending_identity:
        conn = await mail_connections.resolve_for_identity(session, ctx.sending_identity)
        if conn is not None and conn.provider.value != "gmail":
            return None, ctx.sent_attempt.provider_message_id
    return None, None


def base_subject(ctx: MessageContext) -> str:
    if ctx.thread is not None and ctx.thread.subject:
        return ctx.thread.subject
    if ctx.sent_packet is not None and ctx.sent_packet.contents.email is not None:
        return ctx.sent_packet.contents.email.subject
    return f"{ctx.job.title} ({ctx.job.employer})"


def reply_subject(subject: str, prefix: str) -> str:
    return subject if not prefix or subject.lower().startswith(prefix.strip().lower()) else f"{prefix}{subject}"


def default_recipients(ctx: MessageContext) -> list[str]:
    """Reply to whoever wrote last; otherwise to where the application went."""
    if ctx.reply_senders:
        return [ctx.reply_senders[0]]
    return list(ctx.sent_to[:1])
