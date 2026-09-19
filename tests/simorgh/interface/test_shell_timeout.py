"""`[interface] shell_timeout_s` bounds a typed `!<command>`.

The key parsed and nothing read it: `dispatch` ran every `!` with a
hardcoded 120 s (docs/findings/2026-09-19-contract-writing.md)."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts.protocols import Context
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.service import Service
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class _Logger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class TestShellTimeout(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=clock.now)
        self.bus = make_client(backend, source="interface", ledger=self.ledger, clock=clock.now)
        await self.bus.start()
        ctx = Context(
            name="interface", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(InterfaceConfig(shell_timeout_s=0.3, narrate_autonomous=False), run_repl=False)
        await self.service.start(ctx)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def test_a_bang_command_stops_at_the_configured_timeout(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await self.service._handle_line("!sleep 5")
        self.assertIn("[shell timed out after 0.3s]", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
