"""Bus policies. `AllowAllPolicy` is the zero-config default (tests, the
`memory` floor); the Kernel installs `enforcement.ReservedTopologyPolicy`
in real runs (docs/blueprint/subsystems/01-bus.md section 3.1)."""

from __future__ import annotations

from .api import PolicyViolation  # noqa: F401 -- re-exported: the canonical home is api.py


class AllowAllPolicy:
    def check_subscribe(self, source: str, pattern: str) -> None:
        return None

    def check_publish(self, source: str, type: str, payload: dict) -> None:
        return None


__all__ = ["AllowAllPolicy", "PolicyViolation"]
