"""Phase 0 acceptance, Kernel side (docs/blueprint/subsystems/03-kernel.md
section 5.1 / 04 section 3): unlike `test_bus_two_toy_subsystems.py` (which
builds its own bus/ledger/Context by hand), this proves the Kernel's own
composition root -- `registry.build_factories` -> `ContextFactory` ->
`Supervisor.start_layer` -- actually boots two toy subsystems in the real
layer order, hands them a real `Context`, waits for layer N's health
before starting layer N+1, and tears them down cleanly on shutdown.

Layer 1 (`bus`, `ledger`) is real Phase 0 code; layer 2's `cognition` and
`memory` toys stand in for subsystems that do not exist yet -- injected
by patching `simorgh.kernel.service.build_factories`, the one seam the
registry docstring names for exactly this ("a layer whose names are not
yet in FACTORIES is skipped... adding Phase 1+ subsystems is a one-line
FACTORIES entry")."""

import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from tests.simorgh.helpers import FakeClock, make_message

# A real catalog type stands in for a "toy.ping" -- the bus validates every
# publish against the contracts registry, so a made-up type is rejected
# before it ever reaches a handler. `percept.text.received` is unrestricted
# (open to any publisher/subscriber) and carries no meaning here beyond
# "a message that made it through a real Context's real BusClient."
_TOY_EVENT = topics.PERCEPT_TEXT_RECEIVED


class _ToyCognition:
    name = "cognition"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self, order: list[str]) -> None:
        self._order = order

    async def start(self, ctx) -> None:
        self._order.append("cognition.start")
        self.ctx = ctx
        self.received: list[Message] = []
        self._sub = await ctx.bus.subscribe(_TOY_EVENT, self._on_ping)

    async def _on_ping(self, message: Message) -> None:
        self.received.append(message)

    async def stop(self) -> None:
        self._order.append("cognition.stop")
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()


class _ToyMemory:
    name = "memory"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self, order: list[str]) -> None:
        self._order = order

    async def start(self, ctx) -> None:
        self._order.append("memory.start")
        self.ctx = ctx
        await ctx.bus.publish(make_message(_TOY_EVENT, source="memory"))

    async def stop(self) -> None:
        self._order.append("memory.stop")

    async def health(self) -> Health:
        return Health.ok()


def _patched_build_factories(order: list[str], toys: dict):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["cognition"] = lambda: toys.setdefault("cognition", _ToyCognition(order))
        factories["memory"] = lambda: toys.setdefault("memory", _ToyMemory(order))
        return factories

    return _build


class TestKernelBootsTwoToySubsystems(unittest.IsolatedAsyncioTestCase):
    async def test_layer_order_health_and_message_exchange(self):
        order: list[str] = []
        toys: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
            kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
            with mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories(order, toys)):
                await kernel.boot()
                try:
                    self.assertEqual(kernel.state.state, RUNNING)
                    # layer 1 (bus, ledger) must have been fully up before layer 2 started
                    self.assertLess(order.index("cognition.start"), len(order))
                    self.assertEqual(kernel._supervisor.services["bus"].status, "ok")  # noqa: SLF001
                    self.assertEqual(kernel._supervisor.services["ledger"].status, "ok")  # noqa: SLF001
                    self.assertEqual(kernel._supervisor.services["cognition"].status, "ok")  # noqa: SLF001
                    self.assertEqual(kernel._supervisor.services["memory"].status, "ok")  # noqa: SLF001
                    # both started concurrently within layer 2, in either order
                    self.assertEqual(set(order[:2]), {"cognition.start", "memory.start"})
                    # the toy's Context was real: memory could publish, cognition received it
                    import asyncio
                    for _ in range(20):
                        await asyncio.sleep(0)
                    self.assertEqual(len(toys["cognition"].received), 1)
                    self.assertEqual(toys["cognition"].received[0].source, "memory")
                finally:
                    await kernel.shutdown()
                self.assertIn("cognition.stop", order)
                self.assertIn("memory.stop", order)

    async def test_toy_subsystem_health_gates_boot_completion(self):
        class _NeverHealthy(_ToyCognition):
            async def health(self) -> Health:
                return Health.down("simulated boot failure")

        toys: dict = {}
        order: list[str] = []

        def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
            factories = kernel_registry.build_factories(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
            factories["cognition"] = lambda: toys.setdefault("cognition", _NeverHealthy(order))
            return factories

        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
            kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
            with mock.patch("simorgh.kernel.service.build_factories", new=_build):
                from simorgh.kernel.service import KernelBootError

                try:
                    with self.assertRaises(KernelBootError):
                        await kernel.boot()
                    from simorgh.kernel.state import FAILED
                    self.assertEqual(kernel.state.state, FAILED)
                finally:
                    await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
