"""A repeated denial opens its own task, with no human in the loop.

The creator, 2026-09-07, watching `denied (policy): ['plan mode: only
read-only tools']` scroll past: "why should [it] take precious time of
creator to review random warning, why sim as a self generative ai doesn't
have basic feature and skill of addressing its own warning".

Before this, `action.denied` had exactly one consumer that did anything
with it -- the Interface, which printed it at a human. Reflection, whose
whole job is turning patterns into work, never subscribed to it. So 25
identical denials in the creator's real ledger produced 25 log lines and
zero tasks.

This test runs the real path end to end: Guardian denies, Reflection
counts, and Planning ends up holding a task about it.
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

_REASON = "plan mode: only read-only tools"


class DenialsBecomeTasksTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.kernel = Kernel(
            LoadedConfig({
                "runtime": {"data_dir": self._tmp.name},
                # Three is enough to mean "again", and keeps the test short.
                "reflection": {"denial_min_repeats": 3},
            }, None),
            secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.reflection = self.kernel._supervisor.services["reflection"].service  # noqa: SLF001
        self.planning = self.kernel._supervisor.services["planning"].service  # noqa: SLF001

    async def asyncTearDown(self) -> None:
        await self.kernel.shutdown()
        self._tmp.cleanup()

    async def _deny(self, *, tool: str = "list_dir", reason: str = _REASON) -> None:
        """Stand exactly where Guardian stands."""
        await self.reflection._on_action_denied(Message.new(  # noqa: SLF001
            topics.ACTION_DENIED, source="guardian",
            payload={"action_id": "a1", "reasons": [reason], "layer": "policy", "tool": tool},
        ))

    async def _wait_for(self, predicate, *, timeout: float = 5.0, what: str = "condition") -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail(f"timed out waiting for {what}")
            await asyncio.sleep(0.02)

    def _tasks_about_denials(self) -> list:
        return [t for t in self.planning._store.all() if "denied" in t.description.lower()]  # noqa: SLF001

    async def test_the_same_denial_repeating_becomes_a_task(self):
        for _ in range(3):
            await self._deny()
        await self._wait_for(lambda: self._tasks_about_denials(), what="a task about the denials")

        [task] = self._tasks_about_denials()
        self.assertIn("list_dir", task.description)
        self.assertIn(_REASON, task.description)

    async def test_one_denial_raises_nothing(self):
        """A single denial is Guardian working correctly. Only repetition
        carries information."""
        await self._deny()
        await asyncio.sleep(0.3)
        self.assertEqual(self._tasks_about_denials(), [])

    async def test_different_denials_are_counted_separately(self):
        await self._deny(tool="list_dir")
        await self._deny(tool="search_code")
        await self._deny(tool="list_dir")
        await asyncio.sleep(0.3)
        self.assertEqual(self._tasks_about_denials(), [])

    async def test_noticing_the_problem_does_not_itself_become_a_flood(self):
        """Twenty-five identical denials must produce one task, not
        twenty-three."""
        for _ in range(25):
            await self._deny()
        await self._wait_for(lambda: self._tasks_about_denials(), what="a task about the denials")
        await asyncio.sleep(0.3)
        self.assertEqual(len(self._tasks_about_denials()), 1)

    async def test_a_denial_with_no_tool_named_is_ignored(self):
        """`layer=classifier` denials carry no reasons, and some carry no
        tool. There is nothing actionable to raise from those."""
        for _ in range(5):
            await self.reflection._on_action_denied(Message.new(  # noqa: SLF001
                topics.ACTION_DENIED, source="guardian",
                payload={"action_id": "a1", "reasons": [], "layer": "classifier"},
            ))
        await asyncio.sleep(0.3)
        self.assertEqual(self._tasks_about_denials(), [])


if __name__ == "__main__":
    unittest.main()
