"""Owner authentication: Argon2 passwords, optional TOTP, signed session cookie, login rate
limit, CSRF protection for a same-origin SPA, and runner token hashing.

CSRF model: the session cookie is httpOnly and SameSite=Lax, and every state-changing request
from a browser must come from our own origin. Browsers send ``Sec-Fetch-Site``; we accept only
``same-origin`` (and ``none``, a user-typed navigation). Older browsers fall back to ``Origin``,
which must match ``BASE_URL``, the request's own host, or ``CSRF_TRUSTED_ORIGINS``. Requests with
neither header are not from a browser and cannot carry a forged cross-site intent.
The SPA needs no token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.clock import utcnow
from app.core.config import get_config
from app.models.platform import LoginAttempt

_hasher = PasswordHasher()

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
MIN_PASSWORD_LENGTH = 12


# ----- passwords ----------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


# ----- TOTP -------------------------------------------------------------------------------


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    code = code.strip().replace(" ", "")
    return code.isdigit() and pyotp.TOTP(secret).verify(code, valid_window=1)


# ----- session cookie ---------------------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt="nchito-session")


def sign_session(session_id: str) -> str:
    return _serializer().dumps(session_id)


def unsign_session(cookie: str) -> str | None:
    max_age = int(timedelta(hours=get_config().session_max_age_hours).total_seconds())
    try:
        value = _serializer().loads(cookie, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return value if isinstance(value, str) else None


# ----- rate limit -------------------------------------------------------------------------


async def login_blocked(session: AsyncSession, ip: str) -> bool:
    cfg = get_config()
    since = utcnow() - timedelta(seconds=cfg.login_rate_limit_window_seconds)
    failures = await session.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.ip == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since
        )
    )
    return (failures or 0) >= cfg.login_rate_limit_attempts


async def note_login_attempt(session: AsyncSession, ip: str, email: str | None, success: bool) -> None:
    session.add(LoginAttempt(ip=ip, email=email, success=success))
    await session.flush()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ----- CSRF -------------------------------------------------------------------------------


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def csrf_ok(request: Request) -> bool:
    if request.method in SAFE_METHODS:
        return True
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        return True
    cfg = get_config()
    allowed = {cfg.base_origin.lower(), *(_origin_of(o) for o in cfg.csrf_trusted_origins)}
    host = request.headers.get("host")
    if host:
        allowed.add(f"{request.url.scheme}://{host}".lower())
    return _origin_of(origin) in allowed


# ----- runner tokens ----------------------------------------------------------------------

TOKEN_PREFIX = "nch_"


def new_api_token() -> tuple[str, str, str]:
    """Return (plaintext shown once, sha256 hash stored, short display prefix)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_token(raw), raw[:10]


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
