"""FastAPI dependencies for the AI layer (tests override ``llm_service`` with scripted adapters)."""

from __future__ import annotations

from app.llm.ledger import Ledger
from app.llm.service import LLMService


def llm_service() -> LLMService:
    return LLMService()


def ledger() -> Ledger:
    return Ledger()
