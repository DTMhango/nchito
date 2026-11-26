"""Deployment configuration, read from the environment.

Business choices live in the settings registry (``app.core.settings.registry``); this module
holds only deployment choices: where the database is, secrets, base URL and similar.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", description="development | production | test")
    database_url: str = Field(
        default="postgresql+asyncpg://nchito:nchito@localhost:5432/nchito",
        description="SQLAlchemy URL; postgres:// and postgresql:// are normalised to asyncpg.",
    )
    secret_key: str = Field(default="dev-only-change-me", description="Signs session cookies.")
    encryption_key: str = Field(
        default="",
        description="Fernet key for secrets at rest. Required outside development.",
    )
    base_url: str = Field(default="http://localhost:8000")
    app_name: str = Field(default="Nchito", description="Default app name; the UI setting overrides it.")
    files_dir: Path = Field(default=Path("./data/files"))
    backup_dir: Path = Field(default=Path("./data/backups"), description="Where backups are written (BACKUP_DIR).")
    pg_bin_dir: Path | None = Field(default=None, description="Folder holding pg_dump and pg_restore, if not on PATH.")
    spa_dir: Path = Field(default=Path("/app/static"), description="Built SPA served at / when present.")
    csrf_trusted_origins: list[str] = Field(default_factory=list)

    session_cookie_name: str = "nchito_session"
    session_max_age_hours: int = Field(default=336, ge=1, le=24 * 90)
    session_cookie_secure: bool | None = Field(
        default=None, description="Defaults to true when BASE_URL is https."
    )
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_window_seconds: int = Field(default=900, ge=10, le=86400)

    worker_heartbeat_seconds: int = Field(default=30, ge=5, le=600)
    worker_stale_after_seconds: int = Field(default=180, ge=15, le=3600)
    scheduler_tick_seconds: int = Field(default=60, ge=10, le=600)

    google_oauth_client_id: str | None = Field(default=None, description="Google OAuth client id (Gmail and Drive).")
    google_oauth_client_secret: str | None = Field(default=None,
                                                   description="Google OAuth client secret (Gmail and Drive).")

    ms_oauth_client_id: str | None = Field(default=None,
                                           description="Microsoft Entra app client id (Outlook, OneDrive).")
    ms_oauth_client_secret: str | None = Field(default=None,
                                               description="Microsoft Entra app client secret (Outlook, OneDrive).")
    ms_oauth_tenant: str = Field(default="common", description="Entra tenant: common, consumers, organizations or "
                                                               "a tenant id.")

    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        for prefix in ("postgres://", "postgresql://", "postgresql+psycopg://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    @field_validator("csrf_trusted_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.base_url.startswith("https://")

    @property
    def base_origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def libpq_url(self) -> str:
        """Plain libpq URL (for psycopg / procrastinate / pg_dump)."""
        return "postgresql://" + self.database_url.split("://", 1)[1]


@lru_cache
def get_config() -> EnvConfig:
    return EnvConfig()
