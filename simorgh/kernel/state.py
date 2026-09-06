"""The system state machine (docs/blueprint/subsystems/03-kernel.md
section 5.2): `booting -> running <-> paused -> stopping -> stopped`,
plus the terminal `failed` on a boot failure. Transitions are appended
to the Ledger `system` stream *before* `system.state.changed` is
published, so a crash between the two is recovered on restart (the last
recorded state is simply re-announced -- section 4/8).

`pause`/`resume` are idempotent (pausing an already-paused system is a
no-op, not an error); `stop` while `paused` proceeds directly to
`stopping`. This machine holds no policy of its own -- it does not
decide *whether* to pause, only records that it did and tells whoever is
listening (Guardian denies from here on; the Scheduler suspends
idle/sleep ticks; Interface renders it).
"""

from __future__ import annotations

from dataclasses import dataclass

RUNNING = "running"
PAUSED = "paused"
STOPPING = "stopping"
STOPPED = "stopped"
BOOTING = "booting"
FAILED = "failed"

_VALID_STATES = frozenset({BOOTING, RUNNING, PAUSED, STOPPING, STOPPED, FAILED})


class InvalidTransition(RuntimeError):
    pass


@dataclass
class StateChange:
    state: str
    previous: str
    reason: str
    requested_by: str
    scope: str | None = None  # "all" | "autonomous" | None


class SystemStateMachine:
    def __init__(self, initial: str = BOOTING) -> None:
        if initial not in _VALID_STATES:
            raise ValueError(initial)
        self._state = initial
        self._autonomous_paused = False

    @property
    def state(self) -> str:
        return self._state

    @property
    def autonomous_paused(self) -> bool:
        """True if autonomous-only work is paused -- either because the
        whole system is paused, or because a `scope="autonomous"` pause
        is in effect while human-originated work still proceeds."""
        return self._state == PAUSED or self._autonomous_paused

    def boot_complete(self) -> StateChange:
        if self._state != BOOTING:
            raise InvalidTransition(f"boot_complete from {self._state!r}")
        previous, self._state = self._state, RUNNING
        return StateChange(RUNNING, previous, "boot complete", "kernel")

    def boot_failed(self, reason: str) -> StateChange:
        previous, self._state = self._state, FAILED
        return StateChange(FAILED, previous, reason, "kernel")

    def pause(self, *, reason: str, requested_by: str, scope: str | None = None) -> StateChange | None:
        if scope == "autonomous":
            already = self._autonomous_paused
            self._autonomous_paused = True
            if already:
                return None  # idempotent: no new event for a repeat scoped pause
            return StateChange(self._state, self._state, reason, requested_by, scope="autonomous")
        if self._state == PAUSED:
            return None  # idempotent
        if self._state not in (RUNNING,):
            raise InvalidTransition(f"pause from {self._state!r}")
        previous, self._state = self._state, PAUSED
        return StateChange(PAUSED, previous, reason, requested_by, scope="all")

    def resume(self, *, reason: str, requested_by: str, scope: str | None = None) -> StateChange | None:
        if scope == "autonomous":
            if not self._autonomous_paused:
                return None
            self._autonomous_paused = False
            return StateChange(self._state, self._state, reason, requested_by, scope="autonomous")
        if self._state != PAUSED:
            return None  # idempotent (resume while already running)
        previous, self._state = self._state, RUNNING
        return StateChange(RUNNING, previous, reason, requested_by, scope="all")

    def stop(self, *, reason: str, requested_by: str) -> StateChange:
        if self._state == STOPPED:
            return StateChange(STOPPED, STOPPED, reason, requested_by)
        previous, self._state = self._state, STOPPING
        return StateChange(STOPPING, previous, reason, requested_by)

    def stopped(self) -> StateChange:
        previous, self._state = self._state, STOPPED
        return StateChange(STOPPED, previous, "drained", "kernel")


__all__ = [
    "BOOTING", "FAILED", "InvalidTransition", "PAUSED", "RUNNING", "STOPPED", "STOPPING",
    "StateChange", "SystemStateMachine",
]
