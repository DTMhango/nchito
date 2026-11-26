"""Channel registry (CONTRACTS.md 9): channels register by name; nothing imports a concrete channel.

A channel is built per use by a factory that receives the database session (a channel may need the
connected mailbox or the file store). Built-in channels are registered lazily by dotted path, so
importing this module imports no channel. Another stream registers its channel in a few lines, for
example the email channel (``app/apply/channels/email.py``)::

    from app.apply.channels import registry

    async def _email_channel(session):
        from app.apply.channels.email import EmailChannel
        mailbox = ...            # the connected mailbox for this session
        loader = ...             # loads attachment bytes by PacketFile
        return EmailChannel(mailbox, loader, hasher=registry.packet_hash)

    registry.register("email", _email_channel)

or, with a module-level factory, ``registry.register_lazy("email", "app.apply.channels.email:factory")``
(the built-in registration: the connected mailbox, attachments from the default ``FileStore``).

``packet_hash`` is the one packet hash (``apply.packets.content_hash``): sha256 of the canonical JSON of
``PacketContents`` (``model_dump(mode="json")``, sorted keys, ``(",", ":")`` separators,
``ensure_ascii=False``, UTF-8). A channel that checks the packet it was handed must use it.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.apply.channels.base import Channel
from app.apply.packets import content_hash as packet_hash

ChannelFactory = Callable[[AsyncSession], Awaitable[Channel]]

_FACTORIES: dict[str, ChannelFactory] = {}
# Built-in channels. ``unregister`` of a built-in puts its default back (tests replace and restore them).
_BUILTIN: dict[str, str] = {"manual": "app.apply.channels.manual:factory", "email": "app.apply.channels.email:factory",
                            "browser": "app.apply.channels.browser:factory"}
_LAZY: dict[str, str] = dict(_BUILTIN)

__all__ = ["ChannelFactory", "ChannelUnavailable", "available", "get", "is_available", "packet_hash", "register",
           "register_lazy", "unregister"]


class ChannelUnavailable(Exception):
    """No channel of that name is registered (or its factory could not build one)."""


def register(name: str, factory: ChannelFactory, *, replace: bool = False) -> None:
    if not replace and name in _FACTORIES:
        raise ValueError(f"channel {name!r} is already registered")
    _FACTORIES[name] = factory
    _LAZY.pop(name, None)


def register_lazy(name: str, target: str) -> None:
    """Register ``module:attr`` (an async factory) without importing it yet."""
    if ":" not in target:
        raise ValueError("target must be 'module:attr'")
    _LAZY[name] = target


def unregister(name: str) -> None:
    """Remove a registration; a built-in channel falls back to its default factory."""
    _FACTORIES.pop(name, None)
    _LAZY.pop(name, None)
    if name in _BUILTIN:
        _LAZY[name] = _BUILTIN[name]


def available() -> list[str]:
    return sorted(set(_FACTORIES) | set(_LAZY))


def is_available(name: str) -> bool:
    return name in _FACTORIES or name in _LAZY


def _resolve(name: str) -> ChannelFactory:
    if name in _FACTORIES:
        return _FACTORIES[name]
    target = _LAZY.get(name)
    if target is None:
        raise ChannelUnavailable(f"no {name} channel is available in this build")
    module, attr = target.split(":", 1)
    factory: ChannelFactory = getattr(importlib.import_module(module), attr)
    _FACTORIES[name] = factory
    return factory


async def get(session: AsyncSession, name: str) -> Channel:
    channel = await _resolve(name)(session)
    if channel.name != name:
        raise ChannelUnavailable(f"the {name} factory built a {channel.name} channel")
    return channel
