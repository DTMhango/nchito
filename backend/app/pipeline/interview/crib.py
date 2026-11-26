"""The one-page crib sheet, assembled by code from the other sections (no model, nothing new said).

Flagged sections (those that failed the truth checks) contribute nothing but their name in ``flagged``,
so a crib sheet never repeats an unchecked claim.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.pipeline.interview import shapes as sh

POINTS, STORIES, ASKS, GAPS = 5, 4, 3, 3  # one page: layout limits, not business values


def build(current: Mapping[str, sh.Shape], flagged: set[str]) -> sh.CribSheet:
    def ok(key: str) -> sh.Shape | None:
        return None if key in flagged else current.get(key)

    crib = sh.CribSheet(flagged=sorted(k for k in flagged if k in current))
    if isinstance(brief := ok("role_brief"), sh.RoleBrief):
        crib.role = brief.summary.split("\n", 1)[0][:400]
    if isinstance(why := ok("why_you"), sh.WhyYou):
        crib.points = [p.point.text for p in why.points[:POINTS]]
    if isinstance(stories := ok("stories"), sh.Stories):
        chosen = [s for s in stories.items if s.favourite] or stories.items
        crib.stories = [f"{s.title}: {s.result}" for s in chosen[:STORIES]]
    if isinstance(asks := ok("questions_to_ask"), sh.QuestionsToAsk):
        crib.questions_to_ask = [q.question for q in asks.items[:ASKS]]
    if isinstance(pay := ok("pay_sheet"), sh.PaySheet):
        crib.pay = [f"{line.topic}: {line.kit_answer or line.told_them or line.note}" for line in pay.lines]
    if isinstance(gaps := ok("gaps"), sh.Gaps):
        crib.gaps = [f"{g.requirement}: {g.answer.text}" for g in gaps.items[:GAPS]]
    return crib
