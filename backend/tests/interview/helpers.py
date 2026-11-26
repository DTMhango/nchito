"""Scripted replies for the interview pack tests (invented people and employers only; see tests.tailoring)."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.fake import FakeCall, FakeLLMClient
from app.models.applications import InterviewSectionVersion

GOOD: dict[str, dict[str, Any]] = {
    "RoleBriefReply": {"summary": "A data analyst role focused on SQL reporting.", "emphasised": ["SQL"],
                       "requirements": ["SQL and reporting automation"], "level_notes": "Individual contributor.",
                       "company_notes": ["The posting says the team supports sales."]},
    "WhyYou": {"points": [{"requirement": "SQL and reporting automation",
                           "point": {"text": "Cut monthly reporting time by 40% by automating the sales pack.",
                                     "fact_ids": ["F-1"]}}]},
    "Questions": {"items": [
        {"category": "behavioural", "question": "Tell us about automating a report.", "why_asked": "",
         "answer": {"text": "I cut monthly reporting time by 40% by automating the sales pack.", "fact_ids": ["F-1"]},
         "story_ids": ["s1"]},
        {"category": "logistics", "question": "What is your notice period?", "why_asked": "",
         "answer": {"text": "Use the pay and logistics sheet.", "fact_ids": []}, "story_ids": []}]},
    "StoriesReply": {"items": [
        {"id": "s1", "title": "Automating the sales pack", "requirement": "SQL",
         "situation": "Monthly reporting took too long.", "task": "Speed up the sales pack.",
         "action": "Automated the sales pack.", "result": "Cut monthly reporting time by 40%.", "fact_ids": ["F-1"]}]},
    "QuestionsToAsk": {"items": [{"question": "How does the sales team use the reports?", "why": "Shows interest"}]},
    "Gaps": {"items": [{"requirement": "Tableau", "gap": "No Tableau experience",
                        "answer": {"text": "I build reporting with SQL and Python.", "fact_ids": ["F-1"]}}]},
    "ClaimCheckOut": {"flags": []},
    "PracticeFeedback": {"feedback": "Clear and specific.", "strengths": ["Uses a figure"], "improve": [],
                         "suggested_answer": {"text": "I cut monthly reporting time by 40%.", "fact_ids": ["F-1"]}},
}


def responder(**over: Any):
    """A FakeLLMClient default that answers by schema; ``over`` replaces replies (a list is consumed in order)."""
    queues = {k: (list(v) if isinstance(v, list) else v) for k, v in over.items()}

    def reply(call: FakeCall) -> Any:
        name = call.schema.__name__
        got = queues.get(name, GOOD.get(name))
        if isinstance(got, list):
            got = got.pop(0) if len(got) > 1 else got[0]
        if isinstance(got, Exception):
            raise got
        return copy.deepcopy(got)

    return reply


def fake(**over: Any) -> FakeLLMClient:
    return FakeLLMClient(default=responder(**over))


def section_calls(client: FakeLLMClient, schema: str) -> list[FakeCall]:
    return [c for c in client.calls if c.schema.__name__ == schema]


async def versions(session: AsyncSession, pack_id, section: str | None = None) -> list[InterviewSectionVersion]:
    q = select(InterviewSectionVersion).where(InterviewSectionVersion.pack_id == pack_id)
    if section:
        q = q.where(InterviewSectionVersion.section == section)
    return list((await session.scalars(q.order_by(InterviewSectionVersion.section,
                                                  InterviewSectionVersion.version))).all())
