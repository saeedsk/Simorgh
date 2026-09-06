"""Schema-version translators (docs/blueprint/03 section 8).

Adding an optional field is a minor change and needs nothing here.
Removing, renaming, or retyping a field bumps the type's
`schema_version` and requires a translator registered here for one
version back, so a consumer built against the older shape keeps
working while producers roll forward. The Bus routes an older message
through `translate()` before delivery and dead-letters anything it
cannot translate (with a `system.health` event).

The catalog is at v1 for every type, so this module is currently a
registry with no translators -- the mechanism exists before it is
needed, not after.
"""

from __future__ import annotations

from typing import Callable

from .envelope import Message
from .registry import ContractError

Translator = Callable[[dict], dict]

_TRANSLATORS: dict[tuple[str, int, int], Translator] = {}


def register(type_name: str, from_version: int, to_version: int, fn: Translator) -> None:
    if abs(to_version - from_version) != 1:
        raise ContractError("translators move exactly one version at a time; chain them")
    _TRANSLATORS[(type_name, from_version, to_version)] = fn


def can_translate(type_name: str, from_version: int, to_version: int) -> bool:
    step = 1 if to_version > from_version else -1
    v = from_version
    while v != to_version:
        if (type_name, v, v + step) not in _TRANSLATORS:
            return False
        v += step
    return True


def translate(message: Message, to_version: int) -> Message:
    """Return a copy of `message` at `to_version`, applying registered
    translators one step at a time. Identity when already there."""
    if message.schema_version == to_version:
        return message
    if not can_translate(message.type, message.schema_version, to_version):
        raise ContractError(
            f"no translator for {message.type} v{message.schema_version} -> v{to_version}"
        )
    step = 1 if to_version > message.schema_version else -1
    payload = dict(message.payload)
    v = message.schema_version
    while v != to_version:
        payload = _TRANSLATORS[(message.type, v, v + step)](payload)
        v += step
    return message.with_(schema_version=to_version, payload=payload)


def clear() -> None:
    """Test hook."""
    _TRANSLATORS.clear()


__all__ = ["Translator", "can_translate", "clear", "register", "translate"]
