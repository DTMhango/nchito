"""Builders for the follow-up tests: an application already sent by email (through the real packet, permit and
dispatch path with a fake channel), invented employers and example.com addresses only."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.apply import approval, dispatch, packets
from app.apply.channels import registry
from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.llm.fake import FakeLLMClient
from app.models.applications import Application, DispatchAttempt, MailClassification, MailThread
from app.models.followups import OutboundMessage
from tests.apply.fakes import FakeChannel
from tests.apply.helpers import email_draft, setup_app, setup_campaign
from tests.pipeline.matching.helpers import NOW
from tests.tailoring.helpers import add_fact

AFTER_DELAY = NOW + timedelta(minutes=11)
SENT_TO = "jobs@acme.example.com"
RECRUITER = "recruiter@acme.example.com"


def maker():
    return get_sessionmaker()


@pytest.fixture
def channel():
    fake = FakeChannel(hasher=registry.packet_hash)

    async def factory(session):
        return fake

    registry.register("email", factory, replace=True)
    yield fake
    registry.unregister("email")


def reply(*texts: str | tuple[str, list[str]], questions: list[str] | None = None) -> dict[str, Any]:
    paragraphs = [{"text": t, "fact_ids": []} if isinstance(t, str) else {"text": t[0], "fact_ids": t[1]}
                  for t in texts]
    return {"paragraphs": paragraphs, "questions_for_owner": questions or []}


PLAIN = reply("Dear hiring team,", "I wanted to ask whether there is any news on my application for the Data "
              "Analyst role.", "Kind regards,")


def llm(*replies: dict[str, Any]) -> FakeLLMClient:
    fake = FakeLLMClient()
    fake.script("followup", *replies)
    fake.script("claim_check", *({"flags": []} for _ in range(20)))
    return fake


async def sent_app(*, employer: str = "Acme Example") -> uuid.UUID:
    """An application that went out by email to ``SENT_TO`` and is now ``submitted``."""
    async with maker()() as s:
        campaign = await setup_campaign(s)
        _, app = await setup_app(s, campaign, employer=employer, now=NOW)
        await add_fact(s, "F-1", "Cut monthly reporting time by 40% by automating the sales pack.")
        built = await packets.build(s, app, email_draft(), actor="owner", now=NOW)
        await approval.approve(s, app, packet_version=built.packet.version, packet_hash=built.packet.content_hash,
                               channel="email", actor="owner", now=NOW)
        result = await dispatch.queue(s, app.id, now=NOW)
        assert result.queued, result.reason
        await s.commit()
        attempt_id = result.attempt.id
    async with maker()() as s:
        status = await dispatch.run(s, attempt_id, now=AFTER_DELAY)
        assert status is not None and status.value == "sent"
    return app.id


async def link_thread(app_id: uuid.UUID, *, messages: int = 1, sender: str = RECRUITER,
                      subject: str = "Re: Application: Data Analyst") -> uuid.UUID:
    async with maker()() as s:
        t = MailThread(provider_thread_id=f"thread-{uuid.uuid4().hex[:6]}", application_id=app_id, subject=subject,
                       provider_message_ids=[f"m{i}" for i in range(messages)], sender=sender,
                       classification=MailClassification.other, last_message_at=AFTER_DELAY + timedelta(hours=1))
        s.add(t)
        await s.commit()
        return t.id


async def set_values(**values: Any) -> None:
    async with maker()() as s:
        for key, value in values.items():
            await settings_service.set_value(s, key.replace("__", "."), value, actor="test")
        await s.commit()


async def load(model, ident):
    async with maker()() as s:
        return await s.get(model, ident)


async def message_attempts(msg_id: uuid.UUID) -> list[DispatchAttempt]:
    async with maker()() as s:
        msg = await s.get(OutboundMessage, msg_id)
        if msg is None or msg.packet_id is None:
            return []
        return list((await s.scalars(select(DispatchAttempt).where(DispatchAttempt.packet_id == msg.packet_id)
                                     .order_by(DispatchAttempt.created_at))).all())


async def app_row(app_id: uuid.UUID) -> Application:
    return await load(Application, app_id)
