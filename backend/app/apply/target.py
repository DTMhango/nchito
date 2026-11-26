"""Where a role is applied to (DESIGN.md 8.2, 18.1, 18.2): the application address and the channels.

- **The posting's address is a claim, not a fact.** ``Job.apply_email`` is what the pipeline found in
  the posting (its text or a ``mailto:`` link). The owner may set another (``apply_email_owner``), which
  wins. Either way the address is **unconfirmed** until the owner confirms that exact address
  (``apply_email_confirmed``), unless its domain is on the trusted-sites list (suffix match, the same
  rule as browser destinations). Unknown is not yes.
- **Usable** means confirmed or trusted. Only a usable address is chosen for the email channel by
  :func:`app.apply.prepare.prepare_packet`, and the permit gate ``recipient_confirmed`` sends any other
  recipient back to the owner (an automatic approval never sends to an unconfirmed address).
- Changing the address retires the current packet (a recipient change is material, 18.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.models.search import Job

Found = Literal["posting_text", "posting_link", "owner"]
ADDRESS = re.compile(r"^[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+$")
QUOTE_CHARS = 160


class TargetError(Exception):
    def __init__(self, message: str, status: int = 422, code: str = "invalid_address") -> None:
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


@dataclass
class ApplyEmail:
    address: str
    found_in: Found
    evidence: str | None
    confirmed: bool
    confirmed_by: str | None
    confirmed_at: datetime | None
    trusted_domain: bool

    @property
    def usable(self) -> bool:
        return self.confirmed or self.trusted_domain


@dataclass
class ChannelCandidate:
    channel: Literal["email", "browser", "manual"]
    available: bool
    reason: str


def _same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()  # type: ignore[union-attr]


def effective_address(job: Job) -> str | None:
    return (job.apply_email_owner or job.apply_email or "").strip() or None


def evidence_quote(text: str | None, address: str) -> str | None:
    """The sentence of the posting that gives ``address`` (trimmed around it), or None."""
    if not text:
        return None
    at = text.lower().find(address.lower())
    if at < 0:
        return None
    start = max(text.rfind(".", 0, at) + 1, text.rfind("\n", 0, at) + 1, at - QUOTE_CHARS)
    stops = [i for i in (text.find(".", at + len(address)), text.find("\n", at)) if i >= 0]
    end = min([*stops, at + len(address) + QUOTE_CHARS])
    return re.sub(r"\s+", " ", text[start:end + 1]).strip() or None


async def apply_email(session: AsyncSession, job: Job) -> ApplyEmail | None:
    from app.apply import packets

    address = effective_address(job)
    if address is None:
        return None
    if job.apply_email_owner:
        found: Found = "owner"
        quote = None
    else:
        quote = evidence_quote(job.raw_text, address)
        found = "posting_text" if quote else "posting_link"
    confirmed = _same(job.apply_email_confirmed, address)
    trusted = await packets.trusted_site(session, packets.domain_of(address)) is not None
    return ApplyEmail(address=address, found_in=found, evidence=quote, confirmed=confirmed,
                      confirmed_by=job.apply_email_confirmed_by if confirmed else None,
                      confirmed_at=job.apply_email_confirmed_at if confirmed else None, trusted_domain=trusted)


async def usable_email(session: AsyncSession, job: Job) -> str | None:
    found = await apply_email(session, job)
    return found.address if found is not None and found.usable else None


async def candidates(session: AsyncSession, job: Job) -> list[ChannelCandidate]:
    """The ways this role can be applied to now, each with why (not)."""
    from app.apply import prepare
    from app.apply.channels import registry

    email = await apply_email(session, job)
    identity = await prepare.sending_identity(session)
    if email is None:
        e = ChannelCandidate("email", False, "the posting gives no application address")
    elif not email.usable:
        e = ChannelCandidate("email", False, f"{email.address} is not confirmed: confirm it to send by email")
    elif not identity:
        e = ChannelCandidate("email", False, "no mailbox is connected to send from")
    else:
        e = ChannelCandidate("email", True, f"send to {email.address} from {identity}")
    browser = ChannelCandidate(
        "browser", bool(job.apply_url) and registry.is_available("browser"),
        "no application link" if not job.apply_url else (
            "an agent fills the form on the posting's site" if registry.is_available("browser")
            else "browser runners are not part of this build"))
    destination = job.apply_url or (f"mailto:{email.address}" if email else None)
    manual = ChannelCandidate("manual", destination is not None,
                              f"you apply yourself at {destination}" if destination
                              else "no application link or address to hand over")
    return [e, browser, manual]


async def set_email(session: AsyncSession, job: Job, *, address: str | None, confirmed: bool, actor: str,
                    now: datetime | None = None) -> ApplyEmail | None:
    """Set, correct, clear or confirm the application address. ``address`` None keeps the posting's
    address (clearing an override); ``confirmed`` confirms (or withdraws confirmation of) the result."""
    from app.apply import packets
    from app.models.applications import Application

    now = now or utcnow()
    clean = address.strip() if address is not None else None
    if clean is not None and not ADDRESS.match(clean):
        raise TargetError(f"{clean!r} is not an email address")
    before = effective_address(job)
    was_confirmed = _same(job.apply_email_confirmed, before)
    job.apply_email_owner = None if clean is None or _same(clean, job.apply_email) else clean
    after = effective_address(job)
    if confirmed and after is None:
        raise TargetError("there is no application address to confirm", code="no_address")
    if confirmed:
        job.apply_email_confirmed, job.apply_email_confirmed_at, job.apply_email_confirmed_by = after, now, actor
    elif _same(job.apply_email_confirmed, after) or after is None:
        job.apply_email_confirmed = job.apply_email_confirmed_at = job.apply_email_confirmed_by = None
    await session.flush()
    if not _same(before, after) and before is not None:
        for app in (await session.scalars(select(Application).where(Application.job_id == job.id))).all():
            packet = await packets.current(session, app.id)
            if packet is not None and packet.contents.email is not None \
                    and not all(_same(t, after) for t in packet.contents.email.to):
                await packets.invalidate(session, app, packet, f"application address changed to {after or 'none'}",
                                         actor=actor, now=now)
    await audit.record(session, actor=actor, action="job.apply_email_set", subject_type="job", subject_id=job.id,
                       detail={"before": before, "after": after, "confirmed": confirmed,
                               "was_confirmed": was_confirmed, "override": job.apply_email_owner is not None})
    return await apply_email(session, job)
