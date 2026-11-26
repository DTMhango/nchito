"""Portal accounts registry (DESIGN.md 8.4): where the owner has an account and on which runner the session
lives. Owner only, audited. There is no field for a password or any secret, and one cannot be sent."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Page, Timestamps
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.apply import accounts, owner_actions
from app.core import audit
from app.core.clock import utcnow
from app.core.events import publish
from app.models.applications import PendingAction, PortalAccount, PortalAccountStatus

router = APIRouter(prefix="/api/portal-accounts", tags=["portal_accounts"], dependencies=[RequireOwner])

StatusT = Literal["none", "created", "signed_in"]
_SECRET_WORDS = ("password", "passwd", "passcode", "secret", "credential", "token", "pin", "otp", "cookie")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_secrets(cls, data: Any) -> Any:
        if isinstance(data, dict):
            bad = [k for k in data if any(w in str(k).lower() for w in _SECRET_WORDS)]
            if bad:
                raise ValueError("passwords and secrets are never stored; nothing here accepts one")
        return data


class PortalAccountWrite(_Strict):
    portal: str = Field(min_length=1, max_length=60, description="workday, icims, taleo, ...")
    tenant: str = Field(min_length=1, max_length=200,
                        description="Tenant host (and site), e.g. arch.wd5.myworkdayjobs.com/arch")
    url: str | None = None
    status: StatusT = "none"
    signed_in_runner: str | None = Field(default=None, max_length=120, description="pc, server or a runner name")
    email_used: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("portal", "tenant")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class PortalAccountPatch(_Strict):
    url: str | None = None
    status: StatusT | None = None
    signed_in_runner: str | None = Field(default=None, max_length=120)
    email_used: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=2000)


class PortalAccountOut(Timestamps):
    portal: str
    tenant: str
    key: str
    url: str | None
    status: StatusT
    signed_in_runner: str | None
    email_used: str | None
    last_sign_in_at: datetime | None
    notes: str | None
    waiting_applications: int = Field(description="Applications waiting on the open sign-in request, if any")
    open_action_id: uuid.UUID | None = None


class GiveUpIn(_Strict):
    outcome: Literal["manual_handoff", "skipped"] = Field(
        description="manual_handoff: the owner applies by hand; skipped: the application is skipped")
    application_ids: list[uuid.UUID] | None = Field(default=None, description="Default: every waiting application")
    note: str | None = Field(default=None, max_length=500)


class GiveUpOut(BaseModel):
    outcome: str
    handled: list[str]
    remaining: int
    closed: bool


class RefreshOut(BaseModel):
    raised: int
    joined: int
    closed: int
    reminded: int


async def _out(session: AsyncSession, row: PortalAccount) -> PortalAccountOut:
    action = await accounts._open_for_group(session, f"portal:{row.portal}:{row.tenant}")
    return PortalAccountOut(
        id=row.id, created_at=row.created_at, updated_at=row.updated_at, portal=row.portal, tenant=row.tenant,
        key=f"{row.portal}:{row.tenant}", url=row.url, status=row.status.value, signed_in_runner=row.signed_in_runner,
        email_used=row.email_used, last_sign_in_at=row.last_sign_in_at, notes=row.notes,
        waiting_applications=len(action.detail.get("applications", [])) if action else 0,
        open_action_id=action.id if action else None)


async def _load(session: AsyncSession, account_id: uuid.UUID) -> PortalAccount:
    row = await session.get(PortalAccount, account_id)
    if row is None:
        raise HTTPException(404, detail="portal account not found")
    return row


def _apply_status(row: PortalAccount, new: str, runner: str | None) -> None:
    row.status = PortalAccountStatus(new)
    if new == "signed_in":
        if not runner:
            raise HTTPException(422, detail="say which runner holds the session (signed_in_runner)")
        row.signed_in_runner = runner
        row.last_sign_in_at = utcnow()
    else:
        row.signed_in_runner = None


@router.get("", response_model=Page[PortalAccountOut], name="portal_accounts_list")
async def list_accounts(session: SessionDep, status_: StatusT | None = Query(default=None, alias="status")
                        ) -> Page[PortalAccountOut]:
    stmt = select(PortalAccount).order_by(PortalAccount.portal, PortalAccount.tenant)
    if status_:
        stmt = stmt.where(PortalAccount.status == PortalAccountStatus(status_))
    rows = (await session.scalars(stmt)).all()
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    return Page(items=[await _out(session, r) for r in rows], total=total)


@router.post("", response_model=PortalAccountOut, status_code=status.HTTP_201_CREATED, name="portal_accounts_create")
async def create_account(body: PortalAccountWrite, principal: PrincipalDep, session: SessionDep) -> PortalAccountOut:
    row = PortalAccount(portal=body.portal, tenant=body.tenant, url=body.url, email_used=body.email_used,
                        notes=body.notes)
    _apply_status(row, body.status, body.signed_in_runner)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, detail="an account for this portal tenant is already recorded") from exc
    await session.refresh(row)
    await audit.record(session, actor=principal.actor, action="portal_account.created", subject_type="portal_account",
                       subject_id=row.id, detail={"key": f"{row.portal}:{row.tenant}", "status": row.status.value})
    await accounts.reconcile_actions(session, utcnow(), group_key=f"portal:{row.portal}:{row.tenant}")
    return await _out(session, row)


@router.get("/{account_id}", response_model=PortalAccountOut, name="portal_accounts_get")
async def get_account(account_id: uuid.UUID, session: SessionDep) -> PortalAccountOut:
    return await _out(session, await _load(session, account_id))


@router.patch("/{account_id}", response_model=PortalAccountOut, name="portal_accounts_update")
async def update_account(account_id: uuid.UUID, body: PortalAccountPatch, principal: PrincipalDep,
                         session: SessionDep) -> PortalAccountOut:
    row = await _load(session, account_id)
    fields = body.model_dump(exclude_unset=True)
    for name in ("url", "email_used", "notes"):
        if name in fields:
            setattr(row, name, fields[name])
    if fields.get("status") is not None:
        _apply_status(row, fields["status"], fields.get("signed_in_runner") or row.signed_in_runner)
    elif fields.get("signed_in_runner") and row.status == PortalAccountStatus.signed_in:
        row.signed_in_runner = fields["signed_in_runner"]
    await session.flush()
    await session.refresh(row)
    await audit.record(session, actor=principal.actor, action="portal_account.updated", subject_type="portal_account",
                       subject_id=row.id, detail={"changed": sorted(fields), "status": row.status.value})
    await accounts.reconcile_actions(session, utcnow(), group_key=f"portal:{row.portal}:{row.tenant}")
    return await _out(session, row)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, name="portal_accounts_delete")
async def delete_account(account_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> Response:
    row = await _load(session, account_id)
    await audit.record(session, actor=principal.actor, action="portal_account.deleted", subject_type="portal_account",
                       subject_id=row.id, detail={"key": f"{row.portal}:{row.tenant}"})
    await session.delete(row)
    await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/actions/{action_id}/give-up", response_model=GiveUpOut, name="portal_accounts_give_up")
async def give_up(action_id: uuid.UUID, body: GiveUpIn, principal: PrincipalDep, session: SessionDep) -> GiveUpOut:
    """The owner cannot or will not get past the blocker: move the waiting applications (default all) to manual
    handoff or skip them."""
    action = await session.get(PendingAction, action_id)
    if action is None:
        raise HTTPException(404, detail="pending action not found")
    try:
        result = await accounts.give_up(session, action, outcome=body.outcome, application_ids=body.application_ids,
                                        actor=principal.actor, note=body.note)
    except owner_actions.ResolveError as exc:
        raise HTTPException(exc.status, detail=exc.message) from exc
    await publish(session, "pending_action.resolved" if result.closed else "pending_action.updated",
                  {"pending_action_id": str(action.id)})
    return GiveUpOut(outcome=result.outcome, handled=result.handled, remaining=result.remaining, closed=result.closed)


@router.post("/refresh", response_model=RefreshOut, name="portal_accounts_refresh")
async def refresh(session: SessionDep) -> RefreshOut:
    """Run the periodic pass now: raise or join sign-in requests, drop what no longer waits, send due reminders."""
    r = await accounts.tick(session)
    return RefreshOut(raised=r.raised, joined=r.joined, closed=r.closed, reminded=r.reminded)


__all__ = ["router"]
