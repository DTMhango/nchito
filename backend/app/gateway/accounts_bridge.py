"""The optional portal-accounts module (``app.apply.accounts``, another wave 3 stream), loaded lazily.

When it is in the build, sign-in style blockers are registered through it (it groups them per portal and
returns waiting tasks to the same runner on "continue") and it decides whether a job needs an account.
Without it the gateway falls back to its own grouping and the job's facets. Tests replace it with
:func:`set_module`.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

ACCOUNT_KINDS = frozenset({"sign_in", "create_account", "verification_code", "captcha", "assessment",
                           "declaration", "unsupported_form"})

_override: Any = None
_UNSET = object()


def set_module(module: Any = _UNSET) -> None:
    """Use ``module`` as the accounts module (None: act as if it is absent); no argument restores the import."""
    global _override
    _override = None if module is _UNSET else (module if module is not None else False)


def module() -> ModuleType | Any | None:
    if _override is False:
        return None
    if _override is not None:
        return _override
    try:
        return importlib.import_module("app.apply.accounts")
    except ImportError:
        return None


def has(name: str) -> bool:
    mod = module()
    return mod is not None and callable(getattr(mod, name, None))
