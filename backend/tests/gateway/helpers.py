"""Builders for the gateway tests (invented employers, example.com addresses only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.apply import approval, packets
from app.core.db import get_sessionmaker
from app.gateway import auth, service, tasks
from app.gateway.common import GatewayError
from app.models.applications import AgentTask, Application
from tests.apply.helpers import browser_draft, setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW

ALL_SCOPES = ["gateway:tasks", "gateway:packets", "gateway:permits", "gateway:sweep"]


@dataclass
class World:
    app_id: uuid.UUID
    job_id: uuid.UUID
    runner_a: uuid.UUID
    runner_b: uuid.UUID
    secret_a: str


def maker():
    return get_sessionmaker()


async def make_token(name: str, *, kind: str = "pc", scopes: list[str] | None = None) -> tuple[uuid.UUID, str]:
    async with maker()() as s:
        made = await auth.create(s, name=name, runner_kind=kind, scopes=scopes or ALL_SCOPES, by="owner")
        await s.commit()
        return made.row.id, made.secret


async def approved_app(*, employer: str = "Acme Example", draft: packets.PacketDraft | None = None,
                       hand_out: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker()() as s:
        campaign = await setup_campaign(s)
        job, app = await setup_app(s, campaign, employer=employer, now=NOW)
        built = await packets.build(s, app, draft or browser_draft(), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="browser", actor="owner", now=NOW)
        if hand_out:
            assert await tasks.enqueue_apply(s, app, at=NOW) is not None
        await s.commit()
        return app.id, job.id


async def world() -> World:
    app_id, job_id = await approved_app()
    a, secret = await make_token("pc-a")
    b, _ = await make_token("pc-b")
    return World(app_id, job_id, a, b, secret)


async def call(runner: uuid.UUID, name: str, **args: Any) -> dict[str, Any]:
    return await service.call(runner, name, args)


async def refused(runner: uuid.UUID, name: str, **args: Any) -> GatewayError:
    try:
        await service.call(runner, name, args)
    except GatewayError as exc:
        return exc
    raise AssertionError(f"{name} was not refused")


async def load(model: Any, ident: uuid.UUID) -> Any:
    async with maker()() as s:
        return await s.get(model, ident)


async def task_of(app_id: uuid.UUID) -> AgentTask:
    async with maker()() as s:
        return (await s.scalars(select(AgentTask).where(AgentTask.application_id == app_id)
                                .order_by(AgentTask.created_at.desc()))).first()


async def stage(app_id: uuid.UUID) -> str:
    return (await load(Application, app_id)).stage.value


ENTERED = [{"question": "Notice period", "value": "One month"}]
URL = "https://boards.greenhouse.io/acme/jobs/1"


async def permit(runner: uuid.UUID, task_id: str, answers: list[dict[str, str]] | None = None,
                 url: str = URL) -> dict[str, Any]:
    return await call(runner, "request_submit_permit", task_id=task_id, summary="ready to submit",
                      entered_answers=ENTERED if answers is None else answers, attached_files_sha256=[],
                      current_url=url)
