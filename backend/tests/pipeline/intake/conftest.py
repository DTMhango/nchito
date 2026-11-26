from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from app.core.clock import FakeClock
from app.pipeline import orchestrator
from tests.pipeline.intake.fakes import FakeLLMClient, ScriptedConnector

NOW = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)


class Rig:
    """The orchestrator's dependencies, wired to doubles."""

    def __init__(self) -> None:
        self.clock = FakeClock(NOW)
        self.connectors: dict[str, ScriptedConnector] = {}
        self.llm = FakeLLMClient()
        self.scored: list[tuple[object, list]] = []

    def connector(self, name: str, **kwargs) -> ScriptedConnector:
        self.connectors[name] = ScriptedConnector(**kwargs)
        return self.connectors[name]

    async def llm_factory(self, session):
        return self.llm


@pytest.fixture
def rig() -> Iterator[Rig]:
    r = Rig()
    orchestrator.reset_deps()
    orchestrator.configure(source_factory=lambda source: r.connectors[source.name], clock=r.clock,
                           llm_factory=r.llm_factory)

    async def hook(run, ids):
        r.scored.append((run, ids))

    orchestrator.register_score_hook(hook)
    yield r
    orchestrator.reset_deps()
    orchestrator.reset_score_hook()


@pytest.fixture(autouse=True)
def _handlers():
    from app.models.search import RunKind
    from app.pipeline import runs

    orchestrator.install()
    yield
    for kind in (RunKind.sweep, RunKind.expiry_check, RunKind.retention):
        runs.unregister(kind)
