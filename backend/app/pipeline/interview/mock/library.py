"""What a finished mock interview feeds: progress ("practise these next"), the story bank, draft facts, export.

- Progress averages each answered question's scores by category over a pack's sessions (optionally one round);
  a category below ``interview.mock.weak_below`` is weak, and the pack's likely questions in weak categories
  that were not practised yet (then the weakest answered ones) are suggested next.
- A strong answer goes into the pack's story bank in the owner's own words, linked to the approved facts it
  rests on, as an owner edit of the ``stories`` section: checked like any edit, so an unsupported figure flags it.
- An unverified statement becomes a draft fact (``needs_review``) only when the owner says so. It is never
  verified by this: approving it is the Kit's review flow.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.settings import service as settings_service
from app.docs.model import DocModel, Entry, Section
from app.kit.service import next_fact_code
from app.models.applications import InterviewMockSession, InterviewMockTurn, InterviewPack, InterviewSectionVersion
from app.models.base import Origin, ReviewState
from app.models.kit import Fact, FactKind, FactStatus
from app.models.search import Job
from app.pipeline.interview import export
from app.pipeline.interview import shapes as sh
from app.pipeline.interview.mock import checks as mock_checks
from app.pipeline.interview.mock.session import OWNER, pack_questions, turns_of
from app.pipeline.interview.service import InterviewError, current_versions, edit, load_kit

DRAFT_NOTE = "From a mock interview answer; not verified."


# ----- progress --------------------------------------------------------------------------------------


async def sessions_for(session: AsyncSession, pack: InterviewPack,
                       round_id: uuid.UUID | None = None) -> list[InterviewMockSession]:
    q = select(InterviewMockSession).where(InterviewMockSession.pack_id == pack.id)
    if round_id is not None:
        q = q.where(InterviewMockSession.round_id == round_id)
    return list((await session.scalars(q.order_by(InterviewMockSession.created_at.desc()))).all())


def _answer_score(item: dict[str, Any]) -> float | None:
    scores = [int(v) for v in (item.get("scores") or {}).values()]
    return sum(scores) / len(scores) if scores else None


async def progress(session: AsyncSession, pack: InterviewPack, round_id: uuid.UUID | None = None) -> dict[str, Any]:
    values = await settings_service.values(session)
    weak_below = int(values["interview.mock.weak_below"])
    rows = [s for s in await sessions_for(session, pack, round_id) if s.status == "done" and s.feedback]
    per_cat: dict[str, list[float]] = {}
    answered: list[tuple[float, str, str]] = []
    practised: set[str] = set()
    for s in rows:
        for item in (s.feedback or {}).get("answers", []):
            score = _answer_score(item)
            cat = item.get("category") or "other"
            practised.add((item.get("question") or "").casefold())
            if score is None:
                continue
            per_cat.setdefault(cat, []).append(score)
            answered.append((score, item.get("question") or "", cat))
    categories = [{"category": c, "answers": len(v), "average": round(sum(v) / len(v), 2),
                   "weak": sum(v) / len(v) < weak_below} for c, v in sorted(per_cat.items())]
    weak = [c["category"] for c in sorted(categories, key=lambda c: c["average"]) if c["weak"]]
    want = int(values["interview.mock.practise_next"])
    nxt: list[dict[str, Any]] = []
    for q in await pack_questions(session, pack):
        if len(nxt) >= want:
            break
        if q.category in weak and q.question.casefold() not in practised:
            nxt.append({"question": q.question, "category": q.category, "reason": "weak category, not practised"})
    for score, question, cat in sorted(answered):
        if len(nxt) >= want:
            break
        if score < weak_below and question and all(n["question"] != question for n in nxt):
            nxt.append({"question": question, "category": cat, "reason": f"scored {score:.1f}"})
    return {"sessions": len(rows), "categories": categories, "weak": weak, "practise_next": nxt}


# ----- story bank ------------------------------------------------------------------------------------


async def _owner_turn(session: AsyncSession, s: InterviewMockSession, turn_id: uuid.UUID) -> InterviewMockTurn:
    turn = await session.get(InterviewMockTurn, turn_id)
    if turn is None or turn.session_id != s.id or turn.role != OWNER or turn.kind != "answer":
        raise InterviewError("no such answer in this session", 404, "not_found")
    return turn


async def save_story(session: AsyncSession, s: InterviewMockSession, turn_id: uuid.UUID, *, title: str | None,
                     fact_ids: Sequence[str] | None, actor: str) -> InterviewSectionVersion:
    """The answer, in the owner's words, as a new story (the action), linked to the approved facts it rests on."""
    turn = await _owner_turn(session, s, turn_id)
    pack = await session.get(InterviewPack, s.pack_id, with_for_update=True)
    assert pack is not None
    kit = await load_kit(session, None)
    codes = mock_checks.usable_codes(fact_ids if fact_ids is not None else turn.fact_ids, kit)
    turns = await turns_of(session, s.id)
    question = next((t.text for t in turns if t.role == "interviewer" and t.question_index == turn.question_index
                     and t.kind == "question"), "")
    if len(turn.text) > 2000:
        raise InterviewError("the answer is longer than a story allows (2000 characters); shorten it first", 422,
                             "too_long")
    current = (await current_versions(session, pack.id)).get("stories")
    stories = sh.Stories.model_validate(current.content) if current is not None else sh.Stories()
    ids = {st.id for st in stories.items}
    n = 1
    while f"m{n}" in ids:
        n += 1
    story = sh.Story(id=f"m{n}", title=(title or question or "Mock interview answer")[:300],
                     requirement=turn.category or "", situation="", task="", action=turn.text, result="",
                     fact_ids=codes)
    row = await edit(session, pack, "stories", sh.Stories(items=[*stories.items, story]).model_dump(mode="json"),
                     actor=actor)
    await audit.record(session, actor=actor, action="interview.mock_story_saved", subject_type="interview_mock_session",
                       subject_id=s.id, detail={"turn_id": str(turn.id), "story_id": story.id, "fact_ids": codes,
                                                "version": row.version})
    return row


