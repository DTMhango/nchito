"""Test doubles and database builders for the matching tests.

``FakeLLMClient`` is a local stand-in with the same name as the LLM stream's ``app/llm/fake.py``;
swap to that one at merge.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import BudgetExceeded, DataBlock, Message, Stage, TextPart, Usage
from app.models.kit import Fact, FactKind, FactStatus
from app.models.search import (
    Availability,
    Campaign,
    CampaignStatus,
    Job,
    Rubric,
    RubricStatus,
)
from app.schemas.json_types import CampaignCriteria, JobFacets, RubricBody
from tests.pipeline.matching.helpers import NOW

Responder = Callable[[Stage, Sequence[Message], str | None], dict[str, Any]]


class FakeLLMClient:
    """Answers from a responder function; records every call; raises ``BudgetExceeded`` on cue."""

    def __init__(self, responder: Responder, *, cost: int = 7, budget_calls: int | None = None) -> None:
        self.responder = responder
        self.cost = cost
        self.budget_calls = budget_calls
        self.calls: list[tuple[Stage, Sequence[Message], str | None]] = []

    async def complete(self, stage, messages, schema: type[BaseModel], *, max_cost_minor: int, model=None):
        if self.budget_calls is not None and len(self.calls) >= self.budget_calls:
            raise BudgetExceeded("monthly cap reached")
        assert max_cost_minor >= self.cost
        self.calls.append((stage, messages, model))
        result = schema.model_validate(self.responder(stage, messages, model))
        return result, Usage("fake", model or "fake-model", 100, 50, self.cost, "USD", True)

    async def estimate_cost_minor(self, stage, messages, *, model=None) -> int:
        return self.cost

    def text_sent(self, index: int = -1) -> str:
        return "\n".join(p.text if isinstance(p, TextPart) else f"<<{p.label}>>{p.content}"
                         for m in self.calls[index][1] for p in m.parts)

    def data_blocks(self, index: int = -1) -> list[DataBlock]:
        return [p for m in self.calls[index][1] for p in m.parts if isinstance(p, DataBlock)]


def ratings(values: dict[str, int], evidence: dict[str, list[str]] | None = None, gaps: list[str] | None = None
            ) -> Responder:
    def respond(stage, messages, model):
        return {"ratings": [{"criterion": k, "rating": v, "evidence_fact_ids": (evidence or {}).get(k, ["F-1"])}
                            for k, v in values.items()], "gaps": gaps or []}
    return respond


RUBRIC = RubricBody.model_validate({
    "criteria": [{"name": "skills", "weight": 60, "anchors": {"0": "none", "5": "all"}},
                 {"name": "domain", "weight": 40, "anchors": {"0": "none", "5": "deep"}}],
})


async def add_rubric(session: AsyncSession, body: RubricBody = RUBRIC, *, status: RubricStatus = RubricStatus.active,
                     family: uuid.UUID | None = None, version: int = 1) -> Rubric:
    rubric = Rubric(name="Default", body=body, status=status, family=family or uuid.uuid4(), version=version)
    session.add(rubric)
    await session.flush()
    return rubric


async def add_campaign(session: AsyncSession, rubric: Rubric | None, *, name: str = "Analytics", priority: int = 0,
                       criteria: CampaignCriteria | None = None, **kw: Any) -> Campaign:
    campaign = Campaign(name=name, status=CampaignStatus.active, rubric_id=rubric.id if rubric else None,
                        priority=priority, criteria=criteria or CampaignCriteria(), **kw)
    session.add(campaign)
    await session.flush()
    return campaign


async def add_facts(session: AsyncSession, *codes: str, keep_out: Sequence[str] = (),
                    draft: Sequence[str] = ()) -> None:
    for code in codes:
        session.add(Fact(code=code, kind=FactKind.achievement, text=f"Invented achievement {code}",
                         status=FactStatus.draft if code in draft else FactStatus.approved,
                         keep_out_of_prompts=code in keep_out))
    await session.flush()


async def add_job(session: AsyncSession, title: str = "Data Analyst", employer: str = "Acme Example", *,
                  function: str | None = "analytics", level: str | None = None, raw_text: str = "",
                  facets: dict[str, Any] | None = None, deadline: date | None = None,
                  posted_at: datetime | None = None, recruiter: str | None = None, **kw: Any) -> Job:
    job = Job(title=title, employer=employer, canonical_employer=employer, function=function, level=level,
              raw_text=raw_text or f"{title} at {employer}. Python and SQL.",
              content_hash=hashlib.sha256(f"{title}{employer}{uuid.uuid4()}".encode()).hexdigest(),
              facets=JobFacets.model_validate(facets or {}), deadline=deadline,
              deadline_state="dated" if deadline else "not_stated", posted_at=posted_at or NOW,
              availability=Availability.open, last_checked_at=NOW, recruiter=recruiter, **kw)
    session.add(job)
    await session.flush()
    return job
