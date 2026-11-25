"""Registers typed CRUD endpoints whose bodies arrive in a later wave (501 until then).

Kept free of ``from __future__ import annotations`` on purpose: FastAPI reads the endpoint
annotations at runtime and they reference the models passed in.
"""

import uuid
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.common import NOT_IMPLEMENTED_RESPONSES, Page, not_implemented
from app.api.deps import RequireOwner


def add_crud(
    router: APIRouter,
    path: str,
    name: str,
    model_in: Any,
    model_out: Any,
    *,
    wave: int,
    area: str,
    ops: Iterable[str] = ("list", "get", "create", "update", "delete"),
    list_params: Any = None,
) -> None:
    """Add ``list/get/create/update/delete`` for ``path`` (e.g. ``/facts``) named ``<name>_<op>``."""
    ops = set(ops)
    deps = [RequireOwner]

    if "list" in ops:
        if list_params is not None:
            async def list_items(params: Annotated[list_params, Query()]) -> Page[model_out]:  # type: ignore[valid-type]
                not_implemented(wave, area)
        else:
            async def list_items(cursor: str | None = None, limit: int = 50) -> Page[model_out]:  # type: ignore[valid-type]
                not_implemented(wave, area)

        router.add_api_route(path, list_items, methods=["GET"], response_model=Page[model_out], name=f"{name}_list",
                             dependencies=deps, responses=NOT_IMPLEMENTED_RESPONSES)

    if "get" in ops:
        async def get_item(item_id: uuid.UUID) -> model_out:  # type: ignore[valid-type]
            not_implemented(wave, area)

        router.add_api_route(f"{path}/{{item_id}}", get_item, methods=["GET"], response_model=model_out,
                             name=f"{name}_get", dependencies=deps, responses=NOT_IMPLEMENTED_RESPONSES)

    if "create" in ops:
        async def create_item(body: model_in) -> model_out:  # type: ignore[valid-type]
            not_implemented(wave, area)

        router.add_api_route(path, create_item, methods=["POST"], response_model=model_out,
                             status_code=status.HTTP_201_CREATED, name=f"{name}_create", dependencies=deps,
                             responses=NOT_IMPLEMENTED_RESPONSES)

    if "update" in ops:
        async def update_item(item_id: uuid.UUID, body: model_in) -> model_out:  # type: ignore[valid-type]
            not_implemented(wave, area)

        router.add_api_route(f"{path}/{{item_id}}", update_item, methods=["PUT"], response_model=model_out,
                             name=f"{name}_update", dependencies=deps, responses=NOT_IMPLEMENTED_RESPONSES)

    if "delete" in ops:
        async def delete_item(item_id: uuid.UUID) -> Response:
            not_implemented(wave, area)

        router.add_api_route(f"{path}/{{item_id}}", delete_item, methods=["DELETE"],
                             status_code=status.HTTP_204_NO_CONTENT, name=f"{name}_delete",
                             dependencies=deps, responses=NOT_IMPLEMENTED_RESPONSES,
                             response_class=Response)