# ----- unverified statements -------------------------------------------------------------------------


async def resolve_claim(session: AsyncSession, s: InterviewMockSession, turn_id: uuid.UUID, claim_id: str, *,
                        action: str, text: str | None, actor: str) -> InterviewMockTurn:
    """``add_draft``: a draft fact awaiting review (the owner may correct the wording first). ``dismiss``: noted."""
    turn = await _owner_turn(session, s, turn_id)
    claims = [dict(c) for c in turn.claims]
    claim = next((c for c in claims if c["id"] == claim_id), None)
    if claim is None:
        raise InterviewError("no such statement", 404, "not_found")
    if claim["status"] != "unverified":
        return turn
    if action == "add_draft":
        wording = (text or claim["text"]).strip()
        if not wording:
            raise InterviewError("the fact needs some text", 422, "empty")
        fact = Fact(code=await next_fact_code(session), kind=FactKind.achievement, text=wording,
                    status=FactStatus.draft, review_state=ReviewState.needs_review, origin=Origin.owner,
                    confidence_note=DRAFT_NOTE)
        session.add(fact)
        await session.flush()
        claim.update(status="added", fact_code=fact.code)
        await audit.record(session, actor=actor, action="kit.fact.created", subject_type="fact", subject_id=fact.id,
                           detail={"code": fact.code, "from": "mock_interview", "session_id": str(s.id)})
    else:
        claim["status"] = "dismissed"
    turn.claims = claims
    await session.flush()
    return turn


# ----- export ----------------------------------------------------------------------------------------


def _cites(ids: Sequence[str]) -> str:
    return f" [{', '.join(ids)}]" if ids else ""


def document(job: Job, s: InterviewMockSession, turns: Sequence[InterviewMockTurn]) -> DocModel:
    chat = Section(key="transcript", title="Transcript")
    for t in turns:
        if t.role == "interviewer":
            chat.paragraphs.append(f"Interviewer: {t.text}")
        elif t.role == OWNER:
            chat.paragraphs.append(f"You [{mock_checks.answer_code(t.seq)}]: "
                                   f"{t.text if t.kind == 'answer' else '(skipped)'}")
    sections = [chat]
    fb = s.feedback or {}
    if fb:
        summary = Section(key="feedback", title="Feedback", paragraphs=[p for p in [fb.get("summary", "")] if p])
        summary.bullets = [f"{k}: {v}" for k, v in (fb.get("overall") or {}).items()]
        for a in fb.get("answers", []):
            bullets = [*(f"Strong: {x}" for x in a.get("strong", [])), *(f"Tighten: {x}" for x in a.get("tighten", [])),
                       *(f"Suggested: {c['text']}{_cites(c['fact_ids'])}" for c in a.get("suggested", [])),
                       *(f"Removed (failed the truth checks): {c['text'] or '(withheld)'} - {'; '.join(c['reasons'])}"
                         for c in a.get("removed", []))]
            summary.entries.append(Entry(title=a.get("question") or f"Question {a['question_index'] + 1}",
                                         subtitle=a.get("structure") or None, bullets=bullets))
        sections.append(summary)
    return DocModel(kind="pack", name=f"Mock interview: {job.title}", headline=job.employer, sections=sections)


async def export_session(session: AsyncSession, s: InterviewMockSession, fmt: export.ExportFmt) -> bytes:
    pack = await session.get(InterviewPack, s.pack_id)
    assert pack is not None
    job = await session.get(Job, pack.job_id)
    assert job is not None
    return export.render(document(job, s, await turns_of(session, s.id)), fmt)
