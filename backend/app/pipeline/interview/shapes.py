"""Section shapes of the interview pack (DESIGN.md 10.3a). Each is stored as a versioned JSON artefact.

Every sentence that says something about the owner is a :class:`Claim` and carries the Kit fact codes it
rests on, so it goes through the same fact tracing and claim-drift checks as a CV bullet. Text taken from
the posting (the role brief, the questions an employer may ask, the questions to ask them) is not a claim
about the owner; it is still checked against the guardrails and keep-out facts.

The ``*Reply`` models are what the model returns; code adds the fields it owns (research note, favourites).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionCategory = Literal["behavioural", "technical", "role", "motivation", "logistics"]
QUESTION_CATEGORIES: tuple[str, ...] = ("behavioural", "technical", "role", "motivation", "logistics")
LLM_SECTIONS: tuple[str, ...] = ("role_brief", "why_you", "questions", "stories", "questions_to_ask", "gaps")
CODE_SECTIONS: tuple[str, ...] = ("pay_sheet", "crib_sheet")


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(Shape):
    text: str = Field(max_length=2000)
    fact_ids: list[str] = Field(default_factory=list, description="Codes of the approved facts it rests on")


class RoleBrief(Shape):
    summary: str = Field(default="", max_length=3000, description="What the job is, in plain words")
    emphasised: list[str] = Field(default_factory=list, description="What the posting stresses most")
    requirements: list[str] = Field(default_factory=list, description="What the posting actually asks for")
    level_notes: str = Field(default="", max_length=2000, description="What to expect at this level")
    company_notes: list[str] = Field(default_factory=list,
                                     description="Only what the posting or the owner's notes say about the employer")
    research_note: str = ""
    posting_changed: bool = False


class TalkingPoint(Shape):
    requirement: str = ""
    point: Claim


class WhyYou(Shape):
    points: list[TalkingPoint] = Field(default_factory=list)


class LikelyQuestion(Shape):
    category: QuestionCategory
    question: str = Field(max_length=1000)
    why_asked: str = Field(default="", max_length=1000)
    answer: Claim = Field(description="A suggested answer built only from approved facts")
    story_ids: list[str] = Field(default_factory=list)


class Questions(Shape):
    items: list[LikelyQuestion] = Field(default_factory=list)


class Story(Shape):
    id: str = Field(max_length=40, description="Short id such as s1")
    title: str = Field(max_length=300)
    requirement: str = ""
    situation: str = Field(max_length=2000)
    task: str = Field(max_length=2000)
    action: str = Field(max_length=2000)
    result: str = Field(max_length=2000)
    fact_ids: list[str] = Field(default_factory=list)
    favourite: bool = False


class Stories(Shape):
    items: list[Story] = Field(default_factory=list)


class AskThem(Shape):
    question: str = Field(max_length=1000)
    why: str = Field(default="", max_length=1000)


class QuestionsToAsk(Shape):
    items: list[AskThem] = Field(default_factory=list)


class Gap(Shape):
    requirement: str
    gap: str = Field(max_length=1000)
    answer: Claim = Field(description="How to address it honestly, from approved facts")


class Gaps(Shape):
    items: list[Gap] = Field(default_factory=list)


PayStatus = Literal["confirmed", "told_them", "not_disclosed", "decide"]


class PayLine(Shape):
    topic: str
    question: str
    status: PayStatus
    kit_answer: str | None = Field(default=None, description="Your confirmed answer; never a guess")
    told_them: str | None = Field(default=None, description="What the form you sent said")
    note: str = ""


class PaySheet(Shape):
    lines: list[PayLine] = Field(default_factory=list)
    posting_pay: str | None = Field(default=None, description="Pay as the posting states it; null if not stated")


class CribSheet(Shape):
    role: str = ""
    points: list[str] = Field(default_factory=list)
    stories: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    pay: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    flagged: list[str] = Field(default_factory=list, description="Sections that failed the truth checks")


SHAPES: dict[str, type[Shape]] = {
    "role_brief": RoleBrief, "why_you": WhyYou, "questions": Questions, "stories": Stories,
    "questions_to_ask": QuestionsToAsk, "gaps": Gaps, "pay_sheet": PaySheet, "crib_sheet": CribSheet,
}

TITLES: dict[str, str] = {
    "role_brief": "Role brief", "why_you": "Why you", "questions": "Likely questions", "stories": "Story bank",
    "questions_to_ask": "Questions to ask them", "gaps": "Gaps and how to address them",
    "pay_sheet": "Pay and logistics", "crib_sheet": "Crib sheet",
}


class RoleBriefReply(Shape):
    summary: str = Field(default="", max_length=3000)
    emphasised: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    level_notes: str = Field(default="", max_length=2000)
    company_notes: list[str] = Field(default_factory=list)


class StoryReply(Shape):
    id: str = Field(max_length=40)
    title: str = Field(max_length=300)
    requirement: str = ""
    situation: str = Field(max_length=2000)
    task: str = Field(max_length=2000)
    action: str = Field(max_length=2000)
    result: str = Field(max_length=2000)
    fact_ids: list[str] = Field(default_factory=list)


class StoriesReply(Shape):
    items: list[StoryReply] = Field(default_factory=list)


REPLIES: dict[str, type[Shape]] = {
    "role_brief": RoleBriefReply, "why_you": WhyYou, "questions": Questions, "stories": StoriesReply,
    "questions_to_ask": QuestionsToAsk, "gaps": Gaps,
}


class PracticeFeedback(Shape):
    feedback: str = Field(max_length=4000, description="Plain feedback on the draft answer")
    strengths: list[str] = Field(default_factory=list)
    improve: list[str] = Field(default_factory=list)
    suggested_answer: Claim | None = Field(default=None, description="A better answer from approved facts only")


def validate(section: str, content: object) -> Shape:
    """The section's shape, validated (raises ``pydantic.ValidationError``)."""
    return SHAPES[section].model_validate(content)
