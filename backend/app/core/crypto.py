"""Secrets at rest: Fernet with ``ENCRYPTION_KEY`` from env.

The key is never stored in the database or in backups. Losing it makes stored provider
tokens unreadable (they must be reconnected), which is the intended failure mode.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_config


class CryptoError(RuntimeError):
    pass


def _fernet() -> Fernet:
    cfg = get_config()
    key = cfg.encryption_key
    if not key:
        if cfg.is_production:
            raise CryptoError("ENCRYPTION_KEY is required in production")
        # Development and tests only: derive a stable key from SECRET_KEY.
        key = base64.urlsafe_b64encode(hashlib.sha256(cfg.secret_key.encode()).digest()).decode()
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise CryptoError("ENCRYPTION_KEY is not a valid Fernet key") from exc


def fernet() -> Fernet:
    """The configured Fernet, for streaming encryption of large payloads (backups)."""
    return _fernet()


def generate_key() -> str:
    return Fernet.generate_key().decode()


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError("cannot decrypt: wrong ENCRYPTION_KEY or corrupted value") from exc


def mask(secret: str, keep: int = 4) -> str:
    """For display: never show more than the last ``keep`` characters."""
    if len(secret) <= keep:
        return "*" * len(secret)
    return "*" * 8 + secret[-keep:]
