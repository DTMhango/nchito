"""Microsoft identity platform (Entra) OAuth helpers shared by Outlook and OneDrive. DESIGN.md 12, 18.5.

Pure functions: no network. Each connector sends the requests through its own injected transport and
passes the answer here. Authorization code flow with ``offline_access`` for a refresh token. Nothing
here logs or returns a token or the client secret.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
OFFLINE = "offline_access"
USER_READ = "User.Read"  # who signed in (the sending address); the usual sign-in permission
MAIL_SEND = "Mail.Send"
MAIL_READ = "Mail.Read"
FILES_APP_FOLDER = "Files.ReadWrite.AppFolder"
MAIL_SCOPES = (OFFLINE, USER_READ, MAIL_SEND, MAIL_READ)
ONEDRIVE_SCOPES = (OFFLINE, USER_READ, FILES_APP_FOLDER)
REFRESH_MARGIN = timedelta(seconds=60)


class MsAuthError(RuntimeError):
    """Microsoft refused the code or the refresh token. Messages never contain tokens."""


def authorize_url(*, tenant: str, client_id: str, redirect_uri: str, state: str, scopes: tuple[str, ...]) -> str:
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                       "response_mode": "query", "scope": " ".join(scopes), "state": state, "prompt": "consent"})
    return f"{LOGIN}/{tenant}/oauth2/v2.0/authorize?{query}"


def token_url(tenant: str) -> str:
    return f"{LOGIN}/{tenant}/oauth2/v2.0/token"


def code_form(*, client_id: str, client_secret: str, redirect_uri: str, code: str,
              scopes: tuple[str, ...]) -> dict[str, str]:
    return {"client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code", "scope": " ".join(scopes)}


def refresh_form(*, client_id: str, client_secret: str, refresh_token: str,
                 scopes: tuple[str, ...]) -> dict[str, str]:
    return {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token,
            "grant_type": "refresh_token", "scope": " ".join(scopes)}


def expiry(seconds: Any, now: datetime) -> str:
    return (now + timedelta(seconds=int(seconds or 3600))).isoformat()


def tokens_from_answer(status: int, data: Any, *, now: datetime, previous: Mapping[str, str] | None = None,
                       need_scope: str | None = None) -> dict[str, str]:
    """Turn a token endpoint answer into the stored token dict (access_token, refresh_token, expires_at, scope).

    A refresh answer may omit ``refresh_token`` (the old one stays); a first sign-in must have one."""
    body = data if isinstance(data, dict) else {}
    if status != 200 or not body.get("access_token"):
        raise MsAuthError("Microsoft refused the sign-in")
    refresh = body.get("refresh_token") or (previous or {}).get("refresh_token")
    if not refresh:
        raise MsAuthError("Microsoft returned no refresh token; reconnect and accept the consent screen")
    scope = str(body.get("scope") or (previous or {}).get("scope", ""))
    if need_scope and need_scope.lower() not in scope.lower().split():
        raise MsAuthError(f"the {need_scope} permission was not granted")
    return {"access_token": str(body["access_token"]), "refresh_token": str(refresh),
            "expires_at": expiry(body.get("expires_in"), now), "scope": scope}


def is_stale(tokens: Mapping[str, str], now: datetime) -> bool:
    expires = tokens.get("expires_at")
    if not tokens.get("access_token") or not expires:
        return True
    return datetime.fromisoformat(expires).astimezone(UTC) - now <= REFRESH_MARGIN


def scopes_granted(raw: str, wanted: tuple[str, ...]) -> list[str]:
    """The granted permissions for display; Graph answers with short names (``Mail.Send``), sometimes URLs."""
    got = [s.rsplit("/", 1)[-1] for s in raw.split() if s]
    return got or list(wanted)
