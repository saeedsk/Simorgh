"""Per-backend test harness: builds a backend + clients for `memory` and
`sqlite` from the same code so the parity/property suites run once per
backend (docs/blueprint/subsystems/01-bus.md section 9)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import tempfile
from pathlib import Path

from simorgh.bus.backends.memory import InMemoryBackend
from simorgh.bus.backends.sqlite import SqliteBackend
from simorgh.bus.client import BusClient
from simorgh.bus.config import Config

from tests.simorgh.helpers import FakeClock

from .fakes import FakeLedger

BACKENDS = ("memory", "sqlite")


def run(coro_fn):
    """Decorator: run an `async def test_*(self)` under a fresh event loop."""

    @functools.wraps(coro_fn)
    def wrapper(self, *a, **kw):
        return asyncio.run(coro_fn(self, *a, **kw))

    return wrapper


class Harness:
    def __init__(self, backend_name: str, *, clock: FakeClock | None = None, config: Config | None = None,
                 ledger: FakeLedger | None = None, poll_ms: int = 5) -> None:
        self.name = backend_name
        self.clock = clock or FakeClock()
        self.config = config or Config(max_deliveries=3, handler_timeout_seconds=2.0, metrics_interval_seconds=0)
        self.ledger = ledger if ledger is not None else FakeLedger()
        self._tmp: tempfile.TemporaryDirectory | None = None
        self.expired: list = []
        self.errors: list = []
        if backend_name == "memory":
            self.backend = InMemoryBackend(clock=self.clock, max_deliveries=self.config.max_deliveries,
                                           handler_timeout=self.config.handler_timeout_seconds,
                                           on_expired=self.expired.append, on_handler_error=lambda m, e: self.errors.append((m, e)))
        elif backend_name == "sqlite":
            self._tmp = tempfile.TemporaryDirectory()
            self.path = Path(self._tmp.name) / "bus.sqlite"
            self.backend = SqliteBackend(self.path, clock=self.clock, max_deliveries=self.config.max_deliveries,
                                         lease_seconds=self.config.default_lease_seconds, poll_interval_ms=poll_ms,
                                         on_expired=self.expired.append, on_handler_error=lambda m, e: self.errors.append((m, e)))
        else:
            raise ValueError(backend_name)
        self.clients: dict[str, BusClient] = {}

    def client(self, source: str, **kw) -> BusClient:
        if source not in self.clients:
            self.clients[source] = BusClient(self.backend, source=source, ledger=self.ledger, clock=self.clock,
                                             config=self.config, **kw)
        return self.clients[source]

    async def __aenter__(self) -> "Harness":
        await self.backend.start()
        for c in self.clients.values():
            await c.trace.start()
        return self

    async def __aexit__(self, *exc) -> None:
        for c in self.clients.values():
            with contextlib.suppress(Exception):
                await c.trace.stop()
        with contextlib.suppress(Exception):
            await self.backend.stop()
        if self._tmp is not None:
            self._tmp.cleanup()

    async def settle(self, seconds: float = 0.08) -> None:
        end = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < end:
            await asyncio.sleep(0.005)


def for_each_backend(test):
    """Run one async test body once per backend; the body receives the Harness."""

    @functools.wraps(test)
    def wrapper(self):
        for name in BACKENDS:
            with self.subTest(backend=name):
                async def body():
                    async with Harness(name) as h:
                        await test(self, h)
                asyncio.run(body())

    return wrapper
