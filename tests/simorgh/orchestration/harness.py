"""A minimal, self-contained bus+ledger harness for `orchestration`
tests -- built directly on the real memory backends (`simorgh.bus`/
`simorgh.ledger` factories), not on another package's own test harness,
so this suite never breaks when a sibling track's test internals change.
"""

from __future__ import annotations

import asyncio
import functools

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend as make_bus_backend, make_client as make_bus_client
from simorgh.ledger.backends.memory import InMemoryBackend as LedgerMemoryBackend
from simorgh.ledger.client import LedgerClient

from tests.simorgh.helpers import FakeClock


def run(coro_fn):
    @functools.wraps(coro_fn)
    def wrapper(self, *a, **kw):
        return asyncio.run(coro_fn(self, *a, **kw))

    return wrapper


class Harness:
    """One shared in-memory bus backend + ledger; `.client(name)` hands
    out a per-subsystem `BusClient`, matching how the Kernel does it."""

    def __init__(self, *, clock: FakeClock | None = None) -> None:
        self.clock = clock or FakeClock()
        self._bus_backend = make_bus_backend(BusConfig(max_deliveries=3, metrics_interval_seconds=0), clock=self.clock)
        self.ledger = LedgerClient(LedgerMemoryBackend(), clock=self.clock)  # ledger wants a Clock (.now()); FakeClock has one
        self._clients: dict[str, object] = {}

    async def __aenter__(self) -> "Harness":
        await self.ledger.start()
        return self

    async def __aexit__(self, *exc) -> None:
        pass

    def client(self, source: str):
        if source not in self._clients:
            self._clients[source] = make_bus_client(
                self._bus_backend, source=source, config=BusConfig(max_deliveries=3, metrics_interval_seconds=0),
                ledger=self.ledger, clock=self.clock.now,
            )
        return self._clients[source]

    async def pump(self, n: int = 5, *, real_delay: float = 0.0) -> None:
        """Yield the loop `n` times. A handler dispatched via a bus
        subscription runs as a *detached* task (spawned by the backend's
        dispatch loop, not awaited by the test) -- so if it hits a real
        `asyncio.wait_for` timeout (e.g. Assembler's degrade-on-timeout,
        03 section 9), only real wall-clock sleeps let that timer fire;
        `sleep(0)` alone just yields without advancing real time.
        """
        for _ in range(n):
            await asyncio.sleep(real_delay)
