"""One entry point for every gateway tool: validate the input, run the tool for this runner in one
transaction, validate the output. Used by the MCP server and directly by tests.

A refused call (``GatewayError``) still commits what the refusal itself recorded (an expired lease, a
blocker raised for an off-domain page); any other error rolls back.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.gateway import answers, blockers, common, release, runner_config, submit, sweep, tasks
from app.gateway.common import GatewayError
from app.gateway.tools import TOOLS
from app.models.platform import ApiToken

Handler = Callable[[AsyncSession, ApiToken, Any], Awaitable[BaseModel]]

HANDLERS: dict[str, Callable[..., Awaitable[BaseModel]]] = {
    "next_task": tasks.next_task,
    "get_packet": release.get_packet,
    "find_answer": answers.find_answer,
    "save_checkpoint": tasks.save_checkpoint,
    "raise_blocker": blockers.raise_blocker,
    "request_submit_permit": submit.request_submit_permit,
    "report_result": submit.report_result,
    "report_jobs": sweep.report_jobs,
    "report_check": tasks.report_check,
    "release_task": tasks.release_task,
    "evidence_upload_url": release.evidence_upload_url,
    "get_runner_config": runner_config.get_runner_config,
}
assert set(HANDLERS) == set(TOOLS), "every contract tool has exactly one handler"


async def call_in(session: AsyncSession, token_id: uuid.UUID, name: str, arguments: dict[str, Any], *,
                  at: datetime | None = None) -> dict[str, Any]:
    """Run one tool for a runner in ``session`` (the caller commits or rolls back)."""
    if name not in TOOLS:
        raise GatewayError("unknown_tool", f"no tool named {name}")
    in_model, out_model, _ = TOOLS[name]
    try:
        body = in_model.model_validate(arguments or {})
    except ValidationError as exc:
        raise GatewayError("invalid_input", exc.errors(include_url=False, include_context=False).__repr__()[:1000]
                           ) from exc
    token = await session.get(ApiToken, token_id, with_for_update=True, populate_existing=True)
    if token is None or token.revoked_at is not None:
        raise GatewayError("token_revoked", "this token has been revoked")
    at = at or common.now()
    token.last_used_at = at
    result = await HANDLERS[name](session, token, body, at=at)
    return out_model.model_validate(result.model_dump()).model_dump(mode="json")


async def call(token_id: uuid.UUID, name: str, arguments: dict[str, Any], *,
               at: datetime | None = None) -> dict[str, Any]:
    """Run one tool in its own transaction."""
    async with get_sessionmaker()() as session:
        try:
            out = await call_in(session, token_id, name, arguments, at=at)
        except GatewayError:
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise
        await session.commit()
        return out
