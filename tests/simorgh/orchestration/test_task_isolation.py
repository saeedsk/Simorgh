"""Stage 7 item 1, the typed `Task{agent, brief, isolation, budget}`.

`fresh` (the default) sees only its brief. `fork` starts from a COPY of
what the parent has seen -- so the helper can check the parent's own
work -- and nothing it does reaches the parent's context.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.orchestration import profiles
from simorgh.orchestration.api import Outcome, Session
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run


class _Runner(SessionRunner):
    seen: list = []

    async def run(self, session, *, user_text=""):
        _Runner.seen.append(session)
        session.messages.append({"role": "assistant", "content": "the child's own step"})
        await asyncio.sleep(0)
        return Outcome("completed", result_summary="done")


def _parent():
    parent = Session(task_id="t1", kind="research", mode="execute", profile=profiles.RESEARCH)
    parent.messages = [{"role": "user", "content": "find the release year"},
                       {"role": "assistant", "content": "I read the liner notes: 2009"}]
    return parent


class Isolation(unittest.TestCase):
    def setUp(self):
        _Runner.seen = []

    async def _task(self, parent, args):
        async with Harness() as h:
            runner = _Runner(h.client("orchestration"), h.ledger, clock=h.clock.now, delegation=True)
            return await runner._delegate(parent, {"tool": "task", "args": args})  # noqa: SLF001

    @run
    async def test_fresh_sees_only_the_brief(self):
        await self._task(_parent(), {"brief": "check the year", "agent": "verify"})
        self.assertEqual(_Runner.seen[0].messages, [{"role": "assistant", "content": "the child's own step"}])

    @run
    async def test_fork_starts_from_a_copy_and_leaves_the_parent_alone(self):
        parent = _parent()
        before = [dict(m) for m in parent.messages]
        await self._task(parent, {"brief": "check the year", "agent": "verify", "isolation": "fork"})
        child = _Runner.seen[0]
        self.assertIn("I read the liner notes: 2009", [m["content"] for m in child.messages])
        self.assertEqual(child.messages[len(before)]["content"], "Now, as the helper: check the year")
        self.assertEqual(parent.messages, before, "the child's work reached the parent's context")

    @run
    async def test_budget_is_a_step_count_or_a_mapping(self):
        await self._task(_parent(), {"brief": "a", "budget": {"steps": 5}})
        await self._task(_parent(), {"brief": "b", "budget": 4})
        self.assertEqual([s.budget.max_steps for s in _Runner.seen], [5, 4])

    @run
    async def test_an_unknown_isolation_is_said(self):
        ok, text, _ = await self._task(_parent(), {"brief": "a", "isolation": "shared"})
        self.assertFalse(ok)
        self.assertIn("isolation", text)
        self.assertEqual(_Runner.seen, [])


if __name__ == "__main__":
    unittest.main()
