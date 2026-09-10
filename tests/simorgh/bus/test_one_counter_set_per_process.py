"""The bus's own health must be able to see a dead letter.

Each `BusClient` made its own `Metrics`, and `bus.Service` reads the
KERNEL client's -- so its `system.metrics` and its health saw only the
kernel's own traffic. An observer booted the real system, forced two
real dead letters, and watched `bus.Service.health()` report `ok` with
6 delivered while the process had actually handled 115 and
dead-lettered 2 (2026-09-10).

The dead-letter hook is worse than uncounted: `BusClient.__init__`
overwrites `backend.set_dead_letter_hook`, so whichever client was
built LAST owns it, and that is never the one being read.

The shared `TraceWriter` beside it already had exactly this shape, for
exactly this reason.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class OneCounterSetPerProcessTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_two_subsystems_built_by_one_factory_share_a_counter_set(self):
        """This is the seam: `ContextFactory.build` hands every
        subsystem its own client, and `bus.Service` reads only the
        kernel's. The shared `TraceWriter` beside it is passed the same
        way, for the same reason."""
        from simorgh.bus.factory import make_backend
        from simorgh.bus.config import Config as BusConfig
        from simorgh.bus.factory import make_client
        from simorgh.kernel.api import RuntimeConfig
        from simorgh.kernel.context import ContextFactory
        from simorgh.ledger.factory import make_ledger
        from tests.simorgh.helpers import FakeClock

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        self.addAsyncCleanup(ledger.stop)
        backend = make_backend(BusConfig(backend="memory"), clock=clock.now)
        kernel_client = make_client(backend, source="kernel", ledger=ledger, clock=clock.now)

        factory = ContextFactory(
            bus_backend=backend, ledger=ledger,
            config=LoadedConfig({"runtime": {"data_dir": tmp.name}}, None),
            secrets=EnvSecretStore({}), clock=clock,
            runtime=RuntimeConfig(data_dir=Path(tmp.name)), run_id="t",
            hmac_secret=b"secret", needs_hmac_secret=frozenset(),
            metrics=kernel_client.metrics,
        )
        first = factory.build("memory").bus
        second = factory.build("planning").bus
        self.assertIs(first.metrics, second.metrics)
        self.assertIs(first.metrics, kernel_client.metrics,
                      "a subsystem counting into its own set is invisible to bus health")

    async def test_the_counters_the_bus_reads_see_real_traffic(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp.name}}, None),
                        secrets=EnvSecretStore({}))
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        self.assertGreater(kernel.bus.metrics.counters.get("published", 0), 0,
                           "a booted system publishes; the counter the bus reads must see it")


if __name__ == "__main__":
    unittest.main()
