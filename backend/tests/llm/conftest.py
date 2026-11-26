"""Helpers for the AI-layer tests. No test reaches a provider: adapters are scripted."""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from app.core.db import get_sessionmaker
from app.core.settings import service as settings_service
from app.llm.ledger import Ledger
from app.llm.providers import Credentials, ProviderReply, ProviderRequest
from app.llm.service import LLMService


class ScriptedAdapter:
    def __init__(self, *replies: ProviderReply | Exception, name: str = "anthropic", billed: bool = True) -> None:
        self.name = name
        self.billed = billed
        self.replies: deque[ProviderReply | Exception] = deque(replies)
        self.requests: list[tuple[ProviderRequest, Credentials]] = []

    async def call(self, request: ProviderRequest, credentials: Credentials) -> ProviderReply:
        self.requests.append((request, credentials))
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(data: Any, input_tokens: int = 1000, output_tokens: int = 100) -> ProviderReply:
    return ProviderReply(data=data, input_tokens=input_tokens, output_tokens=output_tokens)


async def set_settings(**values: Any) -> None:
    async with get_sessionmaker()() as s:
        for key, value in values.items():
            await settings_service.set_value(s, key.replace("__", "."), value, actor="test")
        await s.commit()


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
async def anthropic_record() -> None:
    from app.llm import provider_records

    async with get_sessionmaker()() as s:
        await provider_records.create(s, provider="anthropic", label="Test", config={},
                                      secrets={"api_key": "test-key-not-real-0000"}, actor="test")
        await s.commit()


def make_service(*adapters: ScriptedAdapter, ledger: Ledger | None = None) -> LLMService:
    return LLMService(adapters={a.name: a for a in adapters}, ledger=ledger, sleep=no_sleep)


async def make_run():
    from app.models.search import Run, RunKind

    async with get_sessionmaker()() as s:
        run = Run(kind=RunKind.sweep, trigger="manual")
        s.add(run)
        await s.commit()
        return run.id
