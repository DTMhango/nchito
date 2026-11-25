"""The deterministic guardrail checker (DESIGN.md 5.3). Pure: no database, no clock, no network.

Code-enforced types: ``never_mention``, ``never_together`` (across a SET of texts),
``require_wording``, ``omit_field``, ``format`` (money rule), ``limit`` (paragraph hook; page
counts come from the renderer in ``Document.pages``) and ``attach_policy``. ``reframe`` and
``positioning`` are instructions to the model and are never violations here.

A violation carries the guardrail's strictness: ``always_block`` is a block that cannot be
waived, ``block_waivable_once`` is a block the owner may waive for one application (with a
reason, audited by the caller), ``advise`` is a warning.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.schemas.json_types import (
    AttachPolicy,
    FormatRule,
    GuardrailParams,
    LimitRule,
    NeverMention,
    NeverTogether,
    OmitField,
    RequireWording,
)

Strictness = Literal["always_block", "block_waivable_once", "advise"]
Severity = Literal["block", "warn"]
Status = Literal["block", "warn"]

FILE_NAME_SCOPE = "file_name"


@dataclass(frozen=True)
class Document:
    """One piece of the outgoing packet. ``scope`` is cv, letter, email, form_answers."""

    scope: str
    text: str
    fact_codes: frozenset[str] = frozenset()
    fields: dict[str, str] = field(default_factory=dict)  # structured fields present (omit_field)
    pages: int | None = None


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    params: GuardrailParams
    scope: tuple[str, ...] = ("everywhere",)
    severity: Severity = "block"
    strictness: Strictness = "always_block"
    enabled: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class Violation:
    guardrail_id: str
    name: str
    type: str
    status: Status
    strictness: Strictness
    waivable: bool
    detail: str
    document_scope: str | None = None


@dataclass(frozen=True)
class Attachment:
    document_type: str  # cv, degree, transcript, id, photo, cert, other
    name: str = ""


def never_skill_rules(skill_names: Iterable[str]) -> list[Rule]:
    """Skills the owner never claims are fed to the checker as ``never_mention`` rules."""
    return [
        Rule(id=f"skill:{name}", name=f"Never claim {name}", params=NeverMention(terms=[name]),
             reason="Marked never-claim in the skills list")
        for name in skill_names
    ]


# ----- helpers --------------------------------------------------------------------------


def _term_re(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term.strip())}(?!\w)", re.IGNORECASE)


def _contains(text: str, term: str) -> bool:
    return bool(term.strip()) and _term_re(term).search(text) is not None


def _applies(rule: Rule, scope: str) -> bool:
    return "everywhere" in rule.scope or scope in rule.scope


def _docs_for(rule: Rule, docs: Sequence[Document]) -> list[Document]:
    return [d for d in docs if _applies(rule, d.scope)]


def _status(rule: Rule) -> Status:
    return "warn" if rule.severity == "warn" or rule.strictness == "advise" else "block"


def _violation(rule: Rule, detail: str, scope: str | None = None) -> Violation:
    status = _status(rule)
    return Violation(
        guardrail_id=rule.id, name=rule.name, type=rule.params.type, status=status,
        strictness=rule.strictness, waivable=status == "block" and rule.strictness == "block_waivable_once",
        detail=detail, document_scope=scope,
    )


def _group_hit(group: Sequence[str], docs: Sequence[Document]) -> str | None:
    """The first member of ``group`` found in any document, by text or by fact code."""
    for member in group:
        for d in docs:
            if member in d.fact_codes or _contains(d.text, member):
                return member
    return None


# ----- one checker per type -------------------------------------------------------------


def _never_mention(rule: Rule, p: NeverMention, docs: Sequence[Document]) -> list[Violation]:
    out: list[Violation] = []
    for d in _docs_for(rule, docs):
        for term in p.terms:
            if _contains(d.text, term):
                out.append(_violation(rule, f"mentions '{term}'", d.scope))
        for pattern in p.regex:
            try:
                hit = re.search(pattern, d.text, re.IGNORECASE)
            except re.error:
                out.append(_violation(rule, f"invalid pattern '{pattern}'", d.scope))
                continue
            if hit:
                out.append(_violation(rule, f"matches pattern '{pattern}'", d.scope))
    return out


def _never_together(rule: Rule, p: NeverTogether, docs: Sequence[Document]) -> list[Violation]:
    scoped = _docs_for(rule, docs)
    a, b = _group_hit(p.group_a, scoped), _group_hit(p.group_b, scoped)
    if a is None or b is None:
        return []
    return [_violation(rule, f"'{a}' and '{b}' appear together in the packet")]


def _require_wording(rule: Rule, p: RequireWording, docs: Sequence[Document]) -> list[Violation]:
    out = []
    for d in _docs_for(rule, docs):
        for wrong in p.instead_of:
            if _contains(d.text, wrong):
                out.append(_violation(rule, f"use '{p.use}', not '{wrong}'", d.scope))
    return out


def _omit_field(rule: Rule, p: OmitField, docs: Sequence[Document]) -> list[Violation]:
    out = []
    for d in _docs_for(rule, docs):
        for name in p.fields:
            label = name.replace("_", " ")
            present = bool(d.fields.get(name)) or _contains(d.text, label)
            if present:
                out.append(_violation(rule, f"'{label}' must not appear", d.scope))
    return out


_MONEY = r"(?:{cur}\s?\d[\d,.]*|\d[\d,.]*\s?{cur})"


def _money_usd_first(rule: Rule, p: FormatRule, docs: Sequence[Document]) -> list[Violation]:
    local = str(p.params.get("local_currency", "")).strip()
    if not local:
        return []
    local_re = re.compile(_MONEY.format(cur=re.escape(local)), re.IGNORECASE)
    usd_re = re.compile(r"(?:USD|US\$|\$)\s?\d|\d\s?USD", re.IGNORECASE)
    out = []
    for d in _docs_for(rule, docs):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", d.text):
            m = local_re.search(sentence)
            if not m:
                continue
            u = usd_re.search(sentence)
            if u is None or u.start() > m.start():
                out.append(_violation(rule, f"give the USD figure first: '{sentence.strip()[:80]}'", d.scope))
    return out


_FORMAT_RULES = {"money_usd_first": _money_usd_first}


def _format(rule: Rule, p: FormatRule, docs: Sequence[Document]) -> list[Violation]:
    checker = _FORMAT_RULES.get(p.rule)
    return checker(rule, p, docs) if checker else []  # unknown format rules are model-enforced


def _paragraphs(text: str) -> int:
    return len([b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()])


def _limit(rule: Rule, p: LimitRule, docs: Sequence[Document]) -> list[Violation]:
    out = []
    for d in docs:
        if d.scope != p.document or not _applies(rule, d.scope):
            continue
        if p.paragraphs is not None and _paragraphs(d.text) > p.paragraphs:
            out.append(_violation(rule, f"{_paragraphs(d.text)} paragraphs, limit {p.paragraphs}", d.scope))
        if p.pages is not None and d.pages is not None and d.pages > p.pages:
            out.append(_violation(rule, f"{d.pages} pages, limit {p.pages}", d.scope))
    return out


def _attach_policy(rule: Rule, p: AttachPolicy, attachments: Sequence[Attachment],
                   released: frozenset[str]) -> list[Violation]:
    out = []
    for a in attachments:
        if a.document_type != p.document_type:
            continue
        ok = (p.when == "when_asked" and bool({"asked", "after_offer"} & released)) or (
            p.when == "after_offer" and "after_offer" in released)
        if not ok:
            out.append(_violation(rule, f"'{a.name or a.document_type}' must not be attached ({p.when})"))
    return out


# ----- entry point ----------------------------------------------------------------------


def check(
    rules: Iterable[Rule],
    documents: Sequence[Document],
    *,
    file_names: Sequence[str] = (),
    attachments: Sequence[Attachment] = (),
    released: Iterable[str] = (),
) -> list[Violation]:
    """Run every enabled rule over the whole outgoing packet.

    ``documents`` is the SET of texts (CV, letter, email body, form answers). File names are
    checked as documents with scope ``file_name``, which only ``everywhere`` rules cover.
    ``released`` lists what the packet may carry now: ``asked`` (the posting asked for it) and
    ``after_offer``.
    """
    docs = [*documents, *(Document(scope=FILE_NAME_SCOPE, text=n) for n in file_names)]
    released_set = frozenset(released)
    out: list[Violation] = []
    for rule in rules:
        if not rule.enabled:
            continue
        p = rule.params
        if isinstance(p, NeverMention):
            out += _never_mention(rule, p, docs)
        elif isinstance(p, NeverTogether):
            out += _never_together(rule, p, docs)
        elif isinstance(p, RequireWording):
            out += _require_wording(rule, p, docs)
        elif isinstance(p, OmitField):
            out += _omit_field(rule, p, docs)
        elif isinstance(p, FormatRule):
            out += _format(rule, p, docs)
        elif isinstance(p, LimitRule):
            out += _limit(rule, p, docs)
        elif isinstance(p, AttachPolicy):
            out += _attach_policy(rule, p, attachments, released_set)
    return out


def blocked(violations: Iterable[Violation], *, waived: Iterable[str] = ()) -> bool:
    """True when an unwaived block remains. Only ``block_waivable_once`` can be waived."""
    waived_ids = set(waived)
    return any(
        v.status == "block" and not (v.waivable and v.guardrail_id in waived_ids) for v in violations
    )
