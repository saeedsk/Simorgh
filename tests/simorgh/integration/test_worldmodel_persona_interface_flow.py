"""Phase 1 Track C acceptance: proves World Model, Persona, and Interface
as three *real* `Service`s booted by the real `simorgh.kernel.Supervisor`
-- not just unit-tested in isolation. Follows the injection seam
`test_kernel_boot_two_toy_subsystems.py` establishes (patching
`simorgh.kernel.service.build_factories`) rather than editing
`simorgh/kernel/registry.py`'s `build_factories()` directly: a sibling
fork building cognition/memory in this same working directory annotated
that module's docstring this session asking every subsystem-track fork
to use exactly this seam instead of concurrent edits to a shared file,
and `simorgh.kernel.registry.LAYERS` already names `worldmodel`/`persona`/
`interface` (registry.py itself needed no edit --  `known_layers()`
already includes them once a factory exists for them).

Proves, over one real Kernel boot:
  1. `world.env.query{what:capability_map}` against THIS real repository
     returns real, non-empty area/module names.
  2. A percept nudges Persona's real mood (not a toy) -- `persona.state.changed`
     observed.
  3. Interface's own `pause` -> `status` -> `resume` command dispatch
     round-trips through the real Kernel state machine (Flow 5).
  4. The CLI degrades honestly, never hangs or crashes, when cognition/
     memory are absent from this boot (they are not registered here).
"""

import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import topics
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.service import Service as InterfaceService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import PAUSED, RUNNING
from simorgh.persona.config import Config as PersonaConfig
from simorgh.persona.service import Service as PersonaService
from simorgh.worldmodel.config import Config as WorldConfig
from simorgh.worldmodel.service import Service as WorldModelService

from tests.simorgh.helpers import FakeClock

REPO_ROOT = Path(__file__).resolve().parents[3]


async def _pump(n: int = 40) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _patched_build_factories(instances: dict):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False):
        # `real()` now wires every subsystem (docs/EVOLUTION.md milestone
        # 103) -- when this test was first written it returned only
        # bus/ledger, so filtering down to that is what actually keeps
        # cognition/memory "absent from this boot" true for test 4, rather
        # than relying on `real()`'s own (now much larger) output.
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["worldmodel"] = lambda: instances.setdefault(
            "worldmodel", WorldModelService(WorldConfig(repo_root=REPO_ROOT)))
        factories["persona"] = lambda: instances.setdefault(
            "persona", PersonaService(PersonaConfig(repo_root=REPO_ROOT, decay_interval_s=5.0)))
        factories["interface"] = lambda: instances.setdefault(
            "interface", InterfaceService(InterfaceConfig(chat_reply_timeout_s=0.3), run_repl=False))
        return factories

    return _build


class WorldModelPersonaInterfaceFlowTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.instances: dict = {}
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
        self._patcher = mock.patch(
            "simorgh.kernel.service.build_factories", new=_patched_build_factories(self.instances),
        )
        self._patcher.start()
        await self.kernel.boot()

    async def asyncTearDown(self):
        await self.kernel.shutdown()
        self._patcher.stop()
        self._tmp.cleanup()

    async def test_booted_through_the_real_supervisor_healthy(self):
        for name in ("bus", "ledger", "worldmodel", "persona", "interface"):
            self.assertEqual(self.kernel._supervisor.services[name].status, "ok")  # noqa: SLF001

    async def test_capability_map_against_the_real_repository(self):
        reply = await self.kernel.bus.request(
            self.kernel.bus.new(topics.WORLD_ENV_QUERY, {"what": "capability_map"}), timeout=3,
        )
        self.assertTrue(reply.payload["ok"])
        self.assertTrue(reply.payload["areas"])  # real, non-empty area list from this repo's src/
        self.assertIn("orchestrator", reply.payload["areas"])
        self.assertTrue(reply.payload["modules_by_area"]["orchestrator"])

    async def test_percept_nudges_personas_real_mood(self):
        seen = []
        sub = await self.kernel.bus.subscribe(
            topics.PERSONA_STATE_CHANGED, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.kernel.bus.publish(self.kernel.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": "this is wonderful, thank you!", "session_id": "s1",
        }))
        await _pump()
        await sub.unsubscribe()
        self.assertTrue(seen, "expected persona.state.changed after a positive percept")
        self.assertGreater(seen[0].payload["valence"], seen[0].payload["previous"]["valence"])

    async def test_interface_pause_status_resume_round_trips_through_the_real_kernel(self):
        interface = self.instances["interface"]

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await interface._handle_line("pause")
            await _pump()
        self.assertEqual(self.kernel.state.state, PAUSED)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await interface._handle_line("status")
            await _pump()
        self.assertIn("paused", out.getvalue())

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await interface._handle_line("resume")
            await _pump()
        self.assertEqual(self.kernel.state.state, RUNNING)

    async def test_cli_degrades_honestly_when_cognition_and_memory_are_absent(self):
        """No `cognition`/`memory` factory is registered in this boot
        (see `_patched_build_factories` above) -- exactly the situation
        the real Kernel will be in for stretches of this build."""
        self.assertNotIn("cognition", self.kernel._supervisor.services)  # noqa: SLF001
        self.assertNotIn("memory", self.kernel._supervisor.services)  # noqa: SLF001
        interface = self.instances["interface"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await asyncio.wait_for(interface._handle_line("hello, anyone there?"), timeout=2.0)
        self.assertIn("no response", out.getvalue())


if __name__ == "__main__":
    unittest.main()
