"""Request dependencies: database session, signed-in owner."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_config
from app.core.db import get_session
from app.core.security import unsign_session
from app.models.platform import AuthSession, Owner

# scope="function": the transaction commits before the response is sent, so a client that
# acts on a response always sees the committed state.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]

OWNER_ACTOR = "owner"
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class Principal:
    owner: Owner
    session_id: uuid.UUID
    actor: str = OWNER_ACTOR


async def current_principal(request: Request, session: SessionDep) -> Principal:
    cookie = request.cookies.get(get_config().session_cookie_name)
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not signed in")
    if not cookie:
        raise unauthorised
    raw = unsign_session(cookie)
    if raw is None:
        raise unauthorised
    try:
        session_id = uuid.UUID(raw)
    except ValueError as exc:
        raise unauthorised from exc
    auth = await session.get(AuthSession, session_id)
    now = utcnow()
    if auth is None or auth.revoked_at is not None or auth.expires_at <= now:
        raise unauthorised
    owner = await session.get(Owner, auth.owner_id)
    if owner is None:
        raise unauthorised
    if now - auth.last_seen_at > TOUCH_INTERVAL:
        auth.last_seen_at = now
    return Principal(owner=owner, session_id=session_id)


PrincipalDep = Annotated[Principal, Depends(current_principal)]
RequireOwner = Depends(current_principal)
