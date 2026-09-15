"""Helper tasks: fresh context in, report out (design section 5)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run


def _parent(task_id="t-parent", depth=0):
    return Session(task_id=task_id, kind="research", mode="execute", user_text="When was the album released?",
                   profile=replace(profiles.RESEARCH, verify=False, max_steps=8), budget=Budget(max_steps=8), depth=depth)


class Delegation(unittest.TestCase):
    @run
    async def test_the_parent_sees_only_the_helpers_report(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "delegate", "args": {"job": "find the release year", "steps": 4}}]},
                {"tool_calls": [{"tool": "read_file", "args": {"path": "discography.md"}}]},
                {"text": "It was released in 2009.\n- discography.md line 12 gives 2009"},
                {"text": "It was released in 2009."},
            ])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   delegation=True)
            session = _parent()
            outcome = await runner.run(session, user_text="When was the album released?")
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertIn("delegate", cognition.calls[0].payload["tools"])
            self.assertEqual(cognition.calls[1].payload["messages"][-1]["content"].count("Your one job"), 1,
                             "the helper starts from its brief")
            views = ["\n".join(str(m.get("content")) for m in c.payload["messages"]) for c in cognition.calls]
            parent_view = next(v for v in views if "Helper t-parent-h1" in v)
            self.assertIn("discography.md line 12 gives 2009", parent_view, "the report came back")
            self.assertNotIn("Result of read_file", parent_view, "the helper's steps did not")
            child_events = await h.ledger.read("task:t-parent-h1")
            self.assertTrue([e for e in child_events if e.type == topics.TASK_STEP], "the helper keeps its own stream")
            self.assertEqual(session.steps[0].tool, "delegate")
            self.assertTrue(session.steps[0].ok)
            await cognition.stop(); await gx.stop()

    @run
    async def test_not_offered_when_off_or_at_the_depth_cap(self):
        for runner_kwargs, depth in (({}, 0), ({"delegation": True, "max_depth": 1}, 1)):
            async with Harness() as h:
                cognition = FakeCognition(h.client("cognition"), script=[{"text": "done"}])
                await cognition.start()
                runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                       **runner_kwargs)
                await runner.run(_parent(depth=depth), user_text="x")
                self.assertNotIn("delegate", cognition.calls[0].payload["tools"], (runner_kwargs, depth))
                await cognition.stop()

    @run
    async def test_a_raw_marker_argument_is_split_into_job_and_steps(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "delegate", "args": {"argument": "find the release year\n{\"steps\": 3}"}}]},
                {"text": "It was 2009.\n- from the discography"},
                {"text": "2009."},
            ])
            await cognition.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   delegation=True)
            session = _parent("t-raw")
            outcome = await runner.run(session, user_text="When?")
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            brief = "\n".join(str(m.get("content")) for m in cognition.calls[1].payload["messages"])
            self.assertIn("Your one job: find the release year", brief)
            self.assertNotIn("steps", brief.split("Your one job:")[1].split("\n")[0], "the JSON is not part of the job")
            self.assertTrue(session.steps[0].ok, session.steps[0].summary)
            await cognition.stop()

    @run
    async def test_a_delegate_with_no_job_is_refused_not_run(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "delegate", "args": {}}]}, {"text": "fine"}])
            await cognition.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   delegation=True)
            session = _parent("t-nojob")
            await runner.run(session, user_text="x")
            self.assertFalse(session.steps[0].ok)
            self.assertIn("refused", session.steps[0].summary)
            await cognition.stop()


if __name__ == "__main__":
    unittest.main()
