"""Stage 7 item 1: a helper is a child session with its own agent, its own
budget and its own stream -- and there is a real cap on how many run at
once."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Outcome, Session
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run


class _Runner(SessionRunner):
    """Counts children and never calls a model: `run` is the seam."""

    started: list = []

    async def run(self, session, *, user_text=""):
        _Runner.started.append((session.task_id, session.profile.name, session.budget.max_steps))
        await asyncio.sleep(0)
        return Outcome("completed", result_summary=f"{session.profile.name} says done")


class Helpers(unittest.TestCase):
    def setUp(self):
        _Runner.started = []

    @run
    async def test_a_helper_runs_as_the_agent_it_was_asked_for(self):
        async with Harness() as h:
            runner = _Runner(h.client("orchestration"), h.ledger, clock=h.clock.now, delegation=True)
            parent = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH)
            ok, text, _ = await runner._delegate(parent, {  # noqa: SLF001
                "tool": "task", "args": {"job": "read the plan", "agent": "plan", "steps": 4}})
        self.assertTrue(ok)
        self.assertEqual(_Runner.started[0][1], "plan")
        self.assertEqual(_Runner.started[0][2], 4)
        self.assertIn("plan says done", text)

    @run
    async def test_an_unknown_agent_is_said_not_swapped(self):
        async with Harness() as h:
            runner = _Runner(h.client("orchestration"), h.ledger, clock=h.clock.now, delegation=True)
            parent = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH)
            ok, text, _ = await runner._delegate(parent, {"tool": "task", "args": {  # noqa: SLF001
                "job": "x", "agent": "researcher"}})
        self.assertFalse(ok)
        self.assertIn("no agent called 'researcher'", text)
        self.assertEqual(_Runner.started, [])

    @run
    async def test_the_concurrency_cap_is_real(self):
        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, delegation=True,
                                   max_children=1)
            parent = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH)
            gate = asyncio.Event()

            async def _slow(session, *, user_text=""):
                await gate.wait()
                return Outcome("completed", result_summary="done")

            runner.run = _slow  # noqa: SLF001 -- the seam, as above
            first = asyncio.ensure_future(runner._delegate(parent, {"args": {"job": "one"}}))  # noqa: SLF001
            await asyncio.sleep(0)
            ok, text, _ = await runner._delegate(parent, {"args": {"job": "two"}})  # noqa: SLF001
            gate.set()
            await first
        self.assertFalse(ok)
        self.assertIn("1 at once is the cap", text)

    @run
    async def test_depth_still_stops_a_chain_of_helpers(self):
        async with Harness() as h:
            runner = _Runner(h.client("orchestration"), h.ledger, clock=h.clock.now, delegation=True, max_depth=1)
            deep = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH, depth=1)
            ok, text, _ = await runner._delegate(deep, {"args": {"job": "deeper"}})  # noqa: SLF001
        self.assertFalse(ok)
        self.assertIn("deeper than 1", text)


if __name__ == "__main__":
    unittest.main()
