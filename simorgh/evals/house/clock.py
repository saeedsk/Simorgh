"""A clock a scenario can push forward (stage 11 item 6).

A companion arc is nine days long -- a baseline forms over a couple of
dozen turns, three quiet days follow, a check-in is or is not offered
-- and nobody will wait nine days for it. But a fake clock the event
loop does not share makes every `asyncio.sleep` in the system lie, and
a scenario that skips a week in a system whose timers all fire at once
tests a machine nobody runs.

So this skips only what a skip can honestly mean: `now()` is the wall
clock plus an offset the scenario controls. Timestamp arithmetic --
exponential decay, baselines, cooldowns, half-lives, "last heard 40
minutes ago" -- moves; waiting does not. `sleep()` is a real sleep of
the real number of seconds asked for, because the thing that asked is
usually a loop with a period, and letting it spin a week's worth of
iterations in an instant is not the day passing, it is a busy loop.

What follows from that, and is the rule for scenarios: **after a skip,
poll for the state you expect rather than waiting for a timer to
notice.** Nothing dated before the skip reappears, and nothing
scheduled inside it fires.
"""

from __future__ import annotations

import asyncio
import time


class SkippingClock:
    """Wall time plus an offset. `skip(seconds)` moves the offset."""

    def __init__(self, *, start: float | None = None) -> None:
        self._base = float(start) if start is not None else time.time()
        self._real_start = time.time()
        self.offset = 0.0

    def now(self) -> float:
        return self._base + (time.time() - self._real_start) + self.offset

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def skip(self, seconds: float) -> float:
        """Move the world's clock forward. Returns the new `now()`."""
        self.offset += float(seconds)
        return self.now()


__all__ = ["SkippingClock"]
