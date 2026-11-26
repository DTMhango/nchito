"""Platform aggregate: owner and sessions, settings, config history, audit, ledger,
connections, tokens, themes, notifications, worker heartbeat."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Entity, IdMixin, PydanticJSON, str_enum
from app.schemas.json_types import ContrastWaiver, ScoreRamp, ThemeFonts


class Owner(Base, Entity):
    """The single owner account. One row at most (enforced by a unique index on a constant)."""

    __tablename__ = "owner"

    singleton: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base, Entity):
    __tablename__ = "auth_session"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owner.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(INET)


class LoginAttempt(Base, Entity):
    __tablename__ = "login_attempt"
    __table_args__ = (Index("ix_login_attempt_ip_created", "ip", "created_at"),)

    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Setting(Base, Entity):
    """Current value of a setting that differs from (or was explicitly set over) its default."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False)


class SettingRevision(Base, Entity):
    """Append-only history of a setting's values."""

    __tablename__ = "setting_revision"
    __table_args__ = (Index("ix_setting_revision_key_version", "key", "version", unique=True),)

    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class ConfigKind(enum.StrEnum):
    guardrails = "guardrails"
    prompt = "prompt"
    rubric = "rubric"
    model_routing = "model_routing"
    automation_policy = "automation_policy"
    campaign = "campaign"
    template = "template"


class ConfigRevision(Base, Entity):
    """Versioned rules, prompts, rubrics, routing, automation policy. Rollback affects future work only."""

    __tablename__ = "config_revision"
    __table_args__ = (Index("ix_config_revision_subject", "kind", "subject_id", "version", unique=True),)

    kind: Mapped[ConfigKind] = mapped_column(str_enum(ConfigKind), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    rollback_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("config_revision.id"))
    note: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base, IdMixin):
    """Append-only. A database trigger rejects UPDATE and DELETE (see the first migration)."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_created", "created_at"),
        Index("ix_audit_event_subject", "subject_type", "subject_id"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(60))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


class LedgerKind(enum.StrEnum):
    reservation = "reservation"
    reconciliation = "reconciliation"
    release = "release"


class LedgerEntry(Base, Entity):
    """Spend ledger. Rows are never updated; a reservation is closed by a reconciliation or release row."""

    __tablename__ = "ledger_entry"
    __table_args__ = (
        Index("ix_ledger_entry_created", "created_at"),
        # A reservation is closed exactly once (reconciliation or release).
        Index("ix_ledger_entry_closes_once", "reservation_id", unique=True,
              postgresql_where=text("reservation_id IS NOT NULL")),
        Index("ix_ledger_entry_run", "run_id"),
    )

    kind: Mapped[LedgerKind] = mapped_column(str_enum(LedgerKind), nullable=False)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ledger_entry.id"))
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(128))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    agent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_task.id", ondelete="SET NULL"))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


class LlmPrice(Base, Entity):
    """Price table for the ledger's estimates and reconciliation (editable data, seeded with a dated default).

    Prices are minor currency units per million tokens. Above ``long_context_threshold`` input tokens
    the ``long_*`` prices apply when set.
    """

    __tablename__ = "llm_price"
    __table_args__ = (Index("ix_llm_price_provider_model", "provider", "model", unique=True),)

    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    input_per_mtok: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    output_per_mtok: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    cache_write_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    cache_read_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    long_context_threshold: Mapped[int | None] = mapped_column(Integer)
    long_input_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    long_output_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)


class ConnectionProvider(enum.StrEnum):
    anthropic = "anthropic"
    openai_compatible = "openai_compatible"
    gmail = "gmail"
    imap_smtp = "imap_smtp"
    gdrive = "gdrive"
    msgraph = "msgraph"
    onedrive = "onedrive"
    telegram = "telegram"
    webhook = "webhook"
    s3 = "s3"
    search_api = "search_api"  # the web search source's provider key (wave 3)


class Connection(Base, Entity):
    __tablename__ = "connection"

    provider: Mapped[ConnectionProvider] = mapped_column(str_enum(ConnectionProvider), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    secrets_enc: Mapped[str | None] = mapped_column(Text, doc="Fernet-encrypted JSON of tokens/keys")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    scopes_granted: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    reads_description: Mapped[str | None] = mapped_column(Text, doc="What the app actually reads (18.5)")
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ApiToken(Base, Entity):
    """Runner bearer tokens: stored hashed, scoped, shown once, revocable."""

    __tablename__ = "api_token"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    runner_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="pc")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(Text)


class Theme(Base, Entity):
    __tablename__ = "theme"

    slug: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fonts: Mapped[ThemeFonts] = mapped_column(PydanticJSON(ThemeFonts), nullable=False)
    radius: Mapped[int] = mapped_column(Integer, nullable=False)
    density: Mapped[str] = mapped_column(String(20), nullable=False)
    light: Mapped[dict[str, str]] = mapped_column(PydanticJSON(dict[str, str]), nullable=False)
    dark: Mapped[dict[str, str]] = mapped_column(PydanticJSON(dict[str, str]), nullable=False)
    chart: Mapped[list[str]] = mapped_column(PydanticJSON(list[str]), nullable=False)
    score: Mapped[ScoreRamp] = mapped_column(PydanticJSON(ScoreRamp), nullable=False)
    current_revision: Mapped[int | None] = mapped_column(Integer)
    contrast_waiver: Mapped[ContrastWaiver | None] = mapped_column(PydanticJSON(ContrastWaiver))


class ThemeRevision(Base, Entity):
    """One saved state of an owner theme (theme studio undo/redo). ``parent`` is the revision it was
    edited from, so undo walks back along the edit path."""

    __tablename__ = "theme_revision"
    __table_args__ = (Index("uq_theme_revision_number", "theme_id", "number", unique=True),)

    theme_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("theme.id", ondelete="CASCADE"),
                                                nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)


class Notification(Base, Entity):
    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_unread", "read_at", "created_at"),)

    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    channels_sent: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)


class WorkerHeartbeat(Base, Entity):
    __tablename__ = "worker_heartbeat"

    worker_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
