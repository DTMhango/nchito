"""Classify an inbound reply: deterministic rules first, a budgeted model only when they cannot tell.

Mail content is untrusted data. The rules only *read* it (regular expressions); the model sees it
only inside a ``DataBlock`` (``app.llm.untrusted.data_block``) and can answer only with one value from
a closed list, so nothing in an email can instruct the system. A classification never sends, applies or
approves anything by itself: ``mail_sync`` turns it into a pending action or, if the owner allowed that
kind in settings, a stage change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect.mailbox import MailMessage
from app.llm.client import BudgetExceeded, LLMClient, LLMError, Message, TextPart
from app.llm.prompts import active_prompt
from app.llm.untrusted import data_block

Category = Literal["confirmation", "rejection", "interview", "information_request", "other"]
CATEGORIES: tuple[str, ...] = ("confirmation", "rejection", "interview", "information_request", "other")
RULE_TEXT_LIMIT = 20_000  # technical bound on regex work, not a business value


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


REJECTION = _rx(
    r"\bunfortunately\b", r"regret to (inform|tell|let)", r"not (been )?(selected|successful|shortlisted)",
    r"(will|would) not be (moving|proceeding|progressing) (forward|further|with)",
    r"decided to (move|go|proceed) (forward )?with (other|another|different)", r"pursue (other|another) candidate",
    r"position (has been|is now) filled", r"your application was unsuccessful",
    r"not (be )?(taking|moving) .{0,30}forward")
INTERVIEW = _rx(
    r"invit\w+ you to (an? |a )?(\w+ )?interview", r"interview (invitation|invite|request)",
    r"(schedule|arrange|set up|book) (an? |your |a )?(\w+ )?(interview|call|phone screen|chat|meeting)",
    r"(would|like) to (speak|talk|meet) with you", r"calendly\.com", r"your availability (for|this|next)",
    r"available for (an? )?(interview|call|chat)")
INFO_REQUEST = _rx(
    r"(please|kindly) (provide|send|share|submit|upload|attach|supply)\b",
    r"could you (please )?(provide|send|share|submit)",
    r"we (still )?need (some |the |your )?(additional |further |more )?(information|documents|details|certificates)",
    r"(additional|further|missing) (information|documents|details) (is|are)? ?(required|needed)")
CONFIRMATION = _rx(
    r"(thank you|thanks) for (applying|your application|your interest|submitting)",
    r"we (have |'ve )?(successfully )?received your (application|cv|resume)",
    r"your application (has been |was )?(successfully )?(received|submitted|sent)",
    r"application (received|confirmation)",
    r"successfully (applied|submitted)")
AUTO_REPLY = _rx(r"out of (the )?office", r"automatic reply", r"auto-?reply", r"away from (my|the) (desk|office)")
BOUNCE_SUBJECT = _rx(r"delivery status notification", r"undeliverable", r"delivery (has )?failed",
                     r"mail delivery (failed|subsystem)", r"returned mail", r"could not be delivered")
BOUNCE_SENDERS = ("mailer-daemon", "postmaster")
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


def is_bounce(msg: MailMessage) -> bool:
    local = msg.sender.split("@", 1)[0]
    return local.startswith(BOUNCE_SENDERS) or bool(BOUNCE_SUBJECT.search(msg.subject or ""))


def classify_rules(msg: MailMessage) -> Classification | None:
    """A decided classification; ``source == "none"`` when the wording conflicts; ``None`` when nothing matched."""
    if is_bounce(msg):
        return Classification("other", "rules", "delivery failure notice", bounce=True)
    text = _text_of(msg)
    if AUTO_REPLY.search(text) or "auto-replied" in msg.headers.get("auto-submitted", "").lower():
        return Classification("other", "rules", "automatic reply")
    hits = {name for name, rx in (("rejection", REJECTION), ("interview", INTERVIEW),
                                  ("information_request", INFO_REQUEST), ("confirmation", CONFIRMATION))
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
                   max_chars: int) -> Classification:
    decided = classify_rules(msg)
    if decided is not None and decided.source == "rules":
        return decided
    if use_llm and llm is not None:
        return await classify_with_model(session, llm, msg, max_chars=max_chars)
    return decided or Classification("other", "none", "no rule matched")
