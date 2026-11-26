"""Which onboarding steps are done (DESIGN.md 13), computed from the data, never stored.

A step is done when the thing it names exists and nothing in it still needs review. Because it is
derived, the wizard resumes at the right place after any interruption and can never disagree with
the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import ReviewState
from app.models.kit import Fact, FactStatus, Person
from app.models.platform import Connection, ConnectionProvider
from app.models.search import Campaign, CampaignStatus

MAIL_PROVIDERS = (ConnectionProvider.gmail, ConnectionProvider.imap_smtp, ConnectionProvider.msgraph)


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    done: bool
    detail: str


async def compute(session: AsyncSession) -> list[Step]:
    has_person = bool(await session.scalar(select(func.count()).select_from(Person)))
    facts = int(await session.scalar(select(func.count()).select_from(Fact).where(
        Fact.status != FactStatus.retired)) or 0)
    facts_pending = int(await session.scalar(select(func.count()).select_from(Fact).where(
        Fact.status != FactStatus.retired, Fact.review_state == ReviewState.needs_review)) or 0)
    person_pending = int(await session.scalar(select(func.count()).select_from(Person).where(
        Person.review_state == ReviewState.needs_review)) or 0)
    live = Campaign.status != CampaignStatus.archived
    campaigns = int(await session.scalar(select(func.count()).select_from(Campaign).where(live)) or 0)
    campaigns_pending = int(await session.scalar(select(func.count()).select_from(Campaign).where(
        live, Campaign.review_state == ReviewState.needs_review)) or 0)
    mail = int(await session.scalar(select(func.count()).select_from(Connection).where(
        Connection.provider.in_(MAIL_PROVIDERS), Connection.enabled.is_(True))) or 0)

    kit_present = has_person or facts > 0
    pending = facts_pending + person_pending
    return [
        Step("kit_present", "Your kit is loaded", kit_present,
             "A profile or facts are in the library." if kit_present else "Upload your CV, old kit or a kit file."),
        Step("facts_confirmed", "Facts confirmed", kit_present and pending == 0 and facts > 0,
             f"{pending} item(s) still need review." if pending else
             ("Every fact is confirmed." if facts else "There are no facts to confirm yet.")),
        Step("campaign_exists", "A campaign exists", campaigns > 0,
             f"{campaigns} campaign(s)." if campaigns else "Create a campaign for the roles you want."),
        Step("criteria_confirmed", "Campaign criteria confirmed", campaigns > 0 and campaigns_pending == 0,
             f"{campaigns_pending} campaign(s) have criteria to confirm." if campaigns_pending else
             ("All campaign criteria are confirmed." if campaigns else "No campaign yet.")),
        Step("mail_connected", "A mail connection exists", mail > 0,
             "Mail is connected." if mail else "Connect the mailbox you use for the search."),
    ]
