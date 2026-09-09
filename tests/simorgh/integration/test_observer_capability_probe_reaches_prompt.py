"""Observer W21-09: does a failed capability probe actually reach the
prompt in a real boot?

`execution/capabilities.py` probes run in the background at Execution
boot, publish `tool.probed`, and `orchestration/service.py` folds them
into `scaffolds._UNAVAILABLE`, rendered into `task_rules` by
`scaffolds.unavailable_note`. This crosses three subsystems over the
bus. Unit tests of each half pass; this checks the seam, the same way
`test_cli_end_to_end.py` does for `Profile.scaffold`.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class CapabilityProbeReachesPromptTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # Make `node` (and therefore `render_page`) look absent, regardless
        # of whether this machine actually has node on PATH.
        self._which_patcher = mock.patch(
            "simorgh.execution.capabilities.shutil.which",
            side_effect=lambda name: None if name == "node" else "/usr/bin/" + name,
        )
        self._which_patcher.start()
        self.kernel = Kernel(
            LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None), secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.interface = self.kernel._supervisor.services["interface"].service  # noqa: SLF001
        self.printed: list[str] = []
        self.interface._out = self.printed.append  # noqa: SLF001

        self.observer = self.kernel.bus
        self.think_requests: list[dict] = []
        self._subs = [
            await self.observer.subscribe(topics.COGNITION_THINK, self._see_think),
        ]

    async def asyncTearDown(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        await self.kernel.shutdown()
        self._which_patcher.stop()
        self._tmp.cleanup()

    async def _see_think(self, message) -> None:
        self.think_requests.append(message.payload)

    async def _wait_for(self, predicate, *, timeout: float = 10.0, what: str = "condition") -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail(f"timed out waiting for {what}")
            await asyncio.sleep(0.02)

    async def test_a_missing_node_warning_reaches_a_render_page_sessions_task_rules(self):
        # Let the background probe task actually run and its result travel
        # execution -> bus -> orchestration -> scaffolds before we ask for
        # a task that offers render_page.
        await self._wait_for(
            lambda: "node" in self._probed_names(), timeout=10.0, what="the node probe to publish",
        )

        out = await self.interface._handle_line(  # noqa: SLF001
            "improve simorgh/hello.py render https://example.com and describe it"
        )
        await self._wait_for(lambda: bool(self.think_requests), what="a cognition.think request")

        payload = self.think_requests[0]
        rules = payload.get("task_rules", "")
        tools = payload.get("tools", [])
        if "render_page" not in tools:
            self.skipTest("this profile did not offer render_page; nothing to warn about")
        self.assertIn(
            "render_page", rules,
            f"render_page was offered but no unavailable-capability warning reached task_rules: {rules!r}",
        )

    def _probed_names(self) -> set[str]:
        from simorgh.orchestration import scaffolds
        return set(scaffolds._UNAVAILABLE.keys())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
