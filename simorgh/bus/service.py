"""`Service(Subsystem)` for the bus (docs/blueprint/subsystems/01-bus.md
section 5.7): the Kernel constructs the backend and the clients *before*
any subsystem, so this Service does not create the bus -- it owns the
bus's own health and metrics reporting and its orderly drain on stop."""

from __future__ import annotations

import asyncio

from simorgh.contracts import topics
from simorgh.contracts.protocols import Context, Health

from .client import BusClient

VERSION = "0.1.0"


class Service:
    name = "bus"
    version = VERSION
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = (topics.SYSTEM_HEALTH, topics.SYSTEM_METRICS)

    def __init__(self, client: BusClient, *, metrics_interval: float = 15.0) -> None:
        self._client = client
        self._interval = metrics_interval
        self._ticker: asyncio.Task | None = None
        self._last_dead = 0
        self._backend_errors = 0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        if self._ticker is None and self._interval > 0:
            self._ticker = asyncio.create_task(self._metrics_loop(), name="bus-metrics")

    async def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            try:
                await self._ticker
            except asyncio.CancelledError:
                pass
            self._ticker = None

    async def _metrics_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._client.emit_metrics()
            except Exception:  # noqa: BLE001
                self._backend_errors += 1

    async def health(self) -> Health:
        dead = self._client.metrics.counters.get("dead", 0)
        degraded_trace = self._client.trace.degraded
        if self._backend_errors:
            return Health.down(f"bus backend errors: {self._backend_errors}")
        if dead > self._last_dead:
            self._last_dead = dead
            return Health.degraded(f"dead letters this window: {dead}")
        if degraded_trace:
            return Health.degraded("trace writer buffering: ledger unavailable")
        return Health.ok()


__all__ = ["Service", "VERSION"]
