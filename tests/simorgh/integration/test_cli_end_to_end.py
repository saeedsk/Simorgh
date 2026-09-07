"""End-to-end from a typed CLI line, through the real booted system.

The creator, 2026-09-07, after a wiring bug reached a live run: "why
didn't the unit tests catch this?" They could not. Every package's own
suite proved its half of a seam and passed while the seam itself was
open -- `Profile.scaffold` was rendered by nobody, Cognition's
`task_rules` block was filled by nobody, and a task-create reply that
said `deduplicated_against` was printed as "task created". Each of those
is invisible from inside one package.

So these tests start at the only place a human actually starts: a line
typed at the REPL. They boot the REAL `registry.build_factories()` (all
fifteen subsystems, the same composition
`test_kernel_boots_all_sixteen_subsystems.py` proves healthy), reach into
the booted Interface service, hand it a line through `_handle_line`, and
then assert on what the rest of the system did with it -- the task that
appeared in Planning, and the `cognition.think` request Orchestration
actually put on the bus for it.

Cognition is real here and will answer from its floor provider (no API
keys in a test run); that is fine and deliberate. What is under test is
the request, not the answer: which tools the session was offered, and
whether it was told what finishing means. An observer subscribed to
`cognition.think` sees the same message Cognition does, without replying
to it.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest

from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class CliEndToEndTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # A real clock, not FakeClock: this test waits on work the
        # Orchestration worker does on its own, so time has to move.
        self.kernel = Kernel(
            LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None), secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.interface = self.kernel._supervisor.services["interface"].service  # noqa: SLF001
        self.printed: list[str] = []
        self.interface._out = self.printed.append  # noqa: SLF001 -- stand where the terminal stands

        self.observer = self.kernel.bus
        self.think_requests: list[dict] = []
        self.created_tasks: list[dict] = []
        self._subs = [
            await self.observer.subscribe(topics.COGNITION_THINK, self._see_think),
            await self.observer.subscribe(topics.TASK_CREATED, self._see_task),
        ]

    async def asyncTearDown(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        await self.kernel.shutdown()
        self._tmp.cleanup()

    async def _see_think(self, message) -> None:
        self.think_requests.append(message.payload)

    async def _see_task(self, message) -> None:
        self.created_tasks.append(message.payload)

    async def _type(self, line: str) -> str:
        """One typed REPL line; returns everything printed for it."""
        before = len(self.printed)
        await self.interface._handle_line(line)  # noqa: SLF001
        return "\n".join(self.printed[before:])

    async def _wait_for(self, predicate, *, timeout: float = 10.0, what: str = "condition") -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate():
            if loop.time() >= deadline:
                self.fail(f"timed out waiting for {what}")
            await asyncio.sleep(0.02)

    # -- the seams no single package's tests can see --------------------------------
    async def test_an_improve_line_reaches_cognition_with_the_patch_profiles_tools(self):
        out = await self._type("improve simorgh/hello.py add a module docstring")
        self.assertIn("task created", out)

        await self._wait_for(lambda: bool(self.think_requests), what="a cognition.think request")
        payload = self.think_requests[0]
        self.assertIn("apply_source_patch", payload["tools"])
        self.assertIn("git_commit", payload["tools"])

    async def test_the_patch_session_is_told_to_commit_what_it_applies(self):
        """The live bug: a run applied its edit and stopped, because
        nothing in its prompt said an uncommitted edit is unfinished.
        `Profile.scaffold` -> `scaffolds.render` -> `task_rules`."""
        await self._type("improve simorgh/hello.py add a module docstring")
        await self._wait_for(lambda: bool(self.think_requests), what="a cognition.think request")

        rules = self.think_requests[0].get("task_rules", "")
        self.assertTrue(rules, "cognition.think carried no task_rules block")
        self.assertIn("git_commit", rules)

    async def test_typing_two_similar_improve_lines_creates_two_real_tasks(self):
        """The live bug: three differently-worded `improve` requests all
        printed the *first* one's id and only the first ever ran, because
        Planning's fuzzy dedupe applied to human requests too."""
        first = await self._type("improve docs/A.md clarify the setup section")
        second = await self._type("improve docs/B.md clarify the install section")

        for out in (first, second):
            self.assertIn("task created", out)
            self.assertNotIn("not created", out)
        await self._wait_for(lambda: len(self.created_tasks) >= 2, what="two distinct tasks")
        ids = {t["task_id"] for t in self.created_tasks}
        self.assertGreaterEqual(len(ids), 2, "the second request reused the first task's id")

    async def test_an_unknown_command_does_not_reach_planning_or_cognition(self):
        """The REPL's own parsing is a seam too: a line that is not a
        command must not silently manufacture work."""
        await self._type("tasks")
        await asyncio.sleep(0.1)
        self.assertEqual(self.created_tasks, [])


if __name__ == "__main__":
    unittest.main()
