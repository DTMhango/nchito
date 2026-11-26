"""The "search API" connection: the key the web search source uses (DESIGN 6).

The key is Fernet-encrypted in ``Connection.secrets_enc``, returned only masked and never logged or audited
(the audit lists secret *names*). The record's config holds the provider's endpoint and response shape, so the
connection can be tested on its own; a ``web_search`` source names its connection with ``connection_id`` in its
config, else the first enabled search API connection is used.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.crypto import encrypt
from app.llm.provider_records import read_secrets
from app.models.platform import Connection, ConnectionProvider
from app.models.search import Source
from app.sources.base import HttpFetcher, SourceError
from app.sources.http import HttpxFetcher
from app.sources.web import http_url
from app.sources.web_search import PROVIDER_SHAPE, JsonSearchProvider

PROVIDER = "search_api"
CONFIG_KEYS = ("endpoint", *PROVIDER_SHAPE)
SECRET_KEYS = ("api_key",)
READS = "Sends search phrases built from your campaigns' titles and places to the search provider. Reads only " \
        "the result links."
TEST_QUERY = "jobs"

_fetcher: HttpFetcher | None = None


def set_fetcher(fetcher: HttpFetcher | None) -> None:
    """Replace the HTTP fetcher used by the connection test (tests)."""
    global _fetcher
    _fetcher = fetcher


def is_search(provider: str) -> bool:
    return provider == PROVIDER


def validate(config: dict[str, Any], secrets_in: dict[str, str], *, creating: bool) -> dict[str, Any]:
    unknown = set(config) - set(CONFIG_KEYS)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))} (the key goes in 'secrets')")
    extra = set(secrets_in) - set(SECRET_KEYS)
    if extra:
        raise ValueError(f"unknown secrets: {', '.join(sorted(extra))}")
    out = dict(config)
    if creating or "endpoint" in config:
        out["endpoint"] = http_url(str(config.get("endpoint", "")))
    if config.get("key_header") and config.get("key_param"):
        raise ValueError("give the key as a header or a query parameter, not both")
    if creating and not secrets_in.get("api_key", "").strip():
        raise ValueError("api_key is required")
    return out


async def create(session: AsyncSession, *, label: str, config: dict[str, Any], secrets: dict[str, str],
                 actor: str) -> Connection:
    clean = validate(config, secrets, creating=True)
    conn = Connection(provider=ConnectionProvider.search_api, label=label, config=clean,
                      secrets_enc=encrypt(json.dumps({"api_key": secrets["api_key"].strip()})), scopes_granted=[],
                      reads_description=READS, health="unknown", enabled=True)
    session.add(conn)
    await session.flush()
    await audit.record(session, actor=actor, action="connection.created", subject_type="connection",
                       subject_id=conn.id, detail={"provider": PROVIDER, "label": label, "secret_names": ["api_key"]})
    return conn


async def update(session: AsyncSession, conn: Connection, *, label: str | None, config: dict[str, Any] | None,
                 secrets: dict[str, str] | None, enabled: bool | None, actor: str) -> Connection:
    changed: list[str] = []
    if label is not None and label != conn.label:
        conn.label = label
        changed.append("label")
    if config is not None:
        conn.config = validate({**conn.config, **config}, {}, creating=False)
        changed.append("config")
    provided = {k: v.strip() for k, v in (secrets or {}).items() if v and v.strip()}
    if provided:
        validate({}, provided, creating=False)
        conn.secrets_enc = encrypt(json.dumps({**read_secrets(conn), **provided}))
        conn.health = "unknown"
        changed.append("secrets")
    if enabled is not None and enabled != conn.enabled:
        conn.enabled = enabled
        changed.append("enabled")
    await session.flush()
    await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                       subject_id=conn.id, detail={"changed": changed, "secret_names": sorted(provided)})
    return conn


def _provider(conn: Connection, fetcher: HttpFetcher) -> JsonSearchProvider:
    key = read_secrets(conn).get("api_key") or ""
    shape = {k: conn.config.get(k, default) for k, default in PROVIDER_SHAPE.items()}
    return JsonSearchProvider(fetcher, endpoint=str(conn.config["endpoint"]), api_key=key, **shape)


async def run_test(conn: Connection) -> tuple[bool, str]:
    """One search for a neutral phrase; the key is never shown in the result."""
    try:
        hits = await _provider(conn, _fetcher or HttpxFetcher()).search(TEST_QUERY, 1)
    except (SourceError, ValueError, KeyError) as exc:
        return False, f"the search provider refused or answered unexpectedly: {exc}"[:500]
    except Exception as exc:  # network trouble: reported, never raised
        return False, f"{type(exc).__name__}: could not reach the search provider"[:500]
    return True, f"the provider answered ({len(hits)} result{'s' if len(hits) != 1 else ''})"


async def api_key_for(session: AsyncSession, source: Source) -> str | None:
    """The key for a web search source: its ``connection_id``, else the first enabled search API connection."""
    raw = (source.config or {}).get("connection_id")
    conn: Connection | None = None
    if raw:
        try:
            conn = await session.get(Connection, uuid.UUID(str(raw)))
        except ValueError:
            conn = None
        if conn is not None and (conn.provider != ConnectionProvider.search_api or not conn.enabled):
            conn = None
    else:
        conn = await session.scalar(select(Connection).where(
            Connection.provider == ConnectionProvider.search_api, Connection.enabled.is_(True))
            .order_by(Connection.created_at).limit(1))
    return (read_secrets(conn).get("api_key") or None) if conn is not None else None
