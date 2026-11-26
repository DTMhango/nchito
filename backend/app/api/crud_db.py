"""Database-backed CRUD endpoints for the simple owner-edited tables (sources, watched employers,
aliases, schedules). The counterpart of ``crud.py`` (which only registers 501 stubs).

Kept free of ``from __future__ import annotations`` on purpose: FastAPI reads the endpoint
annotations at runtime and they reference the models passed in.
"""

import base64
import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Page
from app.api.deps import PrincipalDep, SessionDep
from app.core import audit
from app.models.base import Base

# ``prepare(session, data, existing)`` validates and coerces a request body (as a dict) before it
# is stored; it raises ``ValueError`` (422) or ``HTTPException``.
Prepare = Callable[[Any, dict[str, Any], Any], Awaitable[dict[str, Any]]]
AfterSave = Callable[[Any, Any], Awaitable[None]]


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor.encode()).decode()))
    except ValueError as exc:
        raise HTTPException(422, detail="invalid cursor") from exc


async def page_of(session: Any, orm: type[Base], order: Iterable[Any], cursor: str | None, limit: int,
                  *where: Any) -> tuple[list[Any], int, str | None]:
    limit = max(1, min(limit, 200))
    offset = decode_cursor(cursor)
    total = await session.scalar(select(func.count()).select_from(orm).where(*where))
    rows = (await session.scalars(select(orm).where(*where).order_by(*order).offset(offset).limit(limit))).all()
    more = offset + len(rows) < (total or 0)
    return list(rows), total or 0, encode_cursor(offset + len(rows)) if more else None


def add_db_crud(
    router: APIRouter,
    path: str,
    name: str,
    *,
    orm: Any,
    model_in: Any,
    model_out: Any,
    audit_prefix: str,
    order_by: Iterable[Any],
    prepare: Prepare | None = None,
    after_save: AfterSave | None = None,
    ops: Iterable[str] = ("list", "get", "create", "update", "delete"),
) -> None:
    """Register ``<name>_list/get/create/update/delete`` for ``path`` with real bodies."""
    ops = set(ops)
    order = list(order_by)

    async def _prepared(session: Any, body: Any, existing: Any) -> dict[str, Any]:
        data = body.model_dump()
        try:
            return await prepare(session, data, existing) if prepare else data
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    async def _load(session: Any, item_id: uuid.UUID) -> Any:
        obj = await session.get(orm, item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        return obj

    async def _flush(session: Any) -> None:
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, detail="already exists") from exc

    if "list" in ops:
        async def list_items(session: SessionDep, cursor: str | None = None,
                             limit: int = 50) -> Page[model_out]:  # type: ignore[valid-type]
            rows, total, nxt = await page_of(session, orm, order, cursor, limit)
            return Page[model_out](items=[model_out.model_validate(r) for r in rows],  # type: ignore[valid-type]
                                   total=total, next_cursor=nxt)

        router.add_api_route(path, list_items, methods=["GET"], response_model=Page[model_out], name=f"{name}_list",
                             responses=NOT_IMPLEMENTED_RESPONSES)

    if "get" in ops:
        async def get_item(item_id: uuid.UUID, session: SessionDep) -> model_out:  # type: ignore[valid-type]
            return model_out.model_validate(await _load(session, item_id))

        router.add_api_route(f"{path}/{{item_id}}", get_item, methods=["GET"], response_model=model_out,
                             name=f"{name}_get")

    if "create" in ops:
        async def create_item(body: model_in, session: SessionDep,  # type: ignore[valid-type]
                              principal: PrincipalDep) -> model_out:  # type: ignore[valid-type]
            obj = orm(**await _prepared(session, body, None))
            session.add(obj)
            await _flush(session)
            if after_save:
                await after_save(session, obj)
            await audit.record(session, actor=principal.actor, action=f"{audit_prefix}.created",
                               subject_type=audit_prefix, subject_id=obj.id)
            await session.refresh(obj)
            return model_out.model_validate(obj)

        router.add_api_route(path, create_item, methods=["POST"], response_model=model_out,
                             status_code=status.HTTP_201_CREATED, name=f"{name}_create")

    if "update" in ops:
        async def update_item(item_id: uuid.UUID, body: model_in, session: SessionDep,  # type: ignore[valid-type]
                              principal: PrincipalDep) -> model_out:  # type: ignore[valid-type]
            obj = await _load(session, item_id)
            for key, value in (await _prepared(session, body, obj)).items():
                setattr(obj, key, value)
            await _flush(session)
            if after_save:
                await after_save(session, obj)
            await audit.record(session, actor=principal.actor, action=f"{audit_prefix}.updated",
                               subject_type=audit_prefix, subject_id=obj.id)
            await session.refresh(obj)
            return model_out.model_validate(obj)

        router.add_api_route(f"{path}/{{item_id}}", update_item, methods=["PUT"], response_model=model_out,
                             name=f"{name}_update")

    if "delete" in ops:
        async def delete_item(item_id: uuid.UUID, session: SessionDep, principal: PrincipalDep) -> Response:
            obj = await _load(session, item_id)
            await session.delete(obj)
            await audit.record(session, actor=principal.actor, action=f"{audit_prefix}.deleted",
                               subject_type=audit_prefix, subject_id=item_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        router.add_api_route(f"{path}/{{item_id}}", delete_item, methods=["DELETE"],
                             status_code=status.HTTP_204_NO_CONTENT, name=f"{name}_delete",
                             response_class=Response)
