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

    async def test_the_tasks_command_prints_the_tasks_not_just_a_count(self):
        """Live-caught (the creator, 2026-09-07): `tasks` printed "100
        task(s), 20 project(s)" and nothing else, so a backlog of a
        hundred looked exactly like a backlog of one.

        This asserts through the REPL rather than on the renderer alone
        because the first attempt at the fix shipped a NameError in the
        render lambda, and `_handle_line`'s crash boundary turned it into
        a printed "[render error]" that no test noticed."""
        await self._type("improve simorgh/hello.py add a module docstring")
        await self._wait_for(lambda: bool(self.created_tasks), what="a task to list")

        out = await self._type("tasks")
        self.assertNotIn("render error", out)
        self.assertIn("task(s)", out)
        # the task's own id and kind, not merely how many there are
        self.assertIn(self.created_tasks[0]["task_id"][:12], out)
        self.assertIn("patch", out)

    async def test_an_unknown_command_does_not_reach_planning_or_cognition(self):
        """The REPL's own parsing is a seam too: a line that is not a
        command must not silently manufacture work."""
        await self._type("tasks")
        await asyncio.sleep(0.1)
        self.assertEqual(self.created_tasks, [])


if __name__ == "__main__":
    unittest.main()


class TestTheCancelCommand(CliEndToEndTestCase):
    """`cancel` exists because until 2026-09-08 nothing could stop a
    running task. The worker takes one at a time, so a task that had
    stopped being useful held the whole system until its step budget ran
    out."""

    async def test_cancel_asks_the_named_task_to_stop(self) -> None:
        seen = []
        sub = await self.kernel.bus.subscribe(topics.TASK_CANCEL, lambda m: seen.append(m.payload) or _aiodone())
        out = await self._type("cancel abc123")
        await self._wait_for(lambda: bool(seen), what="task.cancel on the bus")
        await sub.unsubscribe()
        self.assertTrue(seen, f"cancel must actually publish task.cancel; printed: {out!r}")
        self.assertIn("abc123", out)
        self.assertEqual(seen[0]["task_id"], "abc123")

    async def test_cancel_with_no_task_says_how_to_use_it(self) -> None:
        out = await self._type("cancel")
        self.assertIn("usage", out.lower())
        self.assertIn("task_id", out)


async def _aiodone() -> None:
    return None


class TestABlockedTaskIsNotAnnouncedAsFinished(CliEndToEndTestCase):
    """The worst moment an observer has recorded, and they called it a
    trust event rather than a bug (2026-09-08).

    The claims guard caught the model claiming a commit it never made,
    the edit was discarded, the task was marked blocked -- and the CLI
    then printed "task <id> finished" followed by the fabrication itself,
    rendered as the answer. The human only learned the truth by running
    `git log`. `record.status` was on the line above, used to pick a
    colour.
    """

    async def _finish(self, task_id: str, topic: str, payload: dict) -> str:
        self.interface._watched_tasks.add(task_id)  # noqa: SLF001
        before = len(self.printed)
        await self.kernel.bus.publish(self.kernel.bus.new(topic, payload))
        await self._wait_for(lambda: len(self.printed) > before, what="the outcome line")
        return "\n".join(self.printed[before:])

    async def test_a_rejected_answer_is_never_printed_as_the_reply(self) -> None:
        out = await self._finish("b88dc4d73e08", topics.TASK_BLOCKED, {
            "task_id": "b88dc4d73e08",
            "reason": "the answer claims work the step log does not show: says it committed",
            "result_summary": "The docstring now explains the leading slash, and the change was "
                              "committed with the message 'docs(parser): note the leading slash'.",
        })
        self.assertNotIn("finished", out)
        self.assertNotIn("committed with the message", out,
                         "the fabrication must never be rendered as the answer")

    async def test_it_says_how_the_task_really_ended_and_why(self) -> None:
        out = await self._finish("b88dc4d73e08", topics.TASK_BLOCKED, {
            "task_id": "b88dc4d73e08", "reason": "the answer claims work the step log does not show",
            "result_summary": "all done!",
        })
        self.assertIn("blocked", out)
        self.assertIn("claims work the step log does not show", out)

    async def test_a_real_completion_still_prints_its_answer(self) -> None:
        out = await self._finish("aaaa11112222", topics.TASK_COMPLETED, {
            "task_id": "aaaa11112222", "result_summary": "The answer is 42.",
            "artifacts": [], "verification_ref": "",
        })
        self.assertIn("finished", out)
        self.assertIn("42", out)


class TestChatWhileTheSystemIsPaused(CliEndToEndTestCase):
    """A paused system runs no sessions, so no answer is coming. This
    used to publish the percept and wait 420 seconds for a reply that
    could not arrive -- and the REPL thread blocks on the turn, so the
    prompt froze for seven minutes with `resume`, the one command that
    would fix it, queued behind the block. Only Ctrl-C escaped, and that
    stops the system."""

    async def test_it_says_so_at_once_instead_of_waiting(self) -> None:
        await self.kernel.bus.publish(self.kernel.bus.new(
            topics.SYSTEM_STATE_CHANGED, {"state": "paused", "autonomous_paused": True}))
        await self._wait_for(lambda: self.interface._system_state == "paused",  # noqa: SLF001
                             what="the interface to see the pause")
        out = await self._type("are you paused right now?")
        self.assertIn("paused", out)
        self.assertIn("resume", out)

    async def test_a_running_system_still_takes_chat(self) -> None:
        self.assertEqual(self.interface._system_state, "running")  # noqa: SLF001
