"""What the model returns in a mock interview, and the checked feedback code stores.

Every sentence of a suggested answer is a :class:`~app.pipeline.interview.shapes.Claim` citing Kit fact codes
(``F-12``) or the owner's own answers in this session (``A3``: the answer turn with ``seq`` 3). Code checks each
one; one that fails is removed from the suggestion and kept only as a flagged item.
"""

from __future__ import annotations

from pydantic import Field

from app.pipeline.interview.shapes import Claim, QuestionCategory, Shape


class DimScore(Shape):
    dimension: str = Field(max_length=30, description="A rubric key")
    score: int = Field(description="From 1 to the top score")


class AnswerFeedback(Shape):
    structure: str = Field(default="", max_length=1500, description="Situation, task, action, result: what is there")
    relevance: str = Field(default="", max_length=1500, description="How well it answers the posting's needs")
    specificity: str = Field(default="", max_length=1500, description="Concrete actions, figures, results")
    strong: list[str] = Field(default_factory=list, description="What was strong")
    tighten: list[str] = Field(default_factory=list, description="What to tighten")
    scores: list[DimScore] = Field(default_factory=list)
    suggested: list[Claim] = Field(default_factory=list,
                                   description="A stronger answer, one sentence per item, each citing fact codes "
                                               "or answer refs such as A3")


class AnswerAnalysis(Shape):
    fact_ids: list[str] = Field(default_factory=list, description="Codes of approved facts the answer rests on")
    unstated: list[str] = Field(default_factory=list,
                                description="Statements of fact in the answer that no approved fact contains, "
                                            "quoted briefly")


class MockAsk(Shape):
    question: str = Field(max_length=1500)
    category: QuestionCategory


class MockReply(Shape):
    probe: str | None = Field(default=None, max_length=1000, description="A short follow-up probe, or null")
    next_question: str | None = Field(default=None, max_length=1500)
    next_category: QuestionCategory | None = None
    analysis: AnswerAnalysis = Field(default_factory=AnswerAnalysis)
    feedback: AnswerFeedback | None = None


class IndexedFeedback(Shape):
    question_index: int
    feedback: AnswerFeedback


class MockFinal(Shape):
    summary: str = Field(default="", max_length=4000)
    answers: list[IndexedFeedback] = Field(default_factory=list)
    overall: list[DimScore] = Field(default_factory=list)
