"""First-run setup and owner authentication."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import OWNER_ACTOR, PrincipalDep, SessionDep
from app.core import audit, crypto
from app.core.clock import utcnow
from app.core.config import get_config
from app.core.security import (
    client_ip,
    hash_password,
    login_blocked,
    needs_rehash,
    new_totp_secret,
    note_login_attempt,
    password_problem,
    sign_session,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.core.settings import service as settings_service
from app.core.settings.types import SettingValueError
from app.models.platform import AuthSession, Owner

setup_router = APIRouter(prefix="/api/setup", tags=["setup"])
router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupStatus(BaseModel):
    owner_exists: bool


class OwnerCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)
    display_name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        problem = password_problem(v)
        if problem:
            raise ValueError(problem)
        return v


class Me(BaseModel):
    email: str
    display_name: str
    timezone: str
    app_name: str
    totp_enabled: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)
    totp: str | None = Field(default=None, max_length=12)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCode(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class TotpDisable(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=12)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=512)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        problem = password_problem(v)
        if problem:
            raise ValueError(problem)
        return v


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("timing-equaliser-not-a-password")


async def _owner(session: SessionDep) -> Owner | None:
    return await session.scalar(select(Owner).limit(1))


async def _me(session: SessionDep, owner: Owner) -> Me:
    values = await settings_service.values(session)
    return Me(email=owner.email, display_name=owner.display_name, timezone=values["general.timezone"],
              app_name=values["general.app_name"], totp_enabled=owner.totp_enabled)


async def _start_session(session: SessionDep, request: Request, response: Response, owner: Owner) -> None:
    cfg = get_config()
    max_age = timedelta(hours=cfg.session_max_age_hours)
    auth = AuthSession(owner_id=owner.id, expires_at=utcnow() + max_age,
                       user_agent=(request.headers.get("user-agent") or "")[:300] or None,
                       ip=request.client.host if request.client else None)
    session.add(auth)
    await session.flush()
    response.set_cookie(
        cfg.session_cookie_name, sign_session(str(auth.id)), max_age=int(max_age.total_seconds()),
        httponly=True, secure=cfg.cookie_secure, samesite="lax", path="/",
    )


@setup_router.get("/status", response_model=SetupStatus, operation_id="setup_status")
async def setup_status(session: SessionDep) -> SetupStatus:
    count = await session.scalar(select(func.count()).select_from(Owner))
    return SetupStatus(owner_exists=bool(count))


@setup_router.post("/owner", status_code=status.HTTP_201_CREATED, response_model=Me,
                   operation_id="setup_create_owner",
                   responses={409: {"description": "An owner already exists"}})
async def create_owner(body: OwnerCreate, request: Request, response: Response, session: SessionDep) -> Me:
    """Create the single owner account (first run only) and sign in."""
    if await _owner(session) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="an owner already exists")
    try:
        await settings_service.set_value(session, "general.timezone", body.timezone, actor=OWNER_ACTOR,
                                         reason="setup")
    except SettingValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    owner = Owner(email=str(body.email).lower(), display_name=body.display_name.strip(),
                  password_hash=hash_password(body.password))
    session.add(owner)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="an owner already exists") from exc
    await audit.record(session, actor=OWNER_ACTOR, action="owner.created", subject_type="owner",
                       subject_id=owner.id, ip=client_ip(request), detail={"email": owner.email})
    await _start_session(session, request, response, owner)
    return await _me(session, owner)


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_login",
             responses={401: {"description": "Bad credentials, or `totp_required` / `totp_invalid`"},
                        429: {"description": "Too many failed attempts"}})
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> Response:
    ip = client_ip(request)
    if await login_blocked(session, ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too many failed attempts; try later")
    owner = await _owner(session)
    email = str(body.email).lower()
    # Always run one Argon2 verification so timing does not reveal whether the email matched.
    password_ok = verify_password(owner.password_hash if owner else _dummy_hash(), body.password)
    if owner is None or owner.email != email or not password_ok:
        await note_login_attempt(session, ip, email, success=False)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    if owner.totp_enabled:
        if not body.totp:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="totp_required")
        if not owner.totp_secret_enc or not verify_totp(crypto.decrypt(owner.totp_secret_enc), body.totp):
            await note_login_attempt(session, ip, email, success=False)
            await session.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="totp_invalid")
    if needs_rehash(owner.password_hash):
        owner.password_hash = hash_password(body.password)
    await note_login_attempt(session, ip, email, success=True)
    await audit.record(session, actor=OWNER_ACTOR, action="auth.login", subject_type="owner",
                       subject_id=owner.id, ip=ip)
    response.status_code = status.HTTP_204_NO_CONTENT
    await _start_session(session, request, response, owner)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_logout")
async def logout(principal: PrincipalDep, request: Request, session: SessionDep) -> Response:
    auth = await session.get(AuthSession, principal.session_id)
    if auth is not None:
        auth.revoked_at = utcnow()
    await audit.record(session, actor=principal.actor, action="auth.logout", subject_type="owner",
                       subject_id=principal.owner.id, ip=client_ip(request))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(get_config().session_cookie_name, path="/")
    return response


@router.get("/me", response_model=Me, operation_id="auth_me",
            responses={401: {"description": "Not signed in"}})
async def me(principal: PrincipalDep, session: SessionDep) -> Me:
    return await _me(session, principal.owner)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_change_password")
async def change_password(body: PasswordChange, principal: PrincipalDep, request: Request,
                          session: SessionDep) -> Response:
    owner = principal.owner
    if not verify_password(owner.password_hash, body.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="current password is wrong")
    owner.password_hash = hash_password(body.new_password)
    owner.password_changed_at = utcnow()
    revoked = await _revoke(session, owner.id, keep=principal.session_id)
    await audit.record(session, actor=principal.actor, action="auth.password_changed", subject_type="owner",
                       subject_id=owner.id, ip=client_ip(request), detail={"sessions_revoked": revoked})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/totp/setup", response_model=TotpSetupOut, operation_id="auth_totp_setup")
async def totp_setup(principal: PrincipalDep, session: SessionDep) -> TotpSetupOut:
    """Generate a new secret (not active until confirmed with /totp/enable)."""
    owner = principal.owner
    if owner.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="two-factor sign-in is already on")
    secret = new_totp_secret()
    owner.totp_secret_enc = crypto.encrypt(secret)
    app_name = await settings_service.get_value(session, "general.app_name")
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(secret, owner.email, app_name))


@router.post("/totp/enable", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_totp_enable")
async def totp_enable(body: TotpCode, principal: PrincipalDep, session: SessionDep) -> Response:
    owner = principal.owner
    if not owner.totp_secret_enc or not verify_totp(crypto.decrypt(owner.totp_secret_enc), body.code):
        raise HTTPException(422, detail="code does not match")
    owner.totp_enabled = True
    await audit.record(session, actor=principal.actor, action="auth.totp_enabled", subject_type="owner",
                       subject_id=owner.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_totp_disable")
async def totp_disable(body: TotpDisable, principal: PrincipalDep, session: SessionDep) -> Response:
    owner = principal.owner
    if not owner.totp_enabled or not owner.totp_secret_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="two-factor sign-in is off")
    if not verify_password(owner.password_hash, body.password) or not verify_totp(
        crypto.decrypt(owner.totp_secret_enc), body.code
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="password or code is wrong")
    owner.totp_enabled = False
    owner.totp_secret_enc = None
    await audit.record(session, actor=principal.actor, action="auth.totp_disabled", subject_type="owner",
                       subject_id=owner.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None = None
    ip: str | None = None
    current: bool = False


async def _revoke(session: SessionDep, owner_id: uuid.UUID, keep: uuid.UUID | None = None,
                  only: uuid.UUID | None = None) -> int:
    stmt = update(AuthSession).where(AuthSession.owner_id == owner_id, AuthSession.revoked_at.is_(None))
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep)
    if only is not None:
        stmt = stmt.where(AuthSession.id == only)
    result = await session.execute(stmt.values(revoked_at=utcnow()))
    return result.rowcount or 0  # type: ignore[attr-defined]


@router.get("/sessions", response_model=list[SessionOut], operation_id="auth_sessions_list")
async def sessions_list(principal: PrincipalDep, session: SessionDep) -> list[SessionOut]:
    """Active (not revoked, not expired) sessions of the owner, newest first."""
    rows = (await session.scalars(
        select(AuthSession).where(AuthSession.owner_id == principal.owner.id,
                                  AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow())
        .order_by(AuthSession.created_at.desc())
    )).all()
    return [SessionOut(id=r.id, created_at=r.created_at, last_seen_at=r.last_seen_at,
                       user_agent=r.user_agent, ip=str(r.ip) if r.ip else None,
                       current=r.id == principal.session_id) for r in rows]


@router.post("/sessions/revoke-others", operation_id="auth_sessions_revoke_others")
async def sessions_revoke_others(principal: PrincipalDep, request: Request, session: SessionDep) -> dict[str, int]:
    count = await _revoke(session, principal.owner.id, keep=principal.session_id)
    await audit.record(session, actor=principal.actor, action="auth.sessions_revoked_others",
                       subject_type="owner", subject_id=principal.owner.id, ip=client_ip(request),
                       detail={"revoked": count})
    return {"revoked": count}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT,
               operation_id="auth_sessions_revoke", responses={404: {"description": "No such active session"}})
async def sessions_revoke(session_id: uuid.UUID, principal: PrincipalDep, request: Request,
                          session: SessionDep) -> Response:
    count = await _revoke(session, principal.owner.id, only=session_id)
    if not count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such active session")
    await audit.record(session, actor=principal.actor, action="auth.session_revoked", subject_type="auth_session",
                       subject_id=session_id, ip=client_ip(request),
                       detail={"was_current": session_id == principal.session_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
