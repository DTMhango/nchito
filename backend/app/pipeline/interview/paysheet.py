"""The pay and logistics sheet: code only, no model (DESIGN.md 5.4, 10.3a). Unknown is not yes.

Each topic (setting ``interview.pay_topics``) is matched against the answer bank with the same matcher the
application forms use, so scope, conditions, review dates and class are honoured. Only a confirmed,
usable answer fills ``kit_answer``. What the submitted form said fills ``told_them``. Anything else is
``decide`` with the owner's wording: never a guessed or estimated number. Posting pay is shown only when
the posting states it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from app.kit.answers import AnswerRecord, match, similarity
from app.models.search import Job, PayState
from app.pipeline.interview.shapes import PayLine, PaySheet
from app.schemas.json_types import PacketAnswer


def topics(lines: Sequence[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in lines:
        topic, _, question = line.partition("|")
        out.append((topic.strip(), question.strip()))
    return out


def _money(minor: int, currency: str | None) -> str:
    major, cents = divmod(minor, 100)
    return f"{currency + ' ' if currency else ''}{major:,}" + (f".{cents:02d}" if cents else "")


def posting_pay(job: Job) -> str | None:
    if job.pay_state != PayState.stated or (job.pay_min_minor is None and job.pay_max_minor is None):
        return None
    lo, hi = job.pay_min_minor, job.pay_max_minor
    band = (_money(lo, job.pay_currency) if hi is None or lo == hi else
            _money(hi, job.pay_currency) if lo is None else
            f"{_money(lo, job.pay_currency)} to {_money(hi, None)}")
    return f"{band}{f' per {job.pay_period}' if job.pay_period else ''}"


def _told(question: str, given: Sequence[PacketAnswer], threshold: float) -> str | None:
    scored = sorted(((similarity(question, a.question), a) for a in given), key=lambda t: -t[0])
    return scored[0][1].value if scored and scored[0][0] >= threshold else None


def build(job: Job, answers: Sequence[AnswerRecord], given: Sequence[PacketAnswer], *, topic_lines: Sequence[str],
          threshold: float, context: Mapping[str, str], today: date, decide: str) -> PaySheet:
    lines: list[PayLine] = []
    for topic, question in topics(topic_lines):
        told = _told(question, given, threshold)
        r = match(question, answers, threshold=threshold, context=context, today=today)
        if r.outcome == "value" and r.value:
            lines.append(PayLine(topic=topic, question=question, status="confirmed", kit_answer=r.value,
                                 told_them=told, note="" if told in (None, r.value) else
                                 "Your form answer differs from your confirmed answer: be ready to explain."))
        elif r.outcome == "do_not_answer":
            lines.append(PayLine(topic=topic, question=question, status="not_disclosed", told_them=told,
                                 note="You chose not to answer this."))
        elif told is not None:
            lines.append(PayLine(topic=topic, question=question, status="told_them", told_them=told,
                                 note=f"{decide}: no confirmed answer in your Kit ({r.reason})."))
        else:
            lines.append(PayLine(topic=topic, question=question, status="decide", note=f"{decide} ({r.reason})."))
    return PaySheet(lines=lines, posting_pay=posting_pay(job))
