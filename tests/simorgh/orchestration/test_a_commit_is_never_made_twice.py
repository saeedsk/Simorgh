"""Stage 7 item 7: a checkpoint after every irreversible action.

The drill: SIGKILL between a successful `git_commit` and the step record.
The resumed session sees no commit in its steps, makes the same one again,
and one intention becomes two commits. A checkpoint on the session's own
stream is what the resumed session reads instead of guessing."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.contracts.session import CHECKPOINT, stream_name
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.resume import done_actions
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run

COMMIT = {"tool": "git_commit", "args": {"message": "add the docstring"}}
READ = {"tool": "read_file", "args": {"path": "a.py"}}


class _Execution:
    def __init__(self, bus):
        self._bus, self.ran = bus, []

    async def start(self):
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        self.ran.append(message.payload["tool"])
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True, "output_ref": "",
            "stdout_preview": "[abc1234] add the docstring", "duration_ms": 1, "side_effects": []},
            source="execution"))


class ACommitIsNeverMadeTwice(unittest.TestCase):
    @run
    async def test_the_resumed_session_reads_the_checkpoint_instead_of_repeating(self):
        async with Harness() as h:
            execution = _Execution(h.client("guardian"))
            await execution.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            first = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
            ok, summary, _ = await runner._propose_and_await(first, COMMIT, 1)  # noqa: SLF001
            self.assertTrue(ok)
            self.assertEqual(execution.ran, ["git_commit"])

            events = await h.ledger.read(stream_name("t1"))
            self.assertEqual([e.type for e in events], [CHECKPOINT])
            self.assertEqual(events[0].payload["tool"], "git_commit")

            # The crash: a new session for the same task, its steps empty.
            resumed = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
            resumed.done_actions = await done_actions("t1", h.ledger)
            ok, summary, _ = await runner._propose_and_await(resumed, COMMIT, 1)  # noqa: SLF001
            await execution.stop()

        self.assertTrue(ok)
        self.assertIn("already done", summary)
        self.assertEqual(execution.ran, ["git_commit"], "the commit was not made twice")

    @run
    async def test_a_read_is_not_checkpointed_and_may_repeat(self):
        async with Harness() as h:
            execution = _Execution(h.client("guardian"))
            await execution.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t2", kind="patch", mode="execute", profile=profiles.PATCH)
            await runner._propose_and_await(session, READ, 1)  # noqa: SLF001
            session.done_actions = await done_actions("t2", h.ledger)
            await runner._propose_and_await(session, READ, 2)  # noqa: SLF001
            await execution.stop()
        self.assertEqual(execution.ran, ["read_file", "read_file"], "reading twice costs nothing")
        self.assertEqual(session.done_actions, {})

    @run
    async def test_a_different_commit_is_a_different_action(self):
        async with Harness() as h:
            execution = _Execution(h.client("guardian"))
            await execution.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t3", kind="patch", mode="execute", profile=profiles.PATCH)
            await runner._propose_and_await(session, COMMIT, 1)  # noqa: SLF001
            session.done_actions = await done_actions("t3", h.ledger)
            await runner._propose_and_await(  # noqa: SLF001
                session, {"tool": "git_commit", "args": {"message": "and the test"}}, 2)
            await execution.stop()
        self.assertEqual(execution.ran, ["git_commit", "git_commit"])


if __name__ == "__main__":
    unittest.main()
