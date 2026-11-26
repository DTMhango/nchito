"""Automation policy per campaign, overridable per channel (DESIGN.md 8.1).

Modes: ``save_only`` (score and list), ``prepare`` (tailor, then wait), ``ask_then_apply`` (one
approval per application; the system applies), ``auto_apply`` (apply without asking when every gate
passes). The mode is resolved in one place, ``pipeline.decisions.resolve_mode``, so discovery, the
approval receipt and the permit check cannot disagree; this module loads what it needs and explains
the result. A campaign that is not confirmed never goes above ``prepare``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import service as settings_service
from app.models.applications import Application
from app.models.search import Campaign
from app.pipeline.decisions import MODES, SYSTEM_APPLIES_FROM, ModeResolution, RuleRef, resolve_mode
from app.pipeline.filters import campaign_record


@dataclass(frozen=True)
class Policy:
    mode: str
    channel: str | None
    reason: str
    rules: tuple[RuleRef, ...]

    @property
    def system_applies(self) -> bool:
        """The system sends once approved (owner or automatic)."""
        return MODES.index(self.mode) >= MODES.index(SYSTEM_APPLIES_FROM)

    @property
    def auto(self) -> bool:
        return self.mode == "auto_apply"

    def explain(self) -> list[dict[str, object]]:
        return [{"rule": r.rule, "value": r.effective_value, "source": r.source, "version": r.version}
                for r in self.rules]


def _policy(res: ModeResolution, channel: str | None) -> Policy:
    return Policy(mode=res.mode, channel=channel, reason=res.reason, rules=res.rules)


async def for_campaign(session: AsyncSession, campaign: Campaign | None, channel: str | None) -> Policy:
    states = await settings_service.get_all(session)
    default = states["automation.default_mode"]
    if campaign is not None:
        await session.flush()
        await session.refresh(campaign)  # server-set updated_at is its version
    record = campaign_record(campaign) if campaign is not None else {"automation": {}}
    return _policy(resolve_mode(record, channel, default_mode=default.value, default_version=f"v{default.version}"),
                   channel)


async def for_application(session: AsyncSession, app: Application, channel: str | None = None) -> Policy:
    """The policy in force for this application on ``channel`` (default: the application's channel)."""
    campaign = await session.get(Campaign, app.campaign_id) if app.campaign_id else None
    chosen = channel or (app.channel.value if app.channel else None)
    return await for_campaign(session, campaign, chosen)
