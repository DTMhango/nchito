"""Employers and the cooldown (DESIGN 7.1, 8.1, 10.3, wave 4).

An employer is the alias-resolved canonical employer. The list shows each employer's state (free, role in
progress, cooling down until a date, always ask first, blocked); the page shows every role seen, its conflict
groups (winner and held), the applications, contacts and notes, and the exact cooldown rule that applies and
when it ends. Per-employer overrides (cooldown length, always ask first, never apply with a reason, priority
and watch) and ending a cooldown early are audited. Merge and split reuse the corrections code. The employer
is addressed by ``key`` (query parameter), which may contain spaces and slashes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import stages
from app.core.clock import utcnow
from app.pipeline import employers
from app.schemas.json_types import CooldownKind, EmployerStateName

router = APIRouter(prefix="/api/employers", tags=["employers"], dependencies=[RequireOwner])

KeyQ = Annotated[str, Query(min_length=1, max_length=200, description="The employer key (casefolded canonical name)")]


class EmployerRowOut(BaseModel):
    key: str
    name: str
    state: EmployerStateName
    state_text: str
    applications: int
    live: int
    last_applied_at: datetime | None
    roles_seen: int
    held_roles: int
    cooldown_until: date | None
    always_ask_first: bool
    never_apply: bool
    never_reason: str | None
    watched: bool
    priority: int
    cooldown_days: int | None = Field(description="This employer's override; null uses the default")


class RoleOut(BaseModel):
    job_id: uuid.UUID
    title: str
    triage: str
    conflict_state: str
    conflict_note: str | None
    score: int | None
    application_id: uuid.UUID | None
    stage: str | None
    posted_at: datetime | None


class HistoryOut(BaseModel):
    application_id: uuid.UUID
    job_id: uuid.UUID
    title: str
    stage: str
    applied_at: datetime | None
    ended_at: datetime | None
    counts_toward_cooldown: bool


class ContactRowOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    name: str
    role: str | None
    email: str | None
    link: str | None


class CooldownOut(BaseModel):
    kind: CooldownKind = Field(description="end_state: from the end state; applied_date: from the applied date, "
                                           "because there has been no reply")
    application_id: uuid.UUID
    starts_on: date
    days: int
    ends_on: date
    running: bool
    rule: str = Field(description="The rule in words, with the dates")


class EmployerDetailOut(BaseModel):
    employer: EmployerRowOut
    cooldown: CooldownOut | None
    cooldown_days: int = Field(description="The length in force")
    cooldown_days_source: str
    cooldown_ended_early_at: datetime | None
    cooldown_ended_early_by: str | None
    cooldown_ended_early_reason: str | None
    roles: list[RoleOut]
    conflict_groups: list[list[RoleOut]] = Field(description="Roles that compete (winner and held)")
    history: list[HistoryOut]
    contacts: list[ContactRowOut]
    aliases: list[str] = Field(description="Names merged into this employer")
    notes: str | None


class PolicyIn(BaseModel):
    """Only the fields sent change. ``never_apply`` needs ``never_reason``."""

    cooldown_days: int | None = Field(default=None, ge=0, le=3650, description="null clears the override")
    always_ask_first: bool | None = None
    never_apply: bool | None = None
    never_reason: str | None = Field(default=None, max_length=1000)
    priority: int | None = Field(default=None, ge=-100, le=100)
    watched: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)


class EndCooldownIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class MergeIn(BaseModel):
    into: str = Field(min_length=1, max_length=200, description="The canonical employer to merge this one into")
    remember_alias: bool = True


class SplitIn(BaseModel):
    alias: str = Field(min_length=1, max_length=200, description="A name that was merged into another employer")


class MergeOut(BaseModel):
    jobs: int


class StatesIn(BaseModel):
    job_ids: list[uuid.UUID] = Field(max_length=500)


class ChipOut(BaseModel):
    state: EmployerStateName
    text: str
    live: int = Field(default=0, description="The employer's roles in progress (this job's included)")
    live_elsewhere: int = Field(default=0, description="Roles in progress at this employer other than this job")


class StatesOut(BaseModel):
    states: dict[str, ChipOut] = Field(description="By job id")


def _http(exc: employers.EmployerError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "reason": str(exc)})


def _row(r: employers.EmployerRow) -> EmployerRowOut:
    return EmployerRowOut(**r.__dict__)


def _role(r: employers.EmployerRoleRow) -> RoleOut:
    return RoleOut(**r.__dict__)


@router.get("", response_model=list[EmployerRowOut], name="employers_list")
async def list_employers(session: SessionDep, state: EmployerStateName | None = None, q: str | None = None
                         ) -> list[EmployerRowOut]:
    rows = await employers.overview(session)
    if state:
        rows = [r for r in rows if r.state == state]
    if q and q.strip():
        needle = q.strip().casefold()
        rows = [r for r in rows if needle in r.name.casefold()]
    return [_row(r) for r in rows]


@router.post("/states", response_model=StatesOut, name="employers_states")
async def states(body: StatesIn, session: SessionDep) -> StatesOut:
    """The employer chip for each job (Matches and Applications), read only."""
    found = await employers.states_for_jobs(session, body.job_ids)
    return StatesOut(states={str(j): ChipOut(state=c.state, text=c.text, live=c.live, live_elsewhere=c.live_elsewhere)
                             for j, c in found.items()})


@router.get("/detail", response_model=EmployerDetailOut, name="employers_get")
async def get_employer(key: KeyQ, session: SessionDep) -> EmployerDetailOut:
    today = utcnow().date()
    try:
        d = await employers.detail(session, key.strip().casefold())
    except employers.EmployerError as exc:
        raise _http(exc) from exc
    cooldown = None
    if d.cooldown is not None:
        c = d.cooldown
        cooldown = CooldownOut(kind=c.kind, application_id=c.application_id, starts_on=c.anchor.date(), days=c.days,
                               ends_on=c.until, running=c.until > today, rule=c.text)
    titles = {r.job_id: r.title for r in d.roles}
    return EmployerDetailOut(
        employer=_row(d.row), cooldown=cooldown, cooldown_days=d.days, cooldown_days_source=d.days_source,
        cooldown_ended_early_at=d.released_at, cooldown_ended_early_by=d.released_by,
        cooldown_ended_early_reason=d.released_reason, roles=[_role(r) for r in d.roles],
        conflict_groups=[[_role(r) for r in g] for g in d.groups],
        history=[HistoryOut(application_id=a.id, job_id=a.job_id, title=titles.get(a.job_id, ""),
                            stage=a.stage.value, applied_at=a.applied_at, ended_at=a.ended_at,
                            counts_toward_cooldown=stages.counts_as_application(a)) for a in d.applications],
        contacts=[ContactRowOut(id=c.id, job_id=c.job_id, name=c.name, role=c.role, email=c.email, link=c.link)
                  for c in d.contacts],
        aliases=d.aliases, notes=d.notes)


async def _row_for(session: SessionDep, key: str) -> EmployerRowOut:
    return _row(next(r for r in await employers.overview(session) if r.key == key))


@router.patch("/policy", response_model=EmployerRowOut, name="employers_set_policy",
              responses={422: {"description": "A reason is required to never apply ({code, reason})"}})
async def set_policy(key: KeyQ, body: PolicyIn, principal: PrincipalDep, session: SessionDep) -> EmployerRowOut:
    """Per-employer overrides (audited). 'Never apply' blocks tailoring and sending for every role there."""
    key = key.strip().casefold()
    changes = body.model_dump(exclude_unset=True)
    for name in ("always_ask_first", "never_apply", "priority", "watched"):
        if name in changes and changes[name] is None:
            del changes[name]
    try:
        await employers.update_policy(session, key, changes, actor=principal.actor)
        return await _row_for(session, key)
    except employers.EmployerError as exc:
        raise _http(exc) from exc


@router.post("/end-cooldown", response_model=EmployerRowOut, name="employers_end_cooldown",
             responses={409: {"description": "No cooldown is running ({code, reason})"}})
async def end_cooldown(key: KeyQ, body: EndCooldownIn, principal: PrincipalDep, session: SessionDep
                       ) -> EmployerRowOut:
    """End the running cooldown early, with a reason (audited)."""
    key = key.strip().casefold()
    try:
        await employers.end_cooldown(session, key, reason=body.reason, actor=principal.actor)
        return await _row_for(session, key)
    except employers.EmployerError as exc:
        raise _http(exc) from exc


@router.post("/merge", response_model=MergeOut, name="employers_merge")
async def merge(key: KeyQ, body: MergeIn, principal: PrincipalDep, session: SessionDep) -> MergeOut:
    """Merge this employer into another (every role posted under it moves; the alias can be remembered)."""
    try:
        n = await employers.merge_employers(session, key.strip().casefold(), body.into,
                                            remember_alias=body.remember_alias, actor=principal.actor)
    except employers.EmployerError as exc:
        raise _http(exc) from exc
    return MergeOut(jobs=n)


@router.post("/split", response_model=MergeOut, name="employers_split")
async def split(body: SplitIn, principal: PrincipalDep, session: SessionDep) -> MergeOut:
    """Undo a merge: the name stops being an alias and its roles go back under their own employer."""
    try:
        n = await employers.split_employer(session, body.alias, actor=principal.actor)
    except employers.EmployerError as exc:
        raise _http(exc) from exc
    return MergeOut(jobs=n)
