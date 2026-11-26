"""Custom facets: the owner's own yes/no questions, answered per job by the ``custom_facet`` stage.

Every answer is a paid call through the ``LLMClient`` (the production client reserves in the
budget ledger before the call and reconciles after). The posting is untrusted data. When the
budget refuses a call, the remaining jobs stay unanswered and can be backfilled again later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from app.llm.client import BudgetExceeded, BudgetExhausted, LLMClient, Message, TextPart
from app.llm.untrusted import data_block
from app.models.search import CustomFacet, Job
from app.schemas.json_types import CustomFacetValue, YesNo

STAGE = "custom_facet"


class FacetAnswer(BaseModel):
    value: YesNo
    evidence: str | None = None


def build_messages(facet: CustomFacet, job: Job) -> list[Message]:
    return [Message(role="system", parts=[TextPart(
                f"Answer the owner's question about this job posting with yes, no or not_stated, and quote "
                f"the sentence that supports the answer as evidence. Question: {facet.question}")]),
            Message(role="user", parts=[data_block(job.raw_text or job.title, "job posting")])]


async def estimate(client: LLMClient, facet: CustomFacet, jobs: Sequence[Job]) -> int:
    total = 0
    for job in jobs:
        total += await client.estimate_cost_micros(STAGE, build_messages(facet, job), schema=FacetAnswer)
    return total


@dataclass
class BackfillResult:
    answered: int = 0
    remaining: int = 0
    cost_micros: int = 0
    budget: BudgetExhausted | None = None


async def backfill(client: LLMClient, facet: CustomFacet, jobs: Sequence[Job]) -> BackfillResult:
    """Answer ``facet`` for each job, stopping at the first budget refusal."""
    result = BackfillResult()
    for index, job in enumerate(jobs):
        messages = build_messages(facet, job)
        try:
            ceiling = await client.estimate_cost_micros(STAGE, messages, schema=FacetAnswer)
            out, usage = await client.complete(STAGE, messages, FacetAnswer, max_cost_micros=ceiling)
        except BudgetExceeded as exc:
            result.budget = exc if isinstance(exc, BudgetExhausted) else None
            result.remaining = len(jobs) - index
            return result
        job.custom_facets = {**job.custom_facets,
                             facet.key: CustomFacetValue(value=out.value, evidence=out.evidence, model=usage.model)}
        result.answered += 1
        result.cost_micros += usage.cost_micros
    return result
