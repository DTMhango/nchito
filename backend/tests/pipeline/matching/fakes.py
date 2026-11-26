"""Test doubles and database builders for the matching tests.

``FakeLLMClient`` is a thin adapter over ``app.llm.fake.FakeLLMClient``: replies come from a
responder ``(stage, messages, model) -> dict``, and ``budget_calls`` makes calls after the first N
hit the budget.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import fake
from app.llm.client import BudgetExhausted, DataBlock, Message, Stage, TextPart
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


class FakeLLMClient(fake.FakeLLMClient):
    def __init__(self, responder: Responder, *, cost: int = 7, budget_calls: int | None = None) -> None:
        super().__init__(cost_micros=cost, estimate_micros=cost, default=self._reply)
        self.responder = responder
        self.budget_calls = budget_calls

    def _reply(self, call: fake.FakeCall) -> Any:
        if self.budget_calls is not None and len(self.calls) > self.budget_calls:
            self.calls.pop()  # a refused call never reached the model
            return BudgetExhausted("monthly", needed_micros=self.cost_micros, available_micros=0,
                                   currency=self.currency)
        return self.responder(call.stage, call.messages, call.model)  # type: ignore[arg-type]

    def text_sent(self, index: int = -1) -> str:
        return "\n".join(p.text if isinstance(p, TextPart) else f"<<{p.label}>>{p.content}"
                         for m in self.calls[index].messages for p in m.parts)

    def data_blocks(self, index: int = -1) -> list[DataBlock]:
        return [p for m in self.calls[index].messages for p in m.parts if isinstance(p, DataBlock)]


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
