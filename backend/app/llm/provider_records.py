"""LLM provider records (``Connection`` rows for ``anthropic`` and ``openai_compatible``).

Keys are encrypted at rest (``app.core.crypto``), returned only masked, never logged or audited
(audit detail lists which secret names changed, never values).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.crypto import decrypt, encrypt, mask
from app.llm.client import LLMConfigError
from app.llm.providers import Credentials
from app.models.platform import Connection, ConnectionProvider

LLM_PROVIDERS = frozenset({"anthropic", "openai_compatible"})
NON_SECRET_CONFIG = ("base_url", "json_mode", "test_model")


def is_llm(provider: str) -> bool:
    return provider in LLM_PROVIDERS


def read_secrets(conn: Connection) -> dict[str, str]:
    return json.loads(decrypt(conn.secrets_enc)) if conn.secrets_enc else {}


def masked_secrets(conn: Connection) -> dict[str, str]:
    return {k: mask(v) for k, v in read_secrets(conn).items()}


def validate_config(provider: str, config: dict[str, Any]) -> dict[str, Any]:
    unknown = set(config) - set(NON_SECRET_CONFIG)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))} (secrets go in 'secrets')")
    base_url = config.get("base_url")
    if base_url is not None and not str(base_url).startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    if provider == "openai_compatible" and not base_url:
        raise ValueError("an OpenAI-compatible provider needs a base_url")
    if config.get("json_mode", "json_schema") not in ("json_schema", "json_object", "none"):
        raise ValueError("json_mode must be json_schema, json_object or none")
    return dict(config)


async def create(session: AsyncSession, *, provider: str, label: str, config: dict[str, Any],
                 secrets: dict[str, str], actor: str) -> Connection:
    conn = Connection(provider=ConnectionProvider(provider), label=label, config=validate_config(provider, config),
                      secrets_enc=encrypt(json.dumps(secrets)) if secrets else None, scopes_granted=[],
                      reads_description="Sends prompts built by Nchito; reads nothing from your account.",
                      health="unknown", enabled=True)
    session.add(conn)
    await session.flush()
    await audit.record(session, actor=actor, action="connection.created", subject_type="connection",
                       subject_id=conn.id, detail={"provider": provider, "label": label,
                                                   "secret_names": sorted(secrets)})
    return conn


async def update(session: AsyncSession, conn: Connection, *, label: str | None, config: dict[str, Any] | None,
                 secrets: dict[str, str] | None, enabled: bool | None, actor: str) -> Connection:
    changed: list[str] = []
    if label is not None and label != conn.label:
        conn.label, changed = label, [*changed, "label"]
    if config is not None:
        conn.config, changed = validate_config(conn.provider.value, config), [*changed, "config"]
    if secrets is not None:
        merged = {**read_secrets(conn), **{k: v for k, v in secrets.items() if v}}
        conn.secrets_enc = encrypt(json.dumps(merged)) if merged else None
        conn.health = "unknown"
        changed.append("secrets")
    if enabled is not None and enabled != conn.enabled:
        conn.enabled, changed = enabled, [*changed, "enabled"]
    await session.flush()
    await audit.record(session, actor=actor, action="connection.updated", subject_type="connection",
                       subject_id=conn.id, detail={"changed": changed,
                                                   "secret_names": sorted(secrets or {})})
    return conn


async def credentials_for(session: AsyncSession, provider: str) -> tuple[Credentials, uuid.UUID | None]:
    if provider == "claude_cli":
        return Credentials(), None
    conn = await session.scalar(select(Connection).where(
        Connection.provider == ConnectionProvider(provider), Connection.enabled.is_(True)
    ).order_by(Connection.created_at).limit(1))
    if conn is None:
        raise LLMConfigError(f"no enabled {provider} provider: add one in Settings > AI")
    return credentials_of(conn), conn.id


def credentials_of(conn: Connection) -> Credentials:
    secrets = read_secrets(conn)
    options = {k: v for k, v in conn.config.items() if k != "base_url"}
    return Credentials(api_key=secrets.get("api_key"), base_url=conn.config.get("base_url"), options=options)
