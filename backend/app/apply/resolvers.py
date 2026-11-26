"""Resolvers for proposal pending actions raised by other streams (``detail.kind``).

When the owner approves a pending action whose ``detail["kind"]`` has a resolver, the resolver applies the
proposal instead of the packet approval. Resolvers register by kind; known kinds are registered lazily by
dotted path, so this module imports none of them (the mail module may be absent from a build)::

    resolvers.register("my_kind", async_fn)            # async fn(session, action, *, actor) -> None

A kind whose module cannot be imported is reported as unavailable (the action stays open).
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import PendingAction

Resolver = Callable[..., Awaitable[Any]]

_RESOLVERS: dict[str, Resolver] = {}
_LAZY: dict[str, str] = {"mail_stage_proposal": "app.connect.mail_sync:apply_proposal"}


class ResolverUnavailable(Exception):
    pass


def register(kind: str, resolver: Resolver) -> None:
    _RESOLVERS[kind] = resolver
    _LAZY.pop(kind, None)


def register_lazy(kind: str, target: str) -> None:
    if ":" not in target:
        raise ValueError("target must be 'module:attr'")
    _LAZY[kind] = target


def unregister(kind: str) -> None:
    _RESOLVERS.pop(kind, None)
    _LAZY.pop(kind, None)


def kind_of(action: PendingAction) -> str | None:
    kind = (action.detail or {}).get("kind")
    return kind if isinstance(kind, str) else None


def handles(action: PendingAction) -> bool:
    kind = kind_of(action)
    return kind is not None and (kind in _RESOLVERS or kind in _LAZY)


def _resolve(kind: str) -> Resolver:
    if kind in _RESOLVERS:
        return _RESOLVERS[kind]
    target = _LAZY.get(kind)
    if target is None:
        raise ResolverUnavailable(f"no resolver for {kind!r}")
    module, attr = target.split(":", 1)
    try:
        resolver: Resolver = getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as exc:
        raise ResolverUnavailable(f"{kind!r} proposals cannot be applied in this build ({target})") from exc
    _RESOLVERS[kind] = resolver
    return resolver


async def apply(session: AsyncSession, action: PendingAction, *, actor: str) -> None:
    kind = kind_of(action)
    if kind is None:
        raise ResolverUnavailable("this action has no proposal kind")
    await _resolve(kind)(session, action, actor=actor)
