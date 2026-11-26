"""Compare roles side by side (DESIGN.md 18.4): two to four jobs, from a conflict group or any selection.

Reads only: no model call, no pipeline state changes. Rules:

- **Unknown stays unknown.** A fact a posting does not state is a ``not_stated`` cell, never a guess; a row that
  cannot rank every role says so (``comparable`` false, with the reason) and names no best role.
- **Pay is normalised only where that is sound**: year, month and week amounts become per-year amounts in one
  currency; hourly and daily rates (hours and days per year are unknown) and mixed currencies (no exchange rate is
  applied) are shown as stated and marked not comparable. An estimate is marked as one.
- **Scores are compared only under one rubric.** Per-criterion rows always show each rating; the overall score row
  is marked not comparable when the roles were scored under different rubric versions.
- The winner is the role the conflict group already chose (7.1), with its recorded reason; nothing here chooses.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apply import target as apply_target
from app.models.search import Assessment, AssessmentState, Campaign, Job

MIN_JOBS, MAX_JOBS = 2, 4
ANNUALISE = {"year": 1, "month": 12, "week": 52}  # day and hour are not convertible: hours per year are unknown
FACET_ROWS = ("work_model", "remote_scope", "where_must_live", "work_rights", "visa_sponsorship",
              "relocation_required", "relocation_assistance", "needs_account", "employment_type",
              "hiring_arrangement", "timezone_overlap")

CellState = Literal["stated", "not_stated", "unknown", "yes", "no", "estimated", "pass", "fail"]
Group = Literal["facets", "pay", "score", "gates", "employer", "timing", "apply"]


class CompareError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.message, self.status = message, status


class CompareJob(BaseModel):
    id: uuid.UUID
    title: str
    employer: str
    location: str | None = None
    availability: str
    campaign_id: uuid.UUID | None = Field(default=None, description="The campaign whose assessment is shown")
    campaign_name: str | None = None
    score: int | None = None
    assessment_state: str | None = None


class CompareCell(BaseModel):
    value: str | int | None = None
    state: CellState
    note: str | None = None
    amount_minor: int | None = Field(default=None, description="Pay: the per-year midpoint, when normalised")
    currency: str | None = None


class CompareRow(BaseModel):
    key: str
    label: str
    group: Group
    cells: list[CompareCell] = Field(description="One per job, in the order of ``job_ids``")
    comparable: bool = Field(description="False when the roles cannot be ranked on this row; ``note`` says why")
    note: str | None = None
    best_index: int | None = Field(default=None, description="Index of the best role on this row, when comparable")


class CompareOut(BaseModel):
    job_ids: list[uuid.UUID]
    jobs: list[CompareJob]
    rows: list[CompareRow]
    winner_id: uuid.UUID | None = Field(description="The conflict group's winner when the roles share an employer")
    winner_reason: str | None = None


def parse_ids(raw: str) -> list[uuid.UUID]:
    try:
        ids = [uuid.UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise CompareError("job ids must be comma-separated UUIDs") from exc
    if len(set(ids)) != len(ids):
        raise CompareError("the same role cannot be compared with itself")
    if not MIN_JOBS <= len(ids) <= MAX_JOBS:
        raise CompareError(f"compare {MIN_JOBS} to {MAX_JOBS} roles, not {len(ids)}")
    return ids


# ----- cells ------------------------------------------------------------------------------------


def _facet_cell(job: Job, name: str) -> CompareCell:
    facet = getattr(job.facets, name, None)
    value = getattr(facet, "value", None)
    if value is None or value == "not_stated" or (hasattr(value, "kind") and value.kind == "not_stated"):
        return CompareCell(value=None, state="not_stated")
    note = getattr(facet, "evidence", None)
    if hasattr(value, "model_dump"):
        data = value.model_dump(mode="json")
        text = ", ".join(data.get("places") or []) or str(data.get("kind") or data.get("zone") or data)
        if name == "timezone_overlap":
            text = f"{data.get('hours')} h with {data.get('zone')}"
    else:
        text = str(value).replace("_", " ")
    return CompareCell(value=text, state=value if value in ("yes", "no") else "stated", note=note)


def _money(minor: int, currency: str) -> str:
    return f"{minor / 100:,.0f} {currency}"


def _pay_cell(job: Job) -> CompareCell:
    state = getattr(job.pay_state, "value", job.pay_state)
    if state == "not_stated" or (job.pay_min_minor is None and job.pay_max_minor is None):
        return CompareCell(value=None, state="not_stated", note="the posting does not state pay")
    low = job.pay_min_minor if job.pay_min_minor is not None else job.pay_max_minor
    high = job.pay_max_minor if job.pay_max_minor is not None else low
    assert low is not None and high is not None
    currency = job.pay_currency or "?"
    period = job.pay_period or "year"
    shown = f"{_money(low, currency)}" if low == high else f"{_money(low, currency)} to {_money(high, currency)}"
    factor = ANNUALISE.get(period)
    cell_state: CellState = "estimated" if state == "estimated" else "stated"
    if factor is None or job.pay_currency is None:
        why = "no currency stated" if job.pay_currency is None else f"per {period}: hours per year are not known"
        return CompareCell(value=f"{shown} per {period}", state=cell_state, currency=job.pay_currency,
                           note=f"not normalised ({why})")
    annual = (low + high) // 2 * factor
    return CompareCell(value=f"{shown} per {period}", state=cell_state, amount_minor=annual,
                       currency=job.pay_currency, note="estimate, not stated in the posting" if state == "estimated"
                       else (f"about {_money(annual, currency)} per year" if factor != 1 else None))


def _pay_row(jobs: list[Job]) -> CompareRow:
    cells = [_pay_cell(j) for j in jobs]
    missing = [j.title for j, c in zip(jobs, cells, strict=True) if c.state == "not_stated"]
    unconverted = [j.title for j, c in zip(jobs, cells, strict=True) if c.state != "not_stated"
                   and c.amount_minor is None]
    currencies = {c.currency for c in cells if c.amount_minor is not None}
    note = None
    if missing:
        note = f"pay is not stated for {', '.join(missing)}: the roles cannot be ranked on pay"
    elif unconverted:
        note = f"pay for {', '.join(unconverted)} is hourly, daily or has no currency: not normalised"
    elif len(currencies) > 1:
        note = f"different currencies ({', '.join(sorted(str(c) for c in currencies))}); no exchange rate is applied"
    comparable = note is None
    best = None
    if comparable:
        best = max(range(len(cells)), key=lambda i: cells[i].amount_minor or 0)
        if sum(1 for c in cells if c.amount_minor == cells[best].amount_minor) > 1:
            best = None
    return CompareRow(key="pay", label="Pay (per year)", group="pay", cells=cells, comparable=comparable, note=note,
                      best_index=best)


# ----- assessments ------------------------------------------------------------------------------


async def _assessments(session: AsyncSession, job_ids: list[uuid.UUID], campaign_id: uuid.UUID | None
                       ) -> dict[uuid.UUID, Assessment]:
    stmt = select(Assessment).where(Assessment.job_id.in_(job_ids))
    if campaign_id is not None:
        stmt = stmt.where(Assessment.campaign_id == campaign_id)
    chosen: dict[uuid.UUID, Assessment] = {}
    for a in (await session.scalars(stmt)).all():
        current = chosen.get(a.job_id)
        rank = (a.state == AssessmentState.scored, a.score if a.score is not None else -1)
        if current is None or rank > (current.state == AssessmentState.scored,
                                       current.score if current.score is not None else -1):
            chosen[a.job_id] = a
    return chosen


def _score_rows(jobs: list[Job], by_job: dict[uuid.UUID, Assessment]) -> list[CompareRow]:
    present = [by_job.get(j.id) for j in jobs]
    rubrics = {(a.rubric_id, a.rubric_version) for a in present if a is not None and a.rubric_id}
    same_rubric = len(rubrics) <= 1
    rubric_note = None if same_rubric else "scored under different rubric versions: scores are not comparable"
    rows: list[CompareRow] = []
    cells = []
    for a in present:
        if a is None:
            cells.append(CompareCell(value=None, state="unknown", note="not assessed by any campaign"))
        elif a.state != AssessmentState.scored or a.score is None:
            cells.append(CompareCell(value=None, state="unknown", note=f"assessment is {a.state.value}"))
        else:
            cells.append(CompareCell(value=a.score, state="stated",
                                     note="overridden by the owner" if a.override else None))
    known = [c for c in cells if c.value is not None]
    comparable = same_rubric and len(known) == len(cells)
    best = None
    if comparable:
        top = max(int(c.value or 0) for c in cells)
        winners = [i for i, c in enumerate(cells) if c.value == top]
        best = winners[0] if len(winners) == 1 else None
    rows.append(CompareRow(key="score", label="Score", group="score", cells=cells, comparable=comparable,
                           note=rubric_note or (None if comparable else "not every role has a score"),
                           best_index=best))
    names: list[str] = []
    for a in present:
        for r in (a.ratings if a else []):
            if r.criterion not in names:
                names.append(r.criterion)
    for name in names:
        crow = []
        for a in present:
            rating = next((r for r in (a.ratings if a else []) if r.criterion == name), None)
            crow.append(CompareCell(value=None, state="not_stated", note="not rated") if rating is None
                        else CompareCell(value=rating.rating, state="stated", note=rating.note))
        every = all(c.value is not None for c in crow)
        top_i = max(range(len(crow)), key=lambda i: crow[i].value if isinstance(crow[i].value, int) else -1)
        tied = sum(1 for c in crow if c.value == crow[top_i].value) > 1
        rows.append(CompareRow(key=f"criterion:{name}", label=name, group="score", cells=crow,
                               comparable=every and same_rubric,
                               note=rubric_note if not same_rubric else (None if every else "not rated for every role"),
                               best_index=top_i if every and same_rubric and not tied else None))
    gate_names: list[str] = []
    for a in present:
        for f in (a.filter_results if a else []):
            if f.name not in gate_names:
                gate_names.append(f.name)
    for name in gate_names:
        grow = []
        for a in present:
            result = next((f for f in (a.filter_results if a else []) if f.name == name), None)
            grow.append(CompareCell(value=None, state="unknown", note="not evaluated") if result is None
                        else CompareCell(value=result.reason, state=result.result))
        rows.append(CompareRow(key=f"gate:{name}", label=name, group="gates", cells=grow, comparable=True))
    gaps = [CompareCell(value="; ".join(a.gaps) if a and a.gaps else None,
                        state="stated" if a and a.gaps else ("not_stated" if a else "unknown")) for a in present]
    rows.append(CompareRow(key="gaps", label="Gaps", group="score", cells=gaps, comparable=False,
                           note="gaps are listed, not ranked"))
    return rows


# ----- the comparison ---------------------------------------------------------------------------


def _deadline_cell(job: Job) -> CompareCell:
    if job.deadline is not None:
        return CompareCell(value=job.deadline.isoformat(), state="stated")
    if getattr(job.deadline_state, "value", job.deadline_state) == "open_until_filled":
        return CompareCell(value="open until filled", state="stated")
    return CompareCell(value=None, state="not_stated")


async def _channel_cell(session: AsyncSession, job: Job) -> CompareCell:
    for candidate in await apply_target.candidates(session, job):
        if candidate.available:
            return CompareCell(value=candidate.channel, state="stated", note=candidate.reason)
    return CompareCell(value=None, state="unknown", note="no way to apply is available yet")


def _location(job: Job) -> str | None:
    loc = job.location
    return ", ".join(p for p in (loc.city, loc.region, loc.country) if p) or loc.raw


async def build(session: AsyncSession, job_ids: list[uuid.UUID], *, campaign_id: uuid.UUID | None = None
                ) -> CompareOut:
    if not MIN_JOBS <= len(job_ids) <= MAX_JOBS or len(set(job_ids)) != len(job_ids):
        raise CompareError(f"compare {MIN_JOBS} to {MAX_JOBS} different roles")
    found = {j.id: j for j in (await session.scalars(select(Job).where(Job.id.in_(job_ids)))).all()}
    missing = [str(i) for i in job_ids if i not in found]
    if missing:
        raise CompareError(f"no such role: {', '.join(missing)}", 404)
    jobs = [found[i] for i in job_ids]
    by_job = await _assessments(session, job_ids, campaign_id)
    names = {c.id: c.name for c in (await session.scalars(select(Campaign).where(
        Campaign.id.in_({a.campaign_id for a in by_job.values()})))).all()} if by_job else {}

    rows: list[CompareRow] = []
    for name in FACET_ROWS:
        rows.append(CompareRow(key=f"facet:{name}", label=name.replace("_", " ").capitalize(), group="facets",
                               cells=[_facet_cell(j, name) for j in jobs], comparable=True))
    rows.append(CompareRow(key="required_skills", label="Required skills", group="facets", comparable=True, cells=[
        CompareCell(value=", ".join(j.facets.required_skills) or None,
                    state="stated" if j.facets.required_skills else "not_stated") for j in jobs]))
    rows.append(_pay_row(jobs))
    rows.extend(_score_rows(jobs, by_job))
    group_cells = [CompareCell(value=j.canonical_employer, state="stated",
                               note=(f"{j.conflict_state.value}: {j.conflict_note}" if j.conflict_note
                                     else j.conflict_state.value)) for j in jobs]
    rows.append(CompareRow(key="employer_group", label="Employer group", group="employer", cells=group_cells,
                           comparable=False, note="one role per employer is applied to (7.1)"))
    rows.append(CompareRow(key="deadline", label="Deadline", group="timing", cells=[_deadline_cell(j) for j in jobs],
                           comparable=True))
    rows.append(CompareRow(key="availability", label="Posting", group="timing", comparable=True, cells=[
        CompareCell(value=j.availability.value, state="unknown" if j.availability.value == "unknown" else "stated")
        for j in jobs]))
    rows.append(CompareRow(key="apply_method", label="How to apply", group="apply", comparable=True, cells=[
        CompareCell(value=j.apply_method, state="not_stated" if j.apply_method == "unknown" else "stated")
        for j in jobs]))
    rows.append(CompareRow(key="channel", label="Channel available", group="apply", comparable=True,
                           cells=[await _channel_cell(session, j) for j in jobs]))

    winner_id, reason = _winner(jobs)
    return CompareOut(
        job_ids=job_ids, rows=rows, winner_id=winner_id, winner_reason=reason,
        jobs=[_job_out(j, by_job.get(j.id), names) for j in jobs])


def _job_out(job: Job, a: Assessment | None, names: dict[uuid.UUID, str]) -> CompareJob:
    return CompareJob(id=job.id, title=job.title, employer=job.employer, location=_location(job),
                      availability=job.availability.value, campaign_id=a.campaign_id if a else None,
                      campaign_name=names.get(a.campaign_id) if a else None, score=a.score if a else None,
                      assessment_state=a.state.value if a else None)


def _winner(jobs: list[Job]) -> tuple[uuid.UUID | None, str | None]:
    """The conflict group's recorded winner, when every role shares one employer and exactly one of them won."""
    if len({j.canonical_employer for j in jobs}) != 1:
        return None, None
    winners = [j for j in jobs if j.conflict_state.value == "winner"]
    if len(winners) != 1:
        return None, None
    note: Any = winners[0].conflict_note
    return winners[0].id, str(note) if note else "chosen by the employer group's rules"
