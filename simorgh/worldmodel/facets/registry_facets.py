"""`tools` and `user_profile` facets -- both start empty this session
(their producers, Execution's `tool.registered` and Persona's
`persona.user_model.updated`, may not exist yet in a given boot) and
fill in honestly as those events arrive. Never fabricate an entry.
"""

from __future__ import annotations


class ToolsFacet:
    name = "tools"

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    def on_registered(self, name: str, payload: dict) -> None:
        self._tools[name] = {
            "name": name, "read_only": payload.get("read_only", True),
            "reversibility": payload.get("reversibility", "read_only"),
            "provider": payload.get("provider", "builtin"), "available": True,
        }

    def on_unavailable(self, name: str, reason: str) -> None:
        if name in self._tools:
            self._tools[name]["available"] = False
            self._tools[name]["reason"] = reason

    def on_available(self, name: str) -> None:
        """A tool that was marked broken is working again.

        Without this, `available` was a one-way latch: `on_registered`
        set it True once at boot and `on_unavailable` could only ever
        set it False, so a capability Sim installed to unblock itself
        stayed "unavailable" in the Self Model for the life of the
        process. The reason goes with it -- a stale "node is not
        installed" beside a working tool is its own small lie.
        """
        entry = self._tools.get(name)
        if entry is not None and not entry.get("available", True):
            entry["available"] = True
            entry.pop("reason", None)

    def invalidate(self) -> None:
        pass

    async def get(self, args: dict) -> dict:
        return {"tools": list(self._tools.values())}


class UserProfileFacet:
    name = "user_profile"

    def __init__(self) -> None:
        self._facets: dict[str, dict] = {}

    def on_updated(self, facet: str, value, confidence: float) -> None:
        self._facets[facet] = {"value": value, "confidence": confidence}

    def invalidate(self) -> None:
        pass

    async def get(self, args: dict) -> dict:
        return {"facets": dict(self._facets)}
