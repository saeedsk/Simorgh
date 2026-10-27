"""Stage 17 item 8: a native-dialect session is told that independent
lookups may go in one reply -- when `parallel_read_tools` > 1, and only
then; a default session's prompts are unchanged."""

import asyncio
import unittest
from dataclasses import replace

from simorgh.orchestration import profiles, scaffolds
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

LINE = "Independent lookups may be requested together in one reply."


class ParallelCallsAreAskedFor(unittest.TestCase):
    async def _second_think(self, parallel_read_tools, *, native=True):
        call = {"tool": "read_file", "args": {"path": "a.md"}}
        if native:
            call["id"] = "c1"
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[{"tool_calls": [call]}, {"text": "done"}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   parallel_read_tools=parallel_read_tools)
            session = Session(task_id="t1", kind="research", mode="execute", user_text="read a.md",
                              profile=replace(profiles.RESEARCH, verify=False, max_steps=4), budget=Budget(max_steps=4))
            await asyncio.wait_for(runner.run(session, user_text="read a.md"), timeout=10)
            await cognition.stop(); await gx.stop()
        first, second = cognition.calls[:2]
        return first.payload, second.payload

    @run
    async def test_a_native_session_is_told_when_several_may_run(self):
        first, second = await self._second_think(4)
        self.assertIn(LINE, second["messages"][-1]["content"])
        self.assertNotIn(LINE, second["task_rules"], "not in the cacheable prefix")
        self.assertEqual(first["task_rules"], second["task_rules"])

    @run
    async def test_one_call_per_reply_leaves_the_prompt_as_it_was(self):
        _, second = await self._second_think(1)
        everything = "\n".join(str(m.get("content")) for m in second["messages"]) + second["task_rules"]
        self.assertNotIn(LINE, everything)
        self.assertTrue(second["messages"][-1]["content"].endswith("Otherwise take the next step."))

    @run
    async def test_a_marker_session_gets_no_native_line(self):
        _, second = await self._second_think(4, native=False)
        everything = "\n".join(str(m.get("content")) for m in second["messages"]) + second["task_rules"]
        self.assertNotIn(LINE, everything, "the marker dialect has Cognition's own line")

    def test_the_line(self):
        self.assertEqual(scaffolds.parallel_line(4), LINE)
        self.assertEqual(scaffolds.parallel_line(1), "")
        self.assertEqual(scaffolds.parallel_line(0), "")


if __name__ == "__main__":
    unittest.main()
