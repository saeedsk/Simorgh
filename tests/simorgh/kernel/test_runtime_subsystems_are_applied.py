"""`[runtime] subsystems` and `disabled` choose what boots.

Both were parsed into RuntimeConfig and read by nothing until 2026-09-19
(stage 0 item 32): `disabled = ["voice"]` booted voice anyway.
"""
import tempfile
import unittest

from simorgh.kernel.api import RuntimeConfig
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.registry import LAYERS
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import ALWAYS_ON, Kernel, _wanted_subsystems
from tests.simorgh.helpers import FakeClock


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, event, **kw):
        self.warnings.append((event, kw))


class TheSelectionRules(unittest.TestCase):
    def test_all_minus_disabled(self):
        wanted = _wanted_subsystems(RuntimeConfig(disabled=("voice", "benchmark")), LAYERS, _Log())
        self.assertNotIn("voice", wanted)
        self.assertNotIn("benchmark", wanted)
        self.assertIn("orchestration", wanted)

    def test_an_explicit_list_keeps_the_always_on_ones(self):
        log = _Log()
        wanted = _wanted_subsystems(RuntimeConfig(subsystems=("cognition", "orchestration")), LAYERS, log)
        self.assertEqual(wanted, frozenset({"cognition", "orchestration"}) | ALWAYS_ON)

    def test_guardian_cannot_be_disabled_and_saying_so_is_logged(self):
        log = _Log()
        wanted = _wanted_subsystems(RuntimeConfig(disabled=("guardian",)), LAYERS, log)
        self.assertIn("guardian", wanted)
        self.assertIn("runtime_subsystems_always_on", [e for e, _ in log.warnings])

    def test_a_misspelt_name_is_logged_not_silent(self):
        log = _Log()
        _wanted_subsystems(RuntimeConfig(disabled=("vocie",)), LAYERS, log)
        self.assertIn("runtime_subsystems_unknown", [e for e, _ in log.warnings])


class ABootHonoursDisabled(unittest.IsolatedAsyncioTestCase):
    async def test_a_disabled_subsystem_does_not_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = LoadedConfig({"runtime": {"data_dir": tmp, "disabled": ["voice", "benchmark"]}}, None)
            kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
            await kernel.boot()
            try:
                booted = set(kernel._supervisor.services)  # noqa: SLF001
                self.assertNotIn("voice", booted)
                self.assertNotIn("benchmark", booted)
                self.assertIn("guardian", booted)
                self.assertIn("orchestration", booted)
            finally:
                await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
