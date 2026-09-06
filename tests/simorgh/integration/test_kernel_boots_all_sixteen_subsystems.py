"""The definitive proof that the v2 blueprint is not just sixteen
separately-tested packages: it is one system. Every other integration
test in this suite boots a handful of real subsystems together (plus
fakes for the rest) to prove one flow; this test boots the REAL,
unpatched `simorgh.kernel.registry.build_factories()` -- all sixteen
real `Service`s, in the real six-layer order, through the real
`Kernel`/`Supervisor` -- and asserts every single one reports healthy
before the boot completes, then shuts down cleanly.

This is the test `docs/blueprint/00-README.md`'s "definition of done
for the whole system" (`02-system-architecture.md` section 8) points
at: "`python -m simorgh --self-check` boots every subsystem." Unlike
the CLI's own `--self-check` (which deliberately uses two small inline
stub subsystems for the guarded action-path drill, so it can prove the
safety topology without depending on the rest of the build finishing),
this test is the one place the REAL sixteen are all constructed
together, so a wiring mistake in any single `Service.__init__` or a
missing dependency surfaces here, not only in that package's own
narrower integration test.
"""

import tempfile
import unittest

from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.registry import LAYERS
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from tests.simorgh.helpers import FakeClock

ALL_SIXTEEN = frozenset(name for layer in LAYERS for name in layer)


class TestKernelBootsAllSixteenSubsystems(unittest.IsolatedAsyncioTestCase):
    async def test_every_real_subsystem_boots_healthy_and_shuts_down_cleanly(self):
        # 15, not 16: the Kernel itself is the sixteenth blueprint
        # subsystem, but it is the composition root that boots the other
        # fifteen -- it does not appear as an entry in its own LAYERS.
        self.assertEqual(len(ALL_SIXTEEN), 15, "LAYERS should still name exactly the fifteen non-kernel subsystems")

        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
            kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())

            await kernel.boot()
            try:
                self.assertEqual(kernel.state.state, RUNNING)
                services = kernel._supervisor.services  # noqa: SLF001 -- this test's whole point is to inspect every one
                self.assertEqual(
                    set(services.keys()), ALL_SIXTEEN,
                    "every subsystem named in registry.LAYERS must actually have booted",
                )
                unhealthy = {name: svc.status for name, svc in services.items() if svc.status != "ok"}
                self.assertEqual(unhealthy, {}, "every real Service must report healthy after boot")
            finally:
                await kernel.shutdown()

            # A second boot/shutdown cycle on a fresh Kernel over the same
            # data_dir proves the first shutdown released everything it
            # held (ports, files, subscriptions) rather than merely not
            # crashing once.
            kernel2 = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
            await kernel2.boot()
            try:
                self.assertEqual(kernel2.state.state, RUNNING)
                self.assertEqual(set(kernel2._supervisor.services.keys()), ALL_SIXTEEN)  # noqa: SLF001
            finally:
                await kernel2.shutdown()


if __name__ == "__main__":
    unittest.main()
