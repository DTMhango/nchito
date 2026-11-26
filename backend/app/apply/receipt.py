"""The approval receipt (DESIGN.md 18.2): the one screen the owner approves from.

Built from the current packet and the same gate evaluation an owner approval runs, so what the owner
sees is what the approval checks. Pay and work-rights answers are picked out by the
``automation.receipt_*_terms`` settings; anything else material is listed as an unusual disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import gates, packets, policy
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.applications import Application, ApplicationPacket
from app.models.search import Job
from app.schemas.json_types import PacketContents


@dataclass
class Receipt:
    packet: ApplicationPacket
    employer: str
    destination: str
    role: str
    pay_answers: list[str]
    work_rights_answers: list[str]
    attachments: list[str]
    unusual_disclosures: list[str]
    changes_since_last_look: list[dict[str, Any]]
    action_label: str
    gates: list[dict[str, Any]]


def action_label(contents: PacketContents) -> str:
    if contents.channel == "email":
        to = ", ".join(contents.email.to) if contents.email else contents.destination.domain
        return f"Send email to {to}"
    if contents.channel == "browser":
        return f"Let the agent submit on {contents.destination.domain}"
    return "Approve for you to submit by hand"


def _matches(question: str, terms: list[str]) -> bool:
    q = question.casefold()
    return any(t.casefold() in q for t in terms)


async def _previous(session: AsyncSession, packet: ApplicationPacket) -> ApplicationPacket | None:
    return await session.scalar(select(ApplicationPacket).where(
        ApplicationPacket.application_id == packet.application_id, ApplicationPacket.version < packet.version,
        packets.is_application_packet())
        .order_by(ApplicationPacket.version.desc()).limit(1))


async def build(session: AsyncSession, app: Application, *, now: datetime | None = None) -> Receipt | None:
    now = now or utcnow()
    packet = await packets.current(session, app.id)
    if packet is None:
        return None
    job = await session.get(Job, app.job_id)
    assert job is not None
    contents = packet.contents
    pay_terms = list(await settings_service.get_value(session, "automation.receipt_pay_terms"))
    rights_terms = list(await settings_service.get_value(session, "automation.receipt_work_rights_terms"))
    pay = [f"{a.question}: {a.value}" for a in contents.answers if _matches(a.question, pay_terms)]
    rights = [f"{a.question}: {a.value}" for a in contents.answers
              if _matches(a.question, rights_terms) and not _matches(a.question, pay_terms)]
    unusual = [f"{a.question}: {a.value}" for a in contents.answers if a.material
               and not _matches(a.question, pay_terms) and not _matches(a.question, rights_terms)]
    unusual += [f"vault file {f.name}" for f in contents.files if f.kind == "vault"]
    unusual += [f"shared link: {p}" for p in contents.link_permissions]
    if not contents.destination.verified:
        unusual.append(f"destination {contents.destination.domain} is not confirmed as the posting's own")
    if contents.channel == "browser" and not contents.destination.trusted:
        unusual.append(f"{contents.destination.domain} is not on the trusted list")
    previous = await _previous(session, packet)
    channel = contents.channel or "manual"
    evaluation = await gates.evaluate(session, app, packet, channel=channel, approval="owner",
                                      packet_hash=packet.content_hash, for_approval=True, now=now)
    pol = await policy.for_application(session, app, channel)
    policy_ok = pol.system_applies or channel == "manual"
    gate_rows = [{"gate": "policy", "passed": policy_ok, "outcome": "pass" if policy_ok else "fail",
                  "detail": pol.reason},
                 {"gate": "approval", "passed": evaluation.status == "granted",
                  "outcome": "pass" if evaluation.status == "granted" else "fail", "detail": evaluation.reason},
                 *evaluation.gate_results()]
    return Receipt(
        packet=packet, employer=job.employer, destination=contents.destination.url, role=job.title,
        pay_answers=pay, work_rights_answers=rights,
        attachments=[f"{f.name} ({f.kind}, sha256 {f.sha256[:12]})" for f in contents.files],
        unusual_disclosures=unusual,
        changes_since_last_look=packets.diff(previous.contents, contents) if previous else [],
        action_label=action_label(contents), gates=gate_rows)
