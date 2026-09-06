"""The `Facet` shape every facet module conforms to by structure
(no shared base class needed -- they already match)."""

from __future__ import annotations

from typing import Protocol


class Facet(Protocol):
    name: str

    async def get(self, args: dict) -> dict: ...

    def invalidate(self) -> None: ...
