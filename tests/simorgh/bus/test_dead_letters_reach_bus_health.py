"""A dead letter is counted where the bus's own health looks.

`BusClient.__init__` calls `backend.set_dead_letter_hook(self._on_dead_letter)`,
so the LAST client built owns the hook -- and that is never the Kernel's,
whose client `bus.Service` reads. On a real boot the owner is
`orchestration` (checked live, 2026-09-10, 16 subsystems). The only
reason `bus.Service.health()` can see a dead letter at all is that every
client shares ONE `Metrics`; the hook's owner is arbitrary.

Live check on a booted Kernel with `[bus] max_deliveries = 2` and a
handler that always raises: two real dead letters, `kernel.bus.metrics`
read `dead=2` / `delivered=171`, and `bus.Service.health()` returned
`degraded: dead letters this window: 2`. Before the shared counter set
the same run reported `ok` with only the kernel client's own handful of
deliveries.

The second test pins the seam itself: hand one client its own counter
set -- what `ContextFactory` does when it is built without `metrics=`,
as `KernelWorker.boot` builds it -- and the dead letter lands in a set
nothing reads, which is exactly the bug.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.metrics import Metrics
from simorgh.bus.service import Service
from simorgh.contracts.envelope import Message


async def _dead_letter_through(subscriber, publisher) -> None:
    """One real dead letter: a handler that always raises, retried to
    `max_deliveries` (1 here), on a grouped subscription so the backend
    nacks rather than drops."""

    async def boom(_message: Message) -> None:
        raise RuntimeError("always fails")

    await subscriber.subscribe("percept.text.received", boom, group="deadtest", max_inflight=1)
    await publisher.publish(publisher.new(
        "percept.text.received", {"text": "x", "channel": "cli", "session_id": "s1"}))


class DeadLettersReachBusHealthTestCase(unittest.IsolatedAsyncioTestCase):
    async def _backend(self):
        backend = make_backend(BusConfig(backend="memory", max_deliveries=1),
                               on_handler_error=lambda *_: None)
        await backend.start()
        self.addAsyncCleanup(backend.stop)
        return backend

    async def _wait_for_dead(self, metrics: Metrics) -> int:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if metrics.counters.get("dead", 0):
                break
        return metrics.counters.get("dead", 0)

    async def test_the_health_the_bus_reports_sees_another_subsystems_dead_letter(self):
        backend = await self._backend()
        shared = Metrics()
        kernel = make_client(backend, source="kernel", metrics=shared)
        # Built after the kernel's, so this one owns the dead-letter hook.
        subsystem = make_client(backend, source="planning", metrics=shared)
        service = Service(kernel, metrics_interval=0)

        await _dead_letter_through(subsystem, kernel)
        self.assertEqual(await self._wait_for_dead(shared), 1)

        health = await service.health()
        self.assertEqual(health.status, "degraded", health.detail)
        self.assertIn("dead letters", health.detail)

    async def test_a_client_with_its_own_counter_set_is_invisible_to_that_health(self):
        backend = await self._backend()
        kernel = make_client(backend, source="kernel", metrics=Metrics())
        own = make_client(backend, source="planning")  # its own Metrics: the seam
        service = Service(kernel, metrics_interval=0)

        await _dead_letter_through(own, kernel)
        self.assertEqual(await self._wait_for_dead(own.metrics), 1,
                         "the dead letter happened -- it just landed somewhere else")
        self.assertEqual(kernel.metrics.counters.get("dead", 0), 0)
        self.assertEqual((await service.health()).status, "ok",
                         "this is the bug the shared counter set closes; if this ever "
                         "reports degraded, the hook stopped being last-client-wins")


if __name__ == "__main__":
    unittest.main()
