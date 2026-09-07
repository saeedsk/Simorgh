"""docs/blueprint/subsystems/03-kernel.md section 5.3, S3: "nothing may
execute without the safety path" is enforced by wiring, not hoped for --
when a `SAFETY_CRITICAL` subsystem (`guardian`/`execution`) exhausts its
restart budget, `Supervisor._restart` calls the `on_critical_down`
callback the Kernel gave it, and the Kernel auto-pauses. `test_service.py`
covers `Kernel._on_critical_down` in isolation (called directly); this
proves the real seam -- a toy `guardian` that starts healthy and then
reports `down`, driven through the real `Supervisor.poll_once()` /
`_restart` restart-budget logic, actually reaches the Kernel and pauses
it end-to-end. (Phase 0 has no periodic health-poll driver wired into
`Kernel.boot()` yet -- `poll_once()` is called directly here, standing in
for that future ticker; the wiring under test is what happens once it
fires, not the ticker itself.)"""

import tempfile
import unittest
from unittest import mock

from simorgh.contracts.protocols import Health
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import PAUSED, RUNNING
from tests.simorgh.helpers import FakeClock


class _ToyGuardian:
    name = "guardian"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._healthy = True

    async def start(self, ctx) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> Health:
        return Health.ok() if self._healthy else Health.down("simulated crash")

    def crash(self) -> None:
        self._healthy = False


def _build_with_guardian(guardian: _ToyGuardian):
    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
        factories = kernel_registry.build_factories(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["guardian"] = lambda: guardian
        return factories

    return _build


def _make_kernel(tmp: str, *, max_restarts: int = 0) -> Kernel:
    config = LoadedConfig({"runtime": {"data_dir": tmp, "supervisor_max_restarts_per_10m": max_restarts}}, None)
    return Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())


class TestGuardianDownAutopauses(unittest.IsolatedAsyncioTestCase):
    async def test_guardian_exhausting_its_restart_budget_pauses_the_kernel(self):
        guardian = _ToyGuardian()
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp, max_restarts=0)  # first restart attempt is already over budget
            with mock.patch("simorgh.kernel.service.build_factories", new=_build_with_guardian(guardian)):
                await kernel.boot()
                try:
                    self.assertEqual(kernel.state.state, RUNNING)
                    self.assertEqual(kernel._supervisor.services["guardian"].status, "ok")  # noqa: SLF001

                    guardian.crash()
                    changed = await kernel._supervisor.poll_once()  # noqa: SLF001 -- stands in for the future health ticker

                    self.assertEqual([s.name for s in changed], ["guardian"])
                    self.assertEqual(kernel._supervisor.services["guardian"].status, "down")  # noqa: SLF001
                    self.assertEqual(kernel.state.state, PAUSED)
                finally:
                    await kernel.shutdown()

    async def test_a_non_safety_critical_subsystem_going_down_does_not_pause_the_kernel(self):
        # `bus`/`ledger` are the only real Phase 0 subsystems and neither is
        # SAFETY_CRITICAL -- confirms the auto-pause is guardian/execution
        # specific, not "anything going down pauses the system."
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp, max_restarts=0)
            await kernel.boot()
            try:
                self.assertEqual(kernel.state.state, RUNNING)
                supervised = kernel._supervisor.services["bus"]  # noqa: SLF001
                await kernel._supervisor._restart(supervised)  # noqa: SLF001 -- simulate bus exhausting its own budget
                self.assertEqual(supervised.status, "down")
                self.assertEqual(kernel.state.state, RUNNING)  # unaffected: bus is not SAFETY_CRITICAL
            finally:
                await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
