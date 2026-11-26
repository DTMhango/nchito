"""Generic audited CRUD routes for Kit records.

No ``from __future__ import annotations`` on purpose: FastAPI reads the endpoint annotations at
runtime and they reference the models passed in (same reason as ``app/api/crud.py``).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Page
from app.api.deps import PrincipalDep, RequireOwner, SessionDep
from app.core import audit
from app.core.clock import utcnow
from app.models.base import Origin, ReviewState


@dataclass
class Resource:
    """How one Kit entity is exposed. ``entity`` is the review/audit name (``fact``, ``skill``)."""

    entity: str
    model: Any
    model_in: Any
    model_out: Any
    to_columns: Callable[[Any], dict[str, Any]] = lambda body: body.model_dump()
    on_create: Callable[[AsyncSession, dict[str, Any]], Any] | None = None
    order_by: tuple[Any, ...] = field(default_factory=tuple)
    subject: Callable[[Any], str] = lambda row: str(row.id)
    delete: Callable[[AsyncSession, Any], Any] | None = None  # replaces a hard delete (e.g. retire)


async def flush_or_409(session: AsyncSession, message: str) -> None:
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=message) from exc


async def load(session: AsyncSession, res: Resource, item_id: uuid.UUID) -> Any:
    row = await session.get(res.model, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{res.entity} not found")
    return row


def _offset(cursor: str | None) -> int:
    try:
        return max(int(cursor), 0) if cursor else 0
    except ValueError:
        raise HTTPException(422, detail="bad cursor") from None


async def page_of(session: AsyncSession, res: Resource, stmt: Select[Any], cursor: str | None,
                  limit: int) -> Page[Any]:
    offset = _offset(cursor)
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await session.scalars(stmt.order_by(*res.order_by, res.model.id).offset(offset).limit(limit + 1))).all()
    more = len(rows) > limit
    return Page[res.model_out](  # type: ignore[name-defined]
        items=[res.model_out.model_validate(r) for r in rows[:limit]],
        total=total,
        next_cursor=str(offset + limit) if more else None,
    )


def add_kit_crud(
    router: APIRouter,
    path: str,
    name: str,
    res: Resource,
    *,
    list_params: Any = None,
    apply_filters: Callable[[Select[Any], Any], Select[Any]] | None = None,
    ops: tuple[str, ...] = ("list", "get", "create", "update", "delete"),
) -> None:
    deps = [RequireOwner]
    model_in, model_out = res.model_in, res.model_out

    if "list" in ops:
        if list_params is not None:
            async def list_items(params: Annotated[list_params, Query()], session: SessionDep) -> Page[model_out]:  # type: ignore[valid-type]
                stmt = apply_filters(select(res.model), params) if apply_filters else select(res.model)
                return await page_of(session, res, stmt, params.cursor, params.limit)
        else:
            async def list_items(session: SessionDep, cursor: str | None = None,  # type: ignore[misc]
                                 limit: Annotated[int, Query(ge=1, le=500)] = 50) -> Page[model_out]:  # type: ignore[valid-type]
                return await page_of(session, res, select(res.model), cursor, limit)

        router.add_api_route(path, list_items, methods=["GET"], response_model=Page[model_out],
                             name=f"{name}_list", dependencies=deps)

    if "get" in ops:
        async def get_item(item_id: uuid.UUID, session: SessionDep) -> model_out:  # type: ignore[valid-type]
            return model_out.model_validate(await load(session, res, item_id))

        router.add_api_route(f"{path}/{{item_id}}", get_item, methods=["GET"], response_model=model_out,
                             name=f"{name}_get", dependencies=deps)

    if "create" in ops:
        async def create_item(body: model_in, principal: PrincipalDep, session: SessionDep) -> model_out:  # type: ignore[valid-type]
            cols = res.to_columns(body)
            if res.on_create:
                await res.on_create(session, cols)
            row = res.model(**cols, origin=Origin.owner, review_state=ReviewState.confirmed,
                            confirmed_at=utcnow())
            session.add(row)
            await flush_or_409(session, f"{res.entity} already exists")
            await session.refresh(row)
            await audit.record(session, actor=principal.actor, action=f"kit.{res.entity}.created",
                               subject_type=res.entity, subject_id=row.id, detail={"label": res.subject(row)})
            return model_out.model_validate(row)

        router.add_api_route(path, create_item, methods=["POST"], response_model=model_out,
                             status_code=status.HTTP_201_CREATED, name=f"{name}_create", dependencies=deps)

    if "update" in ops:
        async def update_item(item_id: uuid.UUID, body: model_in, principal: PrincipalDep,  # type: ignore[valid-type]
                              session: SessionDep) -> model_out:  # type: ignore[valid-type]
            row = await load(session, res, item_id)
            changed = []
            for key, value in res.to_columns(body).items():
                if key == "code" and value is None:
                    continue
                if key == "code" and value != row.code:
                    raise HTTPException(422, detail="a fact code never changes")
                if getattr(row, key) != value:
                    setattr(row, key, value)
                    changed.append(key)
            await flush_or_409(session, f"{res.entity} conflicts with an existing one")
            await session.refresh(row)
            await audit.record(session, actor=principal.actor, action=f"kit.{res.entity}.updated",
                               subject_type=res.entity, subject_id=row.id,
                               detail={"label": res.subject(row), "fields": changed})
            return model_out.model_validate(row)

        router.add_api_route(f"{path}/{{item_id}}", update_item, methods=["PUT"], response_model=model_out,
                             name=f"{name}_update", dependencies=deps)

    if "delete" in ops:
        async def delete_item(item_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> Response:
            row = await load(session, res, item_id)
            label = res.subject(row)
            if res.delete:
                await res.delete(session, row)
            else:
                await session.delete(row)
            await flush_or_409(session, f"{res.entity} is still in use")
            await audit.record(session, actor=principal.actor, action=f"kit.{res.entity}.deleted",
                               subject_type=res.entity, subject_id=item_id, detail={"label": label})
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        router.add_api_route(f"{path}/{{item_id}}", delete_item, methods=["DELETE"],
                             status_code=status.HTTP_204_NO_CONTENT, name=f"{name}_delete",
                             dependencies=deps, response_class=Response)
