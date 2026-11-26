"""Test doubles for the intake pipeline.

SHIM: ``FakeLLMClient`` here is a local stand-in. Another stream writes ``app/llm/fake.py`` with
the real ``FakeLLMClient``; the coordinator swaps the import at merge.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.llm.client import BudgetExceeded, DataBlock, Message, Stage, Usage
from app.models.search import Campaign, CampaignStatus, Source, SourceAccess
from app.schemas.json_types import CampaignCriteria
from app.sources.base import Availability, RawJob, SearchContext


class FakeLLMClient:
    """Returns canned structured output; records every call. ``respond`` may be a dict or a callable
    taking the posting text."""

    def __init__(self, respond: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
                 cost_minor: int = 3) -> None:
        self.respond = respond or {}
        self.cost_minor = cost_minor
        self.calls: list[tuple[Stage, Sequence[Message]]] = []
        self.raise_budget = False

    async def estimate_cost_minor(self, stage: Stage, messages: Sequence[Message], *, model: str | None = None) -> int:
        return 10

    async def complete(self, stage: Stage, messages: Sequence[Message], schema: type[BaseModel], *,
                       max_cost_minor: int, model: str | None = None) -> tuple[Any, Usage]:
        self.calls.append((stage, messages))
        if self.raise_budget:
            raise BudgetExceeded("cap reached")
        text = "\n".join(p.content for m in messages for p in m.parts if isinstance(p, DataBlock))
        data = self.respond(text) if callable(self.respond) else self.respond
        usage = Usage(provider="fake", model="fake-model", input_tokens=10, output_tokens=5,
                      cost_minor=self.cost_minor, currency="USD", billed=True)
        return schema.model_validate(data), usage


class ScriptedConnector:
    """A connector whose results are scripted by the test."""

    connector = "scripted"
    access = "api"
    permitted_actions = frozenset({"search", "fetch", "check_open"})

    def __init__(self, jobs: list[RawJob] | None = None, error: Exception | None = None,
                 availability: Availability = "open") -> None:
        self.jobs = jobs or []
        self.error = error
        self.availability = availability
        self.warnings: list[str] = []
        self.since_seen: list[datetime | None] = []
        self.checked: list[str] = []

    def validate_config(self, config: Any) -> dict[str, Any]:
        return dict(config)

    async def search(self, ctx: SearchContext, since: datetime | None) -> list[RawJob]:
        self.since_seen.append(since)
        if self.error:
            raise self.error
        return list(self.jobs)

    async def fetch(self, url: str) -> RawJob:
        return self.jobs[0]

    async def check_open(self, url: str) -> Availability:
        self.checked.append(url)
        if isinstance(self.availability, Exception):
            raise self.availability
        return self.availability


def raw(title: str = "Claims Analyst", employer: str = "Example Insurance", url: str | None = None,
        text: str | None = None, req: str | None = None, location: str | None = "Lusaka, Zambia",
        **extra: Any) -> RawJob:
    slug = title.lower().replace(" ", "-")
    return RawJob(
        source_url=url or f"https://jobs.example.com/{slug}-{uuid.uuid4().hex[:6]}", title=title, employer=employer,
        raw_text=text or (f"{title} at {employer}. You will analyse insurance claims, build reports and work with "
                          f"the actuarial team in Lusaka. Experience with Python and Power BI is required."),
        location_raw=location, requisition_id=req, posted_at=datetime(2026, 11, 20, tzinfo=UTC), **extra)


def make_source(name: str = "Src A", connector: str = "greenhouse") -> Source:
    return Source(connector=connector, name=name, access=SourceAccess.api, config={},
                  permitted_actions=["search", "fetch", "check_open"], enabled=True)


def make_campaign(name: str = "Actuarial", source_ids: list[uuid.UUID] | None = None) -> Campaign:
    return Campaign(name=name, status=CampaignStatus.active, criteria=CampaignCriteria(titles=["actuary"]),
                    source_ids=source_ids or [])
