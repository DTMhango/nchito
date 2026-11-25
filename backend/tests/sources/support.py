"""Recorded-fixture fetcher: tests never touch the network."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> Any:
    return json.loads(fixture_text(name))


class FakeFetcher:
    """Maps URL (exact, or prefix when the key ends with ``*``) to ``(status, body)``."""

    def __init__(self, routes: Mapping[str, tuple[int, str]] | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, str, Any]] = []

    def _lookup(self, url: str) -> tuple[int, str]:
        if url in self.routes:
            return self.routes[url]
        for key, value in self.routes.items():
            if key.endswith("*") and url.startswith(key[:-1]):
                return value
        raise AssertionError(f"unexpected request: {url}")

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        self.calls.append(("GET", url, None))
        return self._lookup(url)

    async def post_json(self, url: str, payload: Mapping[str, Any]) -> tuple[int, str]:
        self.calls.append(("POST", url, dict(payload)))
        return self._lookup(url)
