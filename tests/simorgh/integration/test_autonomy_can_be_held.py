"""`auto off` really stops Sim inventing work.

The creator, 2026-09-07: "stop sim's auto revolution and prevent it from
autonomously starting new projects, researchs and tasks", so that each
kind of task can be put through a watched trial one at a time.

It did not work before. `auto off` publishes a `scope="autonomous"`
pause, which deliberately leaves the system `running` -- a human's
requests must keep being served. The state machine has computed
`autonomous_paused` since it was written, and nothing ever published it
on `system.state.changed` or read it anywhere, so Curiosity saw
`running`, and kept generating projects, research and patches.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class AutonomyHoldTestCase(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, **curiosity) -> Kernel:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        kernel = Kernel(
            LoadedConfig({
                "runtime": {"data_dir": self._tmp.name},
                "curiosity": {"min_explore_interval_seconds": 0.0, **curiosity},
            }, None),
            secrets=EnvSecretStore({}),
        )
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    def _curiosity(self, kernel: Kernel):
        return kernel._supervisor.services["curiosity"].service  # noqa: SLF001

    async def _tick(self, kernel: Kernel) -> dict:
        curiosity = self._curiosity(kernel)
        curiosity._last_tick_record = {}  # noqa: SLF001
        await kernel.bus.publish(kernel.bus.new(topics.SYSTEM_TICK_IDLE, {"idle_seconds": 60.0}))
        for _ in range(200):
            if curiosity._last_tick_record:  # noqa: SLF001
                break
            await asyncio.sleep(0.01)
        return curiosity._last_tick_record  # noqa: SLF001

    async def _control(self, kernel: Kernel, topic: str) -> None:
        """Exactly what `auto off` / `auto on` send. Published as
        `interface`, the only non-kernel source the bus policy lets
        control the system (`topics.PUBLISH_ONLY_BY`)."""
        await kernel.bus.publish(Message.new(
            topic, source="interface",
            payload={"reason": "trial", "requested_by": "human", "scope": "autonomous"},
        ))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if self._curiosity(kernel)._autonomy_paused == (topic == topics.SYSTEM_PAUSE):  # noqa: SLF001
                return

    async def test_auto_off_stops_curiosity_inventing_work(self):
        kernel = await self._boot()
        await self._control(kernel, topics.SYSTEM_PAUSE)
        self.assertEqual((await self._tick(kernel)).get("skipped_reason"), "autonomy_paused")

    async def test_auto_on_lets_it_resume(self):
        kernel = await self._boot()
        await self._control(kernel, topics.SYSTEM_PAUSE)
        await self._control(kernel, topics.SYSTEM_RESUME)
        self.assertNotEqual((await self._tick(kernel)).get("skipped_reason"), "autonomy_paused")

    async def test_a_human_request_still_works_while_autonomy_is_held(self):
        """The whole point of a scoped pause: Sim stops inventing work and
        keeps doing what it is asked."""
        kernel = await self._boot()
        await self._control(kernel, topics.SYSTEM_PAUSE)
        reply = await kernel.bus.request(kernel.bus.new(topics.TASK_CREATE, {
            "kind": "patch", "description": "a task the human asked for",
            "origin": "human", "mode": "execute",
        }), timeout=5.0)
        self.assertTrue(reply.payload.get("task_id"))
        self.assertNotIn("deduplicated_against", reply.payload)

    async def test_a_forced_discover_still_obeys_the_human(self):
        """`discover` is a person asking directly, not self-direction."""
        kernel = await self._boot()
        await self._control(kernel, topics.SYSTEM_PAUSE)
        curiosity = self._curiosity(kernel)
        record = await curiosity._run_tick(force=True)  # noqa: SLF001
        self.assertIsInstance(record, list)
        self.assertNotEqual(curiosity._last_tick_record.get("skipped_reason"), "autonomy_paused")  # noqa: SLF001

    async def test_booting_with_autonomy_off_starts_held(self):
        """Where a fresh boot begins, so a trial run does not have to
        race to turn it off."""
        kernel = await self._boot(autonomy_on_boot=False)
        self.assertTrue(self._curiosity(kernel)._autonomy_paused)  # noqa: SLF001
        self.assertEqual((await self._tick(kernel)).get("skipped_reason"), "autonomy_paused")

    async def test_the_default_boot_is_still_autonomous(self):
        kernel = await self._boot()
        self.assertFalse(self._curiosity(kernel)._autonomy_paused)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
