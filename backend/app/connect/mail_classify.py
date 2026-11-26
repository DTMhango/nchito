"""Classify an inbound reply: deterministic rules first, a budgeted model only when they cannot tell.

Mail content is untrusted data. The rules only *read* it (regular expressions); the model sees it
only inside a ``DataBlock`` (``app.llm.untrusted.data_block``) and can answer only with one value from
a closed list, so nothing in an email can instruct the system. A classification never sends, applies or
approves anything by itself: ``mail_sync`` turns it into a pending action or, if the owner allowed that
kind in settings, a stage change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect.mailbox import MailMessage
from app.core.settings.registry import REGISTRY
from app.llm.client import BudgetExceeded, LLMClient, LLMError, Message, TextPart
from app.llm.prompts import active_prompt
from app.llm.untrusted import data_block

Category = Literal["confirmation", "rejection", "interview", "information_request", "other"]
CATEGORIES: tuple[str, ...] = ("confirmation", "rejection", "interview", "information_request", "other")
RULE_TEXT_LIMIT = 20_000  # technical bound on regex work, not a business value


def _rx(patterns: Sequence[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


@dataclass(frozen=True)
class Phrases:
    """The wording the rules look for: settings ``mail.*_phrases`` and ``mail.bounce_senders``."""

    rejection: re.Pattern[str]
    interview: re.Pattern[str]
    info_request: re.Pattern[str]
    confirmation: re.Pattern[str]
    auto_reply: re.Pattern[str]
    bounce_subject: re.Pattern[str]
    bounce_senders: tuple[str, ...]


PHRASE_KEYS = ("mail.rejection_phrases", "mail.interview_phrases", "mail.info_request_phrases",
               "mail.confirmation_phrases", "mail.auto_reply_phrases", "mail.bounce_subject_phrases")


def phrases_from(values: Mapping[str, Any]) -> Phrases:
    rx = [_rx(list(values[key])) for key in PHRASE_KEYS]
    return Phrases(*rx, bounce_senders=tuple(str(v).lower() for v in values["mail.bounce_senders"]))


@lru_cache(maxsize=1)
def default_phrases() -> Phrases:
    return phrases_from({key: REGISTRY[key].default for key in (*PHRASE_KEYS, "mail.bounce_senders")})


QUOTED_LINE = re.compile(r"^\s*>.*$", re.M)


@dataclass(frozen=True)
class Classification:
    category: Category
    source: Literal["rules", "llm", "none"]
    reason: str
    bounce: bool = False
    needs_review: bool = False  # the system could not decide, or the model was unavailable


def _text_of(msg: MailMessage) -> str:
    body = QUOTED_LINE.sub("", msg.body_text or "")
    return f"{msg.subject}\n{body}"[:RULE_TEXT_LIMIT]


def is_bounce(msg: MailMessage, phrases: Phrases | None = None) -> bool:
    p = phrases or default_phrases()
    local = msg.sender.split("@", 1)[0].lower()
    return local.startswith(p.bounce_senders) or bool(p.bounce_subject.search(msg.subject or ""))


def classify_rules(msg: MailMessage, phrases: Phrases | None = None) -> Classification | None:
    """A decided classification; ``source == "none"`` when the wording conflicts; ``None`` when nothing matched."""
    p = phrases or default_phrases()
    if is_bounce(msg, p):
        return Classification("other", "rules", "delivery failure notice", bounce=True)
    text = _text_of(msg)
    if p.auto_reply.search(text) or "auto-replied" in msg.headers.get("auto-submitted", "").lower():
        return Classification("other", "rules", "automatic reply")
    hits = {name for name, rx in (("rejection", p.rejection), ("interview", p.interview),
                                  ("information_request", p.info_request), ("confirmation", p.confirmation))
            if rx.search(text)}
    if not hits:
        return None
    if hits == {"confirmation"}:
        return Classification("confirmation", "rules", "acknowledgement wording")
    if "rejection" in hits:
        if hits <= {"rejection", "confirmation"}:
            return Classification("rejection", "rules", "rejection wording")
        # rejection mixed with an invitation or a request: a model or the owner decides
        return Classification("other", "none", "conflicting wording", needs_review=True)
    if "interview" in hits:
        return Classification("interview", "rules", "interview invitation wording")
    return Classification("information_request", "rules", "request for information wording")


class MailClassifyOut(BaseModel):
    category: Category
    employer: str | None = None
    role: str | None = None


INSTRUCTIONS = (
    "Choose exactly one category for this email: confirmation (the employer acknowledges receiving the "
    "application), rejection, interview (an invitation to interview or to book a call), information_request "
    "(the employer asks the candidate to send or confirm something), or other (anything else, including "
    "offers, newsletters and recruiter outreach). Reply in the JSON format requested.")


async def classify_with_model(session: AsyncSession, llm: LLMClient, msg: MailMessage, *,
                              max_chars: int) -> Classification:
    prompt = await active_prompt(session, "classify_email")
    system = (prompt.text if prompt else "") + "\n\n" + INSTRUCTIONS
    text = f"From: {msg.sender}\nSubject: {msg.subject}\n\n{msg.body_text}"[:max_chars]
    messages = [Message("system", [TextPart(system)]),
                Message("user", [TextPart("Classify this email."), data_block(text, "email")])]
    try:
        ceiling = await llm.estimate_cost_micros("classify_email", messages, schema=MailClassifyOut)
        out, _ = await llm.complete("classify_email", messages, MailClassifyOut, max_cost_micros=ceiling)
    except BudgetExceeded:
        return Classification("other", "none", "model unavailable: AI budget", needs_review=True)
    except LLMError:
        return Classification("other", "none", "model unavailable", needs_review=True)
    except Exception:  # a schema or provider failure must not stop the mailbox check
        return Classification("other", "none", "model reply unusable", needs_review=True)
    return Classification(out.category, "llm", "model classification")


async def classify(session: AsyncSession, llm: LLMClient | None, msg: MailMessage, *, use_llm: bool,
                   max_chars: int, phrases: Phrases | None = None) -> Classification:
    decided = classify_rules(msg, phrases)
    if decided is not None and decided.source == "rules":
        return decided
    if use_llm and llm is not None:
        return await classify_with_model(session, llm, msg, max_chars=max_chars)
    return decided or Classification("other", "none", "no rule matched")
