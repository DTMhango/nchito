"""Pause a campaign until a date (DESIGN.md 18.4): ``POST /campaigns/{id}/status`` with ``paused`` and
``paused_until`` pauses it; nothing is sent for it meanwhile (the decision table's ``campaign_ready`` gate refuses
permits and ``dispatch.recheck`` cancels a queued send); on that date, in the owner's time zone, it resumes.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import utcnow
from app.core.settings import service as settings_service
from app.models.search import Campaign, CampaignStatus


async def resume_due(session: AsyncSession, *, now: datetime | None = None) -> list[Campaign]:
    """Resume every campaign paused until a date that has come. The caller commits."""
    now = now or utcnow()
    tz = ZoneInfo(str(await settings_service.get_value(session, "general.timezone")))
    today = now.astimezone(tz).date()
    rows = list((await session.scalars(select(Campaign).where(
        Campaign.status == CampaignStatus.paused, Campaign.paused_until.is_not(None),
        Campaign.paused_until <= today).with_for_update(skip_locked=True))).all())
    for campaign in rows:
        until = campaign.paused_until
        campaign.status, campaign.paused_until = CampaignStatus.active, None
        await audit.record(session, actor="system", action="campaign.status", subject_type="campaign",
                           subject_id=campaign.id, detail={"status": "active", "resumed_after": str(until),
                                                           "automatic": True})
    await session.flush()
    return rows
